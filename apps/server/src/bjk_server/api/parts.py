"""부품 API (API 명세서 3-2 SET)."""

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import exists, false, func, or_, select

from bjk_server.auth import CurrentUser, TenantDB
from bjk_server.db.models import (
    Category,
    Part,
    PartAlias,
    PartMetrics,
    PartSupplierMetrics,
    Supplier,
    SupplierPart,
)
from bjk_server.errors import ApiError, ErrorCode
from bjk_server.inventory import latest_metrics_subquery, stock_of, stock_subquery
from bjk_server.pagination import Page, PageParams, keyset_page, page_params

router = APIRouter(prefix="/parts", tags=["parts"])


class PartListItem(BaseModel):
    id: uuid.UUID
    name: str
    category: str | None
    unit: str
    stock: int
    # 아래 지표는 최신 새벽 계산(part_metrics) 값이다. 계산 전에는 null.
    abc: Literal["A", "B", "C"] | None = None
    demand_class: str | None = None
    ledger_status: Literal["normal", "suspect"] = "normal"
    t_out: date | None = None
    p_out: float | None = None
    risk_level: Literal["normal", "caution", "high"] | None = None
    computed_at: datetime | None = None


def _like(q: str) -> str:
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@router.get("", response_model=Page[PartListItem])
def list_parts(
    _: CurrentUser,
    db: TenantDB,
    params: Annotated[PageParams, Depends(page_params)],
    q: Annotated[str | None, Query(max_length=100)] = None,
    category_id: uuid.UUID | None = None,
    abc: Literal["A", "B", "C"] | None = None,
    demand_class: Literal["smooth", "erratic", "intermittent", "lumpy", "insufficient"]
    | None = None,
    risk: Literal["caution", "high"] | None = None,
    ledger_status: Literal["normal", "suspect"] | None = None,
) -> Page[PartListItem]:
    """SET-03. 이름·별칭·규격 검색과 필터. 이름순.

    정렬은 DB 로케일과 관계없이 같도록 C(코드포인트) 정렬로 고정한다. 한글은 가나다순이다.
    """
    stock = stock_subquery()
    metrics = latest_metrics_subquery()
    stmt = (
        select(
            Part.id,
            Part.name,
            Part.unit,
            Category.name.label("category"),
            func.coalesce(stock.c.stock, 0).label("stock"),
            metrics.c.abc,
            metrics.c.demand_class,
            metrics.c.t_out,
            metrics.c.p_out,
            metrics.c.external_level,
            metrics.c.computed_at,
        )
        .outerjoin(Category, Category.id == Part.category_id)
        .outerjoin(stock, stock.c.part_id == Part.id)
        .outerjoin(metrics, metrics.c.part_id == Part.id)
        .where(Part.merged_into.is_(None))
    )
    if q and q.strip():
        pattern = _like(q.strip())
        alias_match = exists().where(PartAlias.part_id == Part.id, PartAlias.text.ilike(pattern))
        # 규격은 키가 아니라 값만 검색한다 (예: bearing_no "6205").
        spec_values = func.jsonb_each_text(Part.spec).table_valued("key", "value")
        spec_match = exists(
            select(1).select_from(spec_values).where(spec_values.c.value.ilike(pattern))
        )
        stmt = stmt.where(or_(Part.name.ilike(pattern), alias_match, spec_match))
    if category_id:
        stmt = stmt.where(Part.category_id == category_id)
    if abc:
        stmt = stmt.where(metrics.c.abc == abc)
    if demand_class:
        stmt = stmt.where(metrics.c.demand_class == demand_class)
    if risk:
        stmt = stmt.where(metrics.c.external_level == risk)
    # 장부 검증 결과가 아직 없어 모든 부품이 normal이다.
    if ledger_status == "suspect":
        stmt = stmt.where(false())

    return keyset_page(
        db,
        stmt,
        [Part.name.collate("C"), Part.id],
        params,
        to_item=lambda r: PartListItem(
            id=r.id,
            name=r.name,
            category=r.category,
            unit=r.unit,
            stock=r.stock,
            abc=r.abc,
            demand_class=r.demand_class,
            t_out=r.t_out,
            p_out=r.p_out,
            risk_level=r.external_level,
            computed_at=r.computed_at,
        ),
        cursor_of=lambda r: [r.name, r.id],
    )


class CategoryDetail(BaseModel):
    id: uuid.UUID
    name: str
    import_dependency: Literal["high", "medium", "low"]


class HiddenStock(BaseModel):
    H_c: int
    H_u: int
    parts: list[dict[str, Any]]


class StockDetail(BaseModel):
    S: int
    # 발주 테이블 추가 전이라 입고 예정은 비어 있다.
    incoming: list[dict[str, Any]]
    hidden: HiddenStock
    ledger_status: Literal["normal", "suspect"]
    # 실사 기능(AUD-03) 추가 전이라 null이다.
    last_counted_at: date | None


class DefaultSupplier(BaseModel):
    id: uuid.UUID
    name: str
    LT50: int
    LT90: int


class Loss(BaseModel):
    L: int
    equipment: list[str]
    is_estimate: bool


class PartMetricsDetail(BaseModel):
    abc: Literal["A", "B", "C"]
    demand_class: str
    data_mode: Literal["statistical", "estimated"]
    forecast_weekly: float
    m: float
    F: list[dict[str, Any]]
    default_supplier: DefaultSupplier | None
    D95: int
    D99: int
    reorder_point: int
    t_out: date | None
    t_deadline: date | None
    p_out: float
    loss: Loss
    priority: float
    R: int
    r_lead: float
    r_price: float
    external_level: Literal["normal", "caution", "high"]
    computed_at: datetime


class SupplierMetricsItem(BaseModel):
    supplier_id: uuid.UUID
    name: str
    # 새벽 계산 전에는 납기·표본 수가 null이다.
    LT50: int | None
    LT90: int | None
    samples: int | None
    unit_price: int
    moq: int


class AliasItem(BaseModel):
    text: str
    confirmed_count: int
    ambiguous: bool


class PartDetail(BaseModel):
    id: uuid.UUID
    name: str
    spec: dict[str, Any]
    unit: str
    category: CategoryDetail | None
    stock: StockDetail
    metrics: PartMetricsDetail | None
    supplier_metrics: list[SupplierMetricsItem]
    aliases: list[AliasItem]


def _metrics_detail(db: TenantDB, m: PartMetrics) -> PartMetricsDetail:
    supplier = db.get(Supplier, m.default_supplier_id) if m.default_supplier_id else None
    return PartMetricsDetail(
        abc=m.abc,
        demand_class=m.demand_class,
        data_mode=m.data_mode,
        forecast_weekly=m.forecast_weekly,
        m=m.m,
        F=m.f_items,
        default_supplier=DefaultSupplier(
            id=supplier.id, name=supplier.name, LT50=m.lt50, LT90=m.lt90
        )
        if supplier
        else None,
        D95=m.d95,
        D99=m.d99,
        reorder_point=m.reorder_point,
        t_out=m.t_out,
        t_deadline=m.t_deadline,
        p_out=m.p_out,
        loss=Loss(L=m.loss, equipment=m.loss_equipment, is_estimate=m.loss_is_estimate),
        priority=m.priority,
        R=m.recommended_qty,
        r_lead=m.r_lead,
        r_price=m.r_price,
        external_level=m.external_level,
        computed_at=m.computed_at,
    )


def _supplier_metrics(db: TenantDB, part_id: uuid.UUID) -> list[SupplierMetricsItem]:
    """공급사별 단가·MOQ와 최신 새벽 계산의 납기. 계산 전 공급사는 납기가 null이다."""
    latest = (
        select(PartSupplierMetrics)
        .where(
            PartSupplierMetrics.part_id == part_id,
            PartSupplierMetrics.computed_on
            == select(func.max(PartSupplierMetrics.computed_on))
            .where(PartSupplierMetrics.part_id == part_id)
            .scalar_subquery(),
        )
        .subquery("latest")
    )
    rows = db.execute(
        select(
            SupplierPart.supplier_id,
            Supplier.name,
            SupplierPart.unit_price,
            SupplierPart.moq,
            latest.c.lt50,
            latest.c.lt90,
            latest.c.samples,
        )
        .join(Supplier, Supplier.id == SupplierPart.supplier_id)
        .outerjoin(latest, latest.c.supplier_id == SupplierPart.supplier_id)
        .where(SupplierPart.part_id == part_id)
        .order_by(Supplier.name.collate("C"), Supplier.id)
    )
    return [
        SupplierMetricsItem(
            supplier_id=r.supplier_id,
            name=r.name,
            LT50=r.lt50,
            LT90=r.lt90,
            samples=r.samples,
            unit_price=r.unit_price,
            moq=r.moq,
        )
        for r in rows
    ]


@router.get("/{part_id}", response_model=PartDetail)
def get_part(part_id: uuid.UUID, _: CurrentUser, db: TenantDB) -> PartDetail:
    """SET-04. 부품 정보, 원장 합산 재고, 숨은 재고, 최신 지표, 공급사별 납기, 별칭."""
    part = db.get(Part, part_id)
    # 다른 회사 부품은 RLS로 보이지 않는다. 병합된 부품은 목록과 같이 숨긴다.
    if part is None or part.merged_into is not None:
        raise ApiError(ErrorCode.NOT_FOUND, "부품을 찾을 수 없습니다.")
    category = db.get(Category, part.category_id) if part.category_id else None
    metrics = db.scalar(
        select(PartMetrics)
        .where(PartMetrics.part_id == part.id)
        .order_by(PartMetrics.computed_on.desc())
        .limit(1)
    )
    aliases = db.scalars(
        select(PartAlias)
        .where(PartAlias.part_id == part.id)
        .order_by(PartAlias.confirmed_count.desc(), PartAlias.text.collate("C"))
    )
    return PartDetail(
        id=part.id,
        name=part.name,
        spec=part.spec,
        unit=part.unit,
        category=CategoryDetail(
            id=category.id, name=category.name, import_dependency=category.import_dependency
        )
        if category
        else None,
        stock=StockDetail(
            S=stock_of(db, part.id),
            incoming=[],
            hidden=HiddenStock(
                H_c=metrics.hidden_confirmed if metrics else 0,
                H_u=metrics.hidden_unconfirmed if metrics else 0,
                parts=[],
            ),
            ledger_status="normal",
            last_counted_at=None,
        ),
        metrics=_metrics_detail(db, metrics) if metrics else None,
        supplier_metrics=_supplier_metrics(db, part.id),
        aliases=[
            AliasItem(text=a.text, confirmed_count=a.confirmed_count, ambiguous=a.ambiguous)
            for a in aliases
        ],
    )
