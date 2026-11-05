"""검토 근거 스냅샷 수집 (F-REVIEW-02, docs/ai-integration.md 5-2).

항목별 수집 함수가 스냅샷 필드 일부를 dict로 돌려주고, 이를 합쳐 `bjk_review.ReviewSnapshot`을
만든다. 아직 비어 있는 근거(병합 부품 재고)는 수집 함수를 `COLLECTORS`에
더해 붙인다. 비어 있는 값은 오류가 아니라 해당 체크를 건너뛰는 쪽으로 동작한다.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from bjk_review import (
    HiddenStock,
    OpenOrder,
    OpenRequest,
    OrderRequest,
    PriceStats,
    ReviewSnapshot,
    SupplierOffer,
)
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from bjk_server.clock import KST
from bjk_server.db.models import (
    AuditFlag,
    CalendarEvent,
    Category,
    CountRequest,
    EquipmentPart,
    Maintenance,
    Movement,
    Part,
    PartMetrics,
    PartSupplierMetrics,
    Review,
    Supplier,
    SupplierPart,
)
from bjk_server.domain import hidden_stock as hs
from bjk_server.inventory import stock_of
from bjk_server.jobs.nightly import FALLBACK_LEAD_DAYS, HOLIDAY_FACTORS, IMPORT_DEPENDENT
from bjk_server.purchasing.orders import open_orders, recent_price_stats, remaining_qty

# 다른 열린 요청 P (F-LEDGER-03: 검토중·검토완료·보류)
OPEN_REVIEW_STATUSES = ("reviewing", "reviewed", "held")
F_12M_DAYS = 365


@dataclass(frozen=True)
class SnapshotSource:
    """수집 함수가 함께 읽는 값. 부품·최신 지표·설정은 한 번만 읽는다."""

    db: Session
    part: Part
    category: Category | None
    metrics: PartMetrics | None
    order: OrderRequest
    review_id: uuid.UUID | None
    now: datetime
    settings: dict[str, dict[str, Any]]

    @property
    def today(self) -> date:
        return self.now.astimezone(KST).date()

    @property
    def lead_days(self) -> int:
        """기본 공급사 LT90. 새벽 계산 전이면 기본 공급사 기본 납기."""
        if self.metrics is not None:
            return self.metrics.lt90
        supplier = self.db.get(Supplier, self.part.default_supplier_id)
        return (supplier.default_lead_time_days if supplier else None) or FALLBACK_LEAD_DAYS


Collector = Callable[[SnapshotSource], dict[str, Any]]


def _part(src: SnapshotSource) -> dict[str, Any]:
    part = src.part
    return {
        "part_id": str(part.id),
        "part_name": part.name,
        "default_supplier_id": str(part.default_supplier_id) if part.default_supplier_id else None,
        "has_usage_estimate": part.monthly_estimate is not None,
    }


def _stock(src: SnapshotSource) -> dict[str, Any]:
    """S는 검토 시점의 원장 합계. 병합 부품 합산은 아직 하지 않는다."""
    has_out = src.db.scalar(
        select(exists().where(Movement.part_id == src.part.id, Movement.type == "OUT"))
    )
    return {"stock": stock_of(src.db, src.part.id), "has_usage_history": bool(has_out)}


def _metrics(src: SnapshotSource) -> dict[str, Any]:
    """새벽 계산값(F-ANAL). 계산 전이면 수요 근거가 없는 것으로 둔다."""
    m = src.metrics
    if m is None:
        return {"computed_at": src.now, "d95": 0, "d99": 0}
    return {
        "computed_at": m.computed_at,
        "m": m.m,
        "f_period": sum(int(f["qty"]) for f in m.f_items),
        "d95": m.d95,
        "d99": m.d99,
        "t_out": m.t_out,
        "t_deadline": m.t_deadline,
        "r_lead": m.r_lead,
        "r_price": m.r_price,
        "loss": m.loss,
        "loss_equipment": list(m.loss_equipment),
        "loss_is_estimate": m.loss_is_estimate,
        "data_mode": m.data_mode,
    }


def _maintenance(src: SnapshotSource) -> dict[str, Any]:
    """향후 12개월 정비 확정 필요량. 일정에 필요 부품이 없으면 설비 정비 1회당 수량 (F-SETUP-04)."""
    part_id, db = src.part.id, src.db
    per_maintenance = dict(
        db.execute(
            select(EquipmentPart.equipment_id, EquipmentPart.qty_per_maintenance).where(
                EquipmentPart.part_id == part_id
            )
        ).all()
    )
    total = 0
    for m in db.scalars(
        select(Maintenance).where(
            Maintenance.completed_at.is_(None),
            Maintenance.scheduled_date.between(src.today, src.today + timedelta(days=F_12M_DAYS)),
        )
    ):
        if m.required_parts is not None:
            total += sum(int(r["qty"]) for r in m.required_parts if r["part_id"] == str(part_id))
        else:
            total += per_maintenance.get(m.equipment_id, 0)
    return {"f_12m": total, "has_maintenance_plan": total > 0}


def _suppliers(src: SnapshotSource) -> dict[str, Any]:
    """공급사별 조건과 LT90. 공급사별 새벽 계산 전이면 공급사 기본 납기."""
    db, part_id = src.db, src.part.id
    lt90 = dict(
        db.execute(
            select(PartSupplierMetrics.supplier_id, PartSupplierMetrics.lt90)
            .where(PartSupplierMetrics.part_id == part_id)
            .order_by(PartSupplierMetrics.computed_on)
        ).all()
    )
    offers = [
        SupplierOffer(
            supplier_id=str(supplier.id),
            name=supplier.name,
            unit_price=sp.unit_price,
            moq=sp.moq,
            price_tiers=sp.price_tiers,
            shipping_fee=sp.shipping_fee,
            lt90=lt90.get(supplier.id, supplier.default_lead_time_days or FALLBACK_LEAD_DAYS),
        )
        for sp, supplier in db.execute(
            select(SupplierPart, Supplier)
            .join(Supplier, Supplier.id == SupplierPart.supplier_id)
            .where(SupplierPart.part_id == part_id)
            .order_by(Supplier.name, Supplier.id)
        ).all()
    ]
    return {"suppliers": offers}


def _hidden(src: SnapshotSource) -> dict[str, Any]:
    """같은 규격으로 등록된 다른 부품의 재고와 확인 여부 (F-MATCH-03)."""
    part, db = src.part, src.db
    twins = [
        o
        for o in db.scalars(
            select(Part).where(
                Part.id != part.id, Part.merged_into.is_(None), Part.category_id == part.category_id
            )
        )
        if hs.same_spec(part.category_id, part.spec, o.category_id, o.spec)
    ]
    if not twins:
        return {"hidden": []}
    ids = [o.id for o in twins]
    stock = dict(
        db.execute(
            select(Movement.part_id, func.sum(Movement.qty))
            .where(Movement.part_id.in_(ids))
            .group_by(Movement.part_id)
        ).all()
    )
    last_counted = dict(
        db.execute(
            select(CountRequest.part_id, func.max(CountRequest.answered_at))
            .where(CountRequest.part_id.in_(ids), CountRequest.answered_at <= src.now)
            .group_by(CountRequest.part_id)
        ).all()
    )
    suspect = set(
        db.scalars(
            select(AuditFlag.part_id).where(
                AuditFlag.part_id.in_(ids), AuditFlag.status != "closed"
            )
        )
    )
    split = hs.split_hidden(
        (
            hs.HiddenPart(o.id, int(stock.get(o.id, 0)), last_counted.get(o.id), o.id in suspect)
            for o in twins
        ),
        src.now,
        src.settings["system"]["hidden_stock_count_days"],
    )
    names = {o.id: o.name for o in twins}
    hidden = [
        HiddenStock(part_id=str(p.part_id), name=names[p.part_id], qty=p.qty, confirmed=confirmed)
        for group, confirmed in ((split.confirmed, True), (split.unconfirmed, False))
        for p in group
    ]
    return {"hidden": sorted(hidden, key=lambda h: (h.name, h.part_id))}


def _open_requests(src: SnapshotSource) -> dict[str, Any]:
    """같은 부품의 다른 열린 요청 P. 수정안이 있으면 수정안 수량 (F-REVIEW-02)."""
    query = select(Review).where(
        Review.part_id == src.part.id, Review.status.in_(OPEN_REVIEW_STATUSES)
    )
    if src.review_id is not None:
        query = query.where(Review.id != src.review_id)
    requests = []
    for review in src.db.scalars(query.order_by(Review.created_at, Review.id)):
        proposal = (review.result or {}).get("proposal")
        qty = proposal["qty"] if proposal else review.request["qty"]
        requests.append(OpenRequest(review_id=str(review.id), qty=qty))
    return {"open_requests": requests}


def _orders(src: SnapshotSource) -> dict[str, Any]:
    """열린 발주(C-03), 그중 필요 시점 전 도착분 O, 최근 구매 단가 p̄·σ_p·n (#161).

    같은 부품과 이 부품으로 병합된 부품을 함께 본다. 도착 예정일은 주문 완료 시각(없으면 승인
    시각) + 그 공급사 LT50, 공급사별 새벽 계산 전이면 공급사 기본 납기다.
    필요 시점(t_out)이 없으면 열린 발주 잔량을 모두 O로 본다.
    """
    db, part = src.db, src.part
    ids = [part.id, *db.scalars(select(Part.id).where(Part.merged_into == part.id))]
    lt50 = dict(
        db.execute(
            select(PartSupplierMetrics.supplier_id, PartSupplierMetrics.lt50)
            .where(PartSupplierMetrics.part_id == part.id)
            .order_by(PartSupplierMetrics.computed_on)
        ).all()
    )
    t_need = src.metrics.t_out if src.metrics else None
    orders, incoming = [], 0
    for po in open_orders(db, ids):
        if po.supplier_id in lt50:
            days = lt50[po.supplier_id]
        else:
            supplier = db.get(Supplier, po.supplier_id)
            days = (supplier.default_lead_time_days if supplier else None) or FALLBACK_LEAD_DAYS
        eta = ((po.ordered_at or po.approved_at) + timedelta(days=days)).astimezone(KST).date()
        qty = remaining_qty(po)
        orders.append(OpenOrder(qty=qty, eta=eta))
        if t_need is None or eta <= t_need:
            incoming += qty
    stats = recent_price_stats(db, ids, src.now)
    price = PriceStats(mean=stats.mean, sigma=stats.std or 0.0, n=stats.n)
    return {"open_orders": orders, "incoming": incoming, "price_stats": price}


def _external(src: SnapshotSource) -> dict[str, Any]:
    """수입 의존 여부와 기본 공급사 납기 구간(오늘 ~ 오늘 + LT90)에 겹치는 연휴 이름 (F-EXT)."""
    category = src.category
    dependency = src.part.import_override or (category.import_dependency if category else "low")
    factors = category.lead_factors if category else []
    regions = {HOLIDAY_FACTORS[f] for f in factors if f in HOLIDAY_FACTORS}
    end = src.today + timedelta(days=src.lead_days)
    names = set()
    for event in src.db.scalars(
        select(CalendarEvent).where(
            CalendarEvent.start_date <= end, CalendarEvent.end_date >= src.today
        )
    ):
        if event.scope in regions or (
            event.scope == "supplier" and event.supplier_id == src.part.default_supplier_id
        ):
            names.add(event.name)
    return {"import_dependent": dependency in IMPORT_DEPENDENT, "holidays_in_lead": sorted(names)}


COLLECTORS: tuple[Collector, ...] = (
    _part,
    _stock,
    _metrics,
    _maintenance,
    _suppliers,
    _hidden,
    _open_requests,
    _orders,
    _external,
)


def latest_metrics(db: Session, part_id: uuid.UUID) -> PartMetrics | None:
    return db.scalar(
        select(PartMetrics)
        .where(PartMetrics.part_id == part_id)
        .order_by(PartMetrics.computed_on.desc())
        .limit(1)
    )


def collect_snapshot(
    db: Session,
    part_id: str | None,
    order: OrderRequest,
    *,
    now: datetime,
    settings: dict[str, dict[str, Any]],
    review_id: uuid.UUID | None = None,
) -> ReviewSnapshot:
    """현재 회사(RLS) 세션에서 근거를 모아 고정한다. 부품을 찾지 못하면 보류용 빈 스냅샷."""
    as_of = now.astimezone(KST).date()
    part = db.get(Part, uuid.UUID(part_id)) if part_id else None
    if part is not None and part.merged_into is not None:
        part = db.get(Part, part.merged_into)
    if part is None:
        return ReviewSnapshot(as_of=as_of, computed_at=now, part_id=None, stock=0, d95=0, d99=0)
    src = SnapshotSource(
        db=db,
        part=part,
        category=db.get(Category, part.category_id) if part.category_id else None,
        metrics=latest_metrics(db, part.id),
        order=order,
        review_id=review_id,
        now=now,
        settings=settings,
    )
    values: dict[str, Any] = {"as_of": as_of}
    for collect in COLLECTORS:
        values.update(collect(src))
    return ReviewSnapshot(**values)
