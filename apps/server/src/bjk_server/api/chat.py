"""채팅 기록 API (API 명세서 3-3 CHAT)."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from bjk_review import OrderRequest
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from bjk_server import clock, idempotency, ratelimit
from bjk_server.api.maintenance import mark_completed
from bjk_server.audit.counts import delivered_requests
from bjk_server.audit.flags import check_after_record
from bjk_server.auth import CurrentUser, TenantDB
from bjk_server.chat.interpreter import Interpreter, get_interpreter
from bjk_server.chat.matching import QueryEmbedder, get_query_embedder
from bjk_server.chat.records import (
    RecordResponse,
    Triggered,
    learn_alias,
    movement_out,
    record_movement,
    resolve_equipment,
    resolve_part,
    to_base_qty,
)
from bjk_server.chat.schemas import MessageRequest, MessageResponse
from bjk_server.chat.service import handle_message
from bjk_server.db.models import ChatEntry, ChatMessage, Part, Supplier
from bjk_server.errors import ApiError, ErrorCode
from bjk_server.pagination import Page, PageParams, keyset_page, page_params
from bjk_server.reviews.service import ReviewRunner, create_review, get_review_runner
from bjk_server.security import TokenClaims

router = APIRouter(prefix="/chat", tags=["chat"])

MESSAGES_PER_MINUTE = 20


@router.post("/messages", response_model=MessageResponse)
def post_message(
    body: MessageRequest,
    user: CurrentUser,
    db: TenantDB,
    interpreter: Annotated[Interpreter, Depends(get_interpreter)],
    embedder: Annotated[QueryEmbedder | None, Depends(get_query_embedder)],
):
    """CHAT-01. 메시지 → 추출 결과·확인 카드. 해석 실패 시 폼 입력 카드로 대체."""
    ratelimit.hit(db.get_bind(), f"chat:{user.user_id}", MESSAGES_PER_MINUTE, 60)
    stored = idempotency.claim(
        db,
        user.company_id,
        "chat_message",
        body.client_message_id,
        user.user_id,
        body.model_dump(mode="json"),
    )
    if stored:
        return JSONResponse(stored.body, stored.status_code)
    result = handle_message(
        db, user, body.client_message_id, body.text, interpreter, embedder=embedder
    )
    idempotency.complete(
        db,
        user.company_id,
        "chat_message",
        body.client_message_id,
        200,
        result.model_dump(mode="json"),
    )
    return result


class ConfirmRequest(BaseModel):
    """선택·수정한 값만 보낸다. 비우면 카드의 값을 쓴다."""

    part_id: uuid.UUID | None = None
    qty: int | None = Field(default=None, ge=1)
    equipment_id: uuid.UUID | None = None
    # PURCHASE_REQUEST, IN(발주 대조)
    supplier_id: uuid.UUID | None = None
    unit_price: int | None = Field(default=None, ge=0)


def _own_entry(db: Session, user: TokenClaims, entry_id: uuid.UUID) -> ChatEntry:
    entry = db.scalar(select(ChatEntry).where(ChatEntry.id == entry_id).with_for_update())
    # 다른 사람의 카드는 없는 것으로 취급한다.
    if entry is None or entry.user_id != user.user_id:
        raise ApiError(ErrorCode.NOT_FOUND, "확인 카드를 찾을 수 없습니다.")
    if entry.status != "open":
        raise ApiError(
            ErrorCode.ALREADY_CONFIRMED, "이미 처리된 카드입니다.", {"status": entry.status}
        )
    return entry


def _uuid(value: str | None) -> uuid.UUID | None:
    return uuid.UUID(value) if value else None


class MaintenanceDoneResponse(BaseModel):
    intent: Literal["MAINTENANCE_DONE"]
    maintenance_id: uuid.UUID
    equipment_id: uuid.UUID
    completed_at: datetime
    reply: str


class PurchaseRequestResponse(BaseModel):
    intent: Literal["PURCHASE_REQUEST"]
    review_id: uuid.UUID
    status: Literal["reviewing"]
    reply: str


ConfirmResponse = RecordResponse | MaintenanceDoneResponse | PurchaseRequestResponse


@router.post("/entries/{entry_id}/confirm", response_model=ConfirmResponse)
def confirm_entry(
    entry_id: uuid.UUID,
    body: ConfirmRequest,
    user: CurrentUser,
    db: TenantDB,
    runner: Annotated[ReviewRunner, Depends(get_review_runner)],
) -> ConfirmResponse:
    """CHAT-03. 확인 카드 확정 → 의도별 처리.

    OUT·IN 기록, MAINTENANCE_DONE 정비 완료, PURCHASE_REQUEST 직원 요청 검토 생성.
    """
    now = clock.utcnow()
    entry = _own_entry(db, user, entry_id)
    if entry.expires_at <= now:
        raise ApiError(ErrorCode.ENTRY_EXPIRED, "다시 보내 주세요.")
    if entry.intent == "MAINTENANCE_DONE":
        return _confirm_maintenance(db, user, entry, now)
    if entry.intent == "PURCHASE_REQUEST":
        return _confirm_purchase(db, user, entry, body, runner, now)
    if entry.type == "form" or entry.intent not in ("OUT", "IN"):
        raise ApiError(
            ErrorCode.VALIDATION_ERROR, "이 카드는 폼 입력으로 기록해 주세요.", {"type": entry.type}
        )

    payload = entry.payload
    part_id = body.part_id or _uuid(payload.get("part_id"))
    if (
        entry.type == "select"
        and body.part_id
        and str(body.part_id) not in payload["candidate_ids"]
    ):
        raise ApiError(ErrorCode.PART_NOT_RESOLVED, "후보 중에서 골라 주세요.")
    part = resolve_part(db, part_id)
    qty = body.qty or to_base_qty(payload.get("qty"), payload.get("unit"), part.pack_qty)
    if not qty:
        raise ApiError(ErrorCode.VALIDATION_ERROR, "수량을 입력해 주세요.", {"field": "qty"})
    equipment_id = resolve_equipment(db, body.equipment_id or _uuid(payload.get("equipment_id")))

    intent: Literal["IN", "OUT"] = entry.intent
    movement, stock, reply = record_movement(
        db,
        user,
        intent,
        part,
        qty,
        equipment_id,
        payload.get("source_text"),
        entry.message_id,
        supplier_id=body.supplier_id or _uuid(payload.get("supplier_id")),
        unit_price=body.unit_price if body.unit_price is not None else payload.get("unit_price"),
    )
    result = RecordResponse(
        intent=intent,
        movement=movement_out(movement),
        stock_after=stock,
        reply=reply,
        alias_learned=learn_alias(db, payload.get("part_text"), part),
        triggered=Triggered(audit_flag_id=check_after_record(db, part, movement, stock)),
    )
    entry.status, entry.decided_at = "confirmed", now
    entry.result = result.model_dump(mode="json")
    return result


def _confirm_maintenance(
    db: Session, user: TokenClaims, entry: ChatEntry, now: datetime
) -> MaintenanceDoneResponse:
    """F-CHAT-06. 정비 완료(SET-09)와 같은 결과를 남긴다."""
    m = mark_completed(db, user, uuid.UUID(entry.payload["maintenance_id"]), now)
    result = MaintenanceDoneResponse(
        intent="MAINTENANCE_DONE",
        maintenance_id=m.id,
        equipment_id=m.equipment_id,
        completed_at=now,
        reply="정비 완료로 기록했어요.",
    )
    entry.status, entry.decided_at = "confirmed", now
    entry.result = result.model_dump(mode="json")
    return result


def _candidate_part(entry: ChatEntry, part_id: uuid.UUID | None) -> uuid.UUID | None:
    if entry.type == "select" and part_id and str(part_id) not in entry.payload["candidate_ids"]:
        raise ApiError(ErrorCode.PART_NOT_RESOLVED, "후보 중에서 골라 주세요.")
    return part_id


def _confirm_purchase(
    db: Session,
    user: TokenClaims,
    entry: ChatEntry,
    body: ConfirmRequest,
    runner: ReviewRunner,
    now: datetime,
) -> PurchaseRequestResponse:
    """F-CHAT-04. 확정한 요청으로 직원 요청 검토를 만든다. 검토는 커밋 뒤 돌린다."""
    payload = entry.payload
    part = resolve_part(db, _candidate_part(entry, body.part_id) or _uuid(payload.get("part_id")))
    qty = body.qty or to_base_qty(payload.get("qty"), payload.get("unit"), part.pack_qty)
    supplier_id = body.supplier_id or _uuid(payload.get("supplier_id"))
    if supplier_id is None and entry.type == "select" and part.default_supplier_id:
        # 선택 카드는 부품을 고른 뒤에야 기본 공급사를 알 수 있다.
        supplier_id = part.default_supplier_id
    unit_price = body.unit_price if body.unit_price is not None else payload.get("unit_price")
    result = request_purchase(
        db,
        user,
        runner,
        part,
        qty,
        supplier_id,
        unit_price,
        entry.message_id,
        payload.get("source_text"),
    )
    entry.status, entry.decided_at = "confirmed", now
    entry.result = result.model_dump(mode="json")
    return result


def request_purchase(
    db: Session,
    user: TokenClaims,
    runner: ReviewRunner,
    part: Part,
    qty: int | None,
    supplier_id: uuid.UUID | None,
    unit_price: int | None,
    message_id: uuid.UUID | None,
    text: str | None,
) -> PurchaseRequestResponse:
    """직원 요청 검토 생성 (F-REVIEW-01 입구 staff_request). 카드 확정과 폼 입력이 함께 쓴다."""
    if not qty:
        raise ApiError(ErrorCode.VALIDATION_ERROR, "수량을 입력해 주세요.", {"field": "qty"})
    if supplier_id is not None and db.get(Supplier, supplier_id) is None:
        raise ApiError(ErrorCode.NOT_FOUND, "공급사를 찾을 수 없습니다.")
    order = OrderRequest(
        qty=qty, supplier_id=str(supplier_id) if supplier_id else None, unit_price=unit_price
    )
    review = create_review(
        db,
        user.company_id,
        entry="staff_request",
        order=order,
        part_id=part.id,
        requested_by=user.user_id,
        source_message_id=message_id,
        text=text,
    )
    runner.start_after_commit(db, user.company_id, review.id)
    return PurchaseRequestResponse(
        intent="PURCHASE_REQUEST",
        review_id=review.id,
        status="reviewing",
        reply="검토해서 사장님께 올렸어요.",
    )


class CancelResponse(BaseModel):
    entry_id: uuid.UUID
    status: Literal["cancelled"]


@router.post("/entries/{entry_id}/cancel", response_model=CancelResponse)
def cancel_entry(entry_id: uuid.UUID, user: CurrentUser, db: TenantDB) -> CancelResponse:
    """CHAT-04. 확인 카드 취소. 원장은 바뀌지 않는다."""
    entry = _own_entry(db, user, entry_id)
    entry.status, entry.decided_at = "cancelled", clock.utcnow()
    return CancelResponse(entry_id=entry.id, status="cancelled")


class FormEntryRequest(BaseModel):
    client_message_id: str = Field(min_length=1, max_length=128)
    type: Literal["OUT", "IN", "PURCHASE_REQUEST"]
    part_id: uuid.UUID
    qty: int = Field(ge=1)
    equipment_id: uuid.UUID | None = None
    # PURCHASE_REQUEST: 비우면 기본 공급사·등록 단가로 검토한다. IN: 주면 발주와 대조한다.
    supplier_id: uuid.UUID | None = None
    unit_price: int | None = Field(default=None, ge=0)


@router.post("/entries", response_model=RecordResponse | PurchaseRequestResponse)
def form_entry(
    body: FormEntryRequest,
    user: CurrentUser,
    db: TenantDB,
    runner: Annotated[ReviewRunner, Depends(get_review_runner)],
):
    """CHAT-05. 폼 입력. 확인 카드 없이 바로 기록한다(ai 실패 시 대체 경로)."""
    stored = idempotency.claim(
        db,
        user.company_id,
        "chat_entry",
        body.client_message_id,
        user.user_id,
        body.model_dump(mode="json"),
    )
    if stored:
        return JSONResponse(stored.body, stored.status_code)

    part = resolve_part(db, body.part_id)
    if body.type == "PURCHASE_REQUEST":
        result = request_purchase(
            db, user, runner, part, body.qty, body.supplier_id, body.unit_price, None, None
        )
        return _store_form(db, user, body, result)
    equipment_id = resolve_equipment(db, body.equipment_id)
    movement, stock, reply = record_movement(
        db,
        user,
        body.type,
        part,
        body.qty,
        equipment_id,
        source_text=None,
        supplier_id=body.supplier_id if body.type == "IN" else None,
        unit_price=body.unit_price if body.type == "IN" else None,
    )
    result = RecordResponse(
        intent=body.type,
        movement=movement_out(movement),
        stock_after=stock,
        reply=reply,
        triggered=Triggered(audit_flag_id=check_after_record(db, part, movement, stock)),
    )
    return _store_form(db, user, body, result)


def _store_form(db: Session, user: TokenClaims, body: FormEntryRequest, result: BaseModel):
    """폼 입력을 확정된 form 카드로 남기고 멱등 응답을 저장한다."""
    now = clock.utcnow()
    db.add(
        ChatEntry(
            company_id=user.company_id,
            user_id=user.user_id,
            type="form",
            intent=body.type,
            status="confirmed",
            payload=body.model_dump(mode="json"),
            expires_at=now,
            decided_at=now,
            result=result.model_dump(mode="json"),
        )
    )
    body_json = result.model_dump(mode="json")
    idempotency.complete(db, user.company_id, "chat_entry", body.client_message_id, 200, body_json)
    return result


class HistoryCard(BaseModel):
    entry_id: uuid.UUID
    type: str
    status: Literal["open", "confirmed", "cancelled", "expired"]
    expires_at: datetime


class HistoryMessage(BaseModel):
    message_id: uuid.UUID
    client_message_id: str
    text: str
    intent: str
    reply: str
    created_at: datetime
    cards: list[HistoryCard]


def _card_status(entry: ChatEntry, now: datetime) -> str:
    if entry.status == "open" and entry.expires_at <= now:
        return "expired"
    return entry.status


@router.get("/messages", response_model=Page[HistoryMessage])
def history(
    user: CurrentUser, db: TenantDB, params: Annotated[PageParams, Depends(page_params)]
) -> Page[HistoryMessage]:
    """CHAT-02. 내 대화 이력. 최신순, 카드 상태(open·confirmed·cancelled·expired) 포함."""
    stmt = select(ChatMessage).where(ChatMessage.user_id == user.user_id)
    page = keyset_page(
        db,
        stmt,
        [ChatMessage.created_at, ChatMessage.id],
        params,
        to_item=lambda r: r.ChatMessage,
        cursor_of=lambda r: [r.ChatMessage.created_at, r.ChatMessage.id],
        descending=True,
    )
    entries = db.scalars(
        select(ChatEntry)
        .where(ChatEntry.message_id.in_([m.id for m in page.items]))
        .order_by(ChatEntry.created_at, ChatEntry.id)
    ).all()
    now = clock.utcnow()
    cards: dict[uuid.UUID, list[HistoryCard]] = {}
    for e in entries:
        cards.setdefault(e.message_id, []).append(
            HistoryCard(
                entry_id=e.id, type=e.type, status=_card_status(e, now), expires_at=e.expires_at
            )
        )
    items = [
        HistoryMessage(
            message_id=m.id,
            client_message_id=m.client_message_id,
            text=m.text,
            intent=m.intent,
            reply=m.reply,
            created_at=m.created_at,
            cards=cards.get(m.id, []),
        )
        for m in page.items
    ]
    return Page(items=items, next_cursor=page.next_cursor)


class InboxItem(BaseModel):
    id: uuid.UUID
    kind: Literal["count_request"]
    text: str
    created_at: datetime
    count_request_id: uuid.UUID


class Inbox(BaseModel):
    items: list[InboxItem]


@router.get("/inbox", response_model=Inbox)
def inbox(user: CurrentUser, db: TenantDB) -> Inbox:
    """시스템이 먼저 보낸 메시지(명세 밖, #275). 지금은 응답을 기다리는 내 실사 요청뿐이다.

    블라인드 실사(F-AUDIT-06)라 장부 수량은 담지 않는다. 응답은 채팅 `COUNT` 의도나 AUD-03으로 한다.
    `created_at`은 전달 시각(예약 건은 예약 시각)이고 오래된 요청부터 준다.
    """
    return Inbox(
        items=[
            InboxItem(
                id=r.id,
                kind="count_request",
                text=r.message,
                created_at=r.sent_at or r.scheduled_for,
                count_request_id=r.id,
            )
            for r in delivered_requests(db, user.user_id, clock.utcnow())
        ]
    )
