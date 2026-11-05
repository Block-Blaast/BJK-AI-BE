"""시스템 초안 검토 (재고 부족 F-LEDGER-03, 놓친 발주 F-MISSED-01).

두 초안은 같은 중복 방지 규칙을 쓴다: 같은 부품의 열린 발주·열린 요청이 있거나, 오늘(Asia/Seoul)
'발주 불필요'로 닫힌 검토가 있으면 만들지 않는다. 초안 원안은 수량 R, 기본 공급사, 단가 비움.
"""

import uuid
from collections.abc import Callable, Collection
from datetime import date, datetime

from bjk_review import OrderRequest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from bjk_server.ai.client import get_ai_client
from bjk_server.clock import KST
from bjk_server.db.models import Part, PurchaseOrder, Review
from bjk_server.domain.purchase_order import OPEN_STATUSES
from bjk_server.reviews import service
from bjk_server.reviews.service import ReviewRunner, create_review
from bjk_server.reviews.snapshot import OPEN_REVIEW_STATUSES, latest_metrics

# 초안을 막는 부품을 고른다. part_ids가 있으면 그 부품만 본다.
Blocker = Callable[[Session, date, Collection[uuid.UUID] | None], set[uuid.UUID]]


def _only(query, column, part_ids):
    return query.where(column.in_(list(part_ids))) if part_ids is not None else query


def _open_reviews(db: Session, today: date, part_ids=None) -> set[uuid.UUID]:
    """열린 요청·초안(검토중·검토완료·보류)."""
    query = select(Review.part_id).where(
        Review.part_id.is_not(None), Review.status.in_(OPEN_REVIEW_STATUSES)
    )
    return set(db.scalars(_only(query, Review.part_id, part_ids)))


def _open_orders(db: Session, today: date, part_ids=None) -> set[uuid.UUID]:
    """열린 발주(승인됨·발주됨·부분입고, F-APPROVAL-02)."""
    query = select(PurchaseOrder.part_id).where(PurchaseOrder.status.in_(OPEN_STATUSES))
    return set(db.scalars(_only(query, PurchaseOrder.part_id, part_ids)))


def _closed_no_order_today(db: Session, today: date, part_ids=None) -> set[uuid.UUID]:
    """오늘 '발주 불필요'로 닫힌 검토. 다음 새벽 계산 전까지 다시 만들지 않는다."""
    query = select(Review.part_id).where(
        Review.part_id.is_not(None),
        Review.status == "closed",
        Review.decision["action"].astext == "accept_no_order",
        func.date(func.timezone("Asia/Seoul", Review.decided_at)) == today,
    )
    return set(db.scalars(_only(query, Review.part_id, part_ids)))


BLOCKERS: tuple[Blocker, ...] = (_open_reviews, _open_orders, _closed_no_order_today)


def blocked_parts(
    db: Session, today: date, part_ids: Collection[uuid.UUID] | None = None
) -> set[uuid.UUID]:
    return set().union(*(block(db, today, part_ids) for block in BLOCKERS))


def draft_order(qty: int, supplier_id: uuid.UUID | None) -> OrderRequest:
    return OrderRequest(qty=qty, supplier_id=str(supplier_id) if supplier_id else None)


def request_runner(db: Session) -> ReviewRunner:
    """요청 처리 중 만든 초안을 커밋 뒤 백그라운드에서 돌리는 실행기. 테스트에서 바꾼다."""
    scope = sessionmaker(db.get_bind(), expire_on_commit=False).begin
    return ReviewRunner(scope, get_ai_client(), service._executor)


def stock_draft_after_record(
    db: Session, company_id: uuid.UUID, part: Part, stock: int, now: datetime
) -> uuid.UUID | None:
    """원장 기록 직후 재주문점 이탈이면 재고 부족 초안 검토를 만든다 (F-LEDGER-03).

    S + H_c ≤ 재주문점(최신 새벽 계산)이고 중복 방지에 걸리지 않으면 수량 R로 만든다.
    새벽 계산 전이거나 R이 0이면 만들지 않는다. 부품 재고 잠금 안에서 불려 부품당 하나만 생긴다.
    """
    metrics = latest_metrics(db, part.id)
    if metrics is None or metrics.recommended_qty <= 0:
        return None
    if stock + metrics.hidden_confirmed > metrics.reorder_point:
        return None
    if part.id in blocked_parts(db, now.astimezone(KST).date(), [part.id]):
        return None
    review = create_review(
        db,
        company_id,
        entry="stock_draft",
        order=draft_order(metrics.recommended_qty, metrics.default_supplier_id),
        part_id=part.id,
    )
    request_runner(db).start_after_commit(db, company_id, review.id)
    return review.id
