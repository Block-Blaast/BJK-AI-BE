"""발주 API (API 명세서 8장 PO-01~04, F-APPROVAL-02·03)."""

import uuid
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from bjk_server import clock
from bjk_server.auth import TenantDB, require_role
from bjk_server.db.models import Part, PurchaseOrder, ReviewSnapshot, Supplier, User
from bjk_server.domain.purchase_order import (
    OrderStateConflict,
    PoStatus,
    cancel,
    mark_ordered,
    order_message,
)
from bjk_server.errors import ApiError, ErrorCode
from bjk_server.pagination import Page, PageParams, keyset_page, page_params
from bjk_server.purchasing.receipt import lead_time_days
from bjk_server.security import TokenClaims

router = APIRouter(prefix="/purchase-orders", tags=["purchase-orders"])

Manager = Annotated[TokenClaims, Depends(require_role("manager"))]


class Ref(BaseModel):
    id: uuid.UUID
    name: str


class PurchaseOrderOut(BaseModel):
    id: uuid.UUID
    review_id: uuid.UUID | None
    part: Ref
    supplier: Ref
    qty: int
    unit_price: int
    total: int
    status: PoStatus
    approved_at: datetime
    approved_by: str | None
    ordered_at: datetime | None
    ordered_by: str | None
    received_qty: int
    received_at: datetime | None
    # 주문 완료 → 입고 완료 일수. 주문 완료 표시 없이 입고된 건은 납기 표본에서 빼 null
    actual_lead_time_days: int | None


Approver = aliased(User)
Orderer = aliased(User)


def _select():
    return (
        select(
            PurchaseOrder,
            Part.name.label("part_name"),
            Supplier.name.label("supplier_name"),
            Approver.name.label("approved_by_name"),
            Orderer.name.label("ordered_by_name"),
        )
        .join(Part, Part.id == PurchaseOrder.part_id)
        .join(Supplier, Supplier.id == PurchaseOrder.supplier_id)
        .outerjoin(Approver, Approver.id == PurchaseOrder.approved_by)
        .outerjoin(Orderer, Orderer.id == PurchaseOrder.ordered_by)
    )


def order_out(row) -> PurchaseOrderOut:
    po: PurchaseOrder = row.PurchaseOrder
    days = None
    if po.received_at and po.ordered_at and not po.implicit_order:
        days = lead_time_days(po.ordered_at, po.received_at)
    return PurchaseOrderOut(
        id=po.id,
        review_id=po.review_id,
        part=Ref(id=po.part_id, name=row.part_name),
        supplier=Ref(id=po.supplier_id, name=row.supplier_name),
        qty=po.qty,
        unit_price=po.unit_price,
        total=po.qty * po.unit_price,
        status=po.status,  # type: ignore[arg-type]
        approved_at=po.approved_at,
        approved_by=row.approved_by_name,
        ordered_at=po.ordered_at,
        ordered_by=None if po.implicit_order else row.ordered_by_name,
        received_qty=po.received_qty,
        received_at=po.received_at,
        actual_lead_time_days=days,
    )


@router.get("", response_model=Page[PurchaseOrderOut])
def list_orders(
    _: Manager,
    db: TenantDB,
    params: Annotated[PageParams, Depends(page_params)],
    status: PoStatus | None = None,
    part_id: uuid.UUID | None = None,
    supplier_id: uuid.UUID | None = None,
) -> Page[PurchaseOrderOut]:
    """PO-01. 최근 승인부터."""
    stmt = _select()
    if status:
        stmt = stmt.where(PurchaseOrder.status == status)
    if part_id:
        stmt = stmt.where(PurchaseOrder.part_id == part_id)
    if supplier_id:
        stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)
    return keyset_page(
        db,
        stmt,
        [PurchaseOrder.approved_at, PurchaseOrder.id],
        params,
        to_item=order_out,
        cursor_of=lambda r: [r.PurchaseOrder.approved_at, r.PurchaseOrder.id],
        descending=True,
    )


def locked_order(db: Session, order_id: uuid.UUID) -> PurchaseOrder:
    order = db.scalar(select(PurchaseOrder).where(PurchaseOrder.id == order_id).with_for_update())
    if order is None:
        raise ApiError(ErrorCode.NOT_FOUND, "발주를 찾을 수 없습니다.")
    return order


def state_conflict(e: OrderStateConflict) -> ApiError:
    return ApiError(
        ErrorCode.ORDER_STATE_CONFLICT,
        "지금 상태에서는 할 수 없습니다.",
        {"status": e.status, "action": e.action},
    )


class CancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class CancelResponse(BaseModel):
    id: uuid.UUID
    status: PoStatus


@router.post("/{order_id}/cancel", response_model=CancelResponse)
def cancel_order(
    order_id: uuid.UUID, body: CancelRequest, _: Manager, db: TenantDB
) -> CancelResponse:
    """PO-04. 주문하지 않기로 함. 승인됨에서만, 그 밖은 409. 취소한 발주는 열린 발주에서 빠진다."""
    order = locked_order(db, order_id)
    try:
        order.status = cancel(order.status)  # type: ignore[arg-type]
    except OrderStateConflict as e:
        raise state_conflict(e) from None
    order.cancelled_at = clock.utcnow()
    order.cancel_reason = (body.reason or "").strip() or None
    return CancelResponse(id=order.id, status="cancelled")


class PurchaseOrderDetail(PurchaseOrderOut):
    # 공급사에 보낼 문자 문구 (F-APPROVAL-03). 희망 납기는 검토 스냅샷의 필요 시점
    order_message: str


def _need_by(db: Session, review_id: uuid.UUID | None) -> date | None:
    if review_id is None:
        return None
    values = db.scalar(
        select(ReviewSnapshot.values)
        .where(ReviewSnapshot.review_id == review_id)
        .order_by(ReviewSnapshot.created_at.desc(), ReviewSnapshot.id)
        .limit(1)
    )
    t_out = (values or {}).get("t_out")
    return date.fromisoformat(t_out) if t_out else None


@router.get("/{order_id}", response_model=PurchaseOrderDetail)
def get_order(order_id: uuid.UUID, _: Manager, db: TenantDB) -> PurchaseOrderDetail:
    """PO-02. 발주 상세와 공급사 문자 문구."""
    row = db.execute(_select().where(PurchaseOrder.id == order_id)).first()
    if row is None:
        raise ApiError(ErrorCode.NOT_FOUND, "발주를 찾을 수 없습니다.")
    po: PurchaseOrder = row.PurchaseOrder
    unit = db.scalar(select(Part.unit).where(Part.id == po.part_id))
    message = order_message(row.part_name, po.qty, unit, _need_by(db, po.review_id))
    return PurchaseOrderDetail(**order_out(row).model_dump(), order_message=message)


class MarkOrderedRequest(BaseModel):
    ordered_at: datetime | None = None


class MarkOrderedResponse(BaseModel):
    id: uuid.UUID
    status: PoStatus
    ordered_at: datetime


@router.post("/{order_id}/mark-ordered", response_model=MarkOrderedResponse)
def mark_order_placed(
    order_id: uuid.UUID, body: MarkOrderedRequest, user: Manager, db: TenantDB
) -> MarkOrderedResponse:
    """PO-03. 전화·문자로 주문했다고 표시한다. 이 시각부터 실제 납기를 잰다 (F-LEDGER-04).

    `ordered_at`을 비우면 지금. 승인 시각보다 이르거나 미래면 400. 승인됨에서만, 그 밖은 409.
    """
    order = locked_order(db, order_id)
    try:
        status = mark_ordered(order.status)  # type: ignore[arg-type]
    except OrderStateConflict as e:
        raise state_conflict(e) from None
    now = clock.utcnow()
    ordered_at = body.ordered_at or now
    if ordered_at.tzinfo is None or ordered_at > now or ordered_at < order.approved_at:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "주문 시각은 승인 이후 지금까지의 시간대 포함 시각이어야 합니다.",
            {"field": "ordered_at"},
        )
    order.status, order.ordered_at, order.ordered_by = status, ordered_at, user.user_id
    return MarkOrderedResponse(id=order.id, status=status, ordered_at=ordered_at)
