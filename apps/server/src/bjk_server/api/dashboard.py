"""대시보드 요약 (API 명세서 DSH-02, 화면 W-01). 계산은 새벽 배치 값과 원장 합산만 쓴다."""

import uuid
from datetime import date, datetime, time, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select

from bjk_server import clock
from bjk_server.api.external import external_status
from bjk_server.auth import TenantDB, require_role
from bjk_server.clock import KST
from bjk_server.db.models import AuditFlag, Movement, Part, PurchaseOrder, Review, SupplierPart
from bjk_server.domain.external import Level
from bjk_server.inventory import latest_metrics_subquery, stock_subquery
from bjk_server.security import TokenClaims

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

Manager = Annotated[TokenClaims, Depends(require_role("manager"))]

RISK_TOP = 5
# 묶인 재고: 이 기간 출고가 없는 부품의 재고 금액 (명세에 정의 없음, 2026-11-05 사용자 결정 #180)
IDLE_DAYS = 180
# 결정을 기다리는 검토 (2026-11-05 사용자 결정 #180)
PENDING_STATUSES = ("reviewed", "held")
_LEVEL_ORDER: dict[Level, int] = {"normal": 0, "caution": 1, "high": 2}


class RiskItem(BaseModel):
    part_id: uuid.UUID
    name: str
    p_out: float
    L: int
    priority: float
    t_out: date | None


class PendingReviews(BaseModel):
    count: int
    urgent: int


class AuditSummary(BaseModel):
    open: int
    high: int


class ExternalSummary(BaseModel):
    level: Level
    updated_at: datetime | None


class TodaySummary(BaseModel):
    movements: int
    reviews_created: int
    decisions: int


class DashboardSummary(BaseModel):
    risk_top5: list[RiskItem]
    pending_reviews: PendingReviews
    audit_flags: AuditSummary
    awaiting_order: int
    tied_up_stock_amount: int
    external: ExternalSummary
    today: TodaySummary
    computed_at: datetime | None


def _risk_top(db) -> tuple[list[RiskItem], datetime | None]:
    m = latest_metrics_subquery()
    rows = db.execute(
        select(m, Part.name)
        .join(Part, Part.id == m.c.part_id)
        .where(Part.merged_into.is_(None))
        .order_by(m.c.priority.desc(), m.c.part_id)
        .limit(RISK_TOP)
    ).all()
    computed_at = db.scalar(select(func.max(m.c.computed_at)))
    items = [
        RiskItem(
            part_id=r.part_id,
            name=r.name,
            p_out=r.p_out,
            L=r.loss,
            priority=r.priority,
            t_out=r.t_out,
        )
        for r in rows
    ]
    return items, computed_at.astimezone(KST) if computed_at else None


def _tied_up_amount(db, now: datetime) -> int:
    """최근 IDLE_DAYS일 출고가 없고 재고가 있는 부품의 재고 × 단가 합.

    단가는 기본 공급사 단가, 없으면 등록된 공급사 중 가장 싼 단가. 단가가 없으면 0원으로 본다.
    """
    stock = stock_subquery()
    # 병합된 부품에 남은 출고도 대표 부품의 사용으로 본다(F-LEDGER-02, stock_subquery와 같은 기준)
    used = (
        select(func.coalesce(Part.merged_into, Movement.part_id))
        .select_from(Movement)
        .join(Part, Part.id == Movement.part_id)
        .where(Movement.type == "OUT", Movement.occurred_at >= now - timedelta(days=IDLE_DAYS))
        .distinct()
    )
    default_price = (
        select(SupplierPart.unit_price)
        .where(
            SupplierPart.part_id == Part.id, SupplierPart.supplier_id == Part.default_supplier_id
        )
        .limit(1)
        .scalar_subquery()
    )
    cheapest = (
        select(func.min(SupplierPart.unit_price))
        .where(SupplierPart.part_id == Part.id)
        .scalar_subquery()
    )
    price = func.coalesce(default_price, cheapest, 0)
    total = db.scalar(
        select(func.coalesce(func.sum(stock.c.stock * price), 0))
        .select_from(Part)
        .join(stock, stock.c.part_id == Part.id)
        .where(Part.merged_into.is_(None), stock.c.stock > 0, Part.id.not_in(used))
    )
    return int(total)


def _external(user: TokenClaims, db) -> ExternalSummary:
    status = external_status(user, db)
    level = max((i.level for i in status.indicators), key=_LEVEL_ORDER.get, default="normal")
    updated_at = status.updated_at.astimezone(KST) if status.updated_at else None
    return ExternalSummary(level=level, updated_at=updated_at)


@router.get("/summary", response_model=DashboardSummary)
def dashboard_summary(user: Manager, db: TenantDB) -> DashboardSummary:
    """DSH-02. `awaiting_order`는 승인 후 주문 완료 표시를 기다리는 발주(`approved`) 수."""
    now = clock.utcnow()
    start = datetime.combine(now.astimezone(KST).date(), time.min, tzinfo=KST)
    risk_top5, computed_at = _risk_top(db)

    pending = db.execute(
        select(
            func.count(),
            func.count().filter(Review.flags.any_() == "urgent"),
        ).where(Review.status.in_(PENDING_STATUSES))
    ).one()
    flags = db.execute(
        select(func.count(), func.count().filter(AuditFlag.level == "high")).where(
            AuditFlag.status != "closed"
        )
    ).one()
    today = TodaySummary(
        movements=db.scalar(select(func.count()).where(Movement.occurred_at >= start)) or 0,
        reviews_created=db.scalar(select(func.count()).where(Review.created_at >= start)) or 0,
        decisions=db.scalar(select(func.count()).where(Review.decided_at >= start)) or 0,
    )
    return DashboardSummary(
        risk_top5=risk_top5,
        pending_reviews=PendingReviews(count=pending[0], urgent=pending[1]),
        audit_flags=AuditSummary(open=flags[0], high=flags[1]),
        awaiting_order=db.scalar(select(func.count()).where(PurchaseOrder.status == "approved"))
        or 0,
        tied_up_stock_amount=_tied_up_amount(db, now),
        external=_external(user, db),
        today=today,
        computed_at=computed_at,
    )
