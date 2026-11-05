"""부품 API (API 명세서 3-2 SET)."""

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import exists, func, or_, select

from bjk_server import clock
from bjk_server.ai.client import AiClient, get_ai_client
from bjk_server.ai.embeddings import embed_rows
from bjk_server.api.schemas import Forecast
from bjk_server.auth import CurrentUser, TenantDB, require_role
from bjk_server.db.models import (
    AuditFlag,
    Category,
    Movement,
    Part,
    PartAlias,
    PartMetrics,
    PartSupplierMetrics,
    Supplier,
    SupplierPart,
    User,
)
from bjk_server.errors import ApiError, ErrorCode
from bjk_server.inventory import latest_metrics_subquery, stock_of, stock_subquery
from bjk_server.pagination import Page, PageParams, keyset_page, page_params
from bjk_server.purchasing.orders import open_qty
from bjk_server.security import TokenClaims

router = APIRouter(prefix="/parts", tags=["parts"])

Manager = Annotated[TokenClaims, Depends(require_role("manager"))]
Ai = Annotated[AiClient | None, Depends(get_ai_client)]
Dependency = Literal["high", "medium", "low"]
SpecValue = str | int | float
# 엑셀 이관·부품 등록 때 들어간 시작 재고의 원장 사유 (F-SETUP-01)
INITIAL_STOCK_REASON = "초기 재고"


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
    # 열린 의심 항목(F-AUDIT)이 있으면 장부 의심
    suspect = exists().where(AuditFlag.part_id == Part.id, AuditFlag.status != "closed")
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
            suspect.label("suspect"),
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
    if ledger_status:
        stmt = stmt.where(suspect if ledger_status == "suspect" else ~suspect)

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
            ledger_status="suspect" if r.suspect else "normal",
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


@router.get("/{part_id}/forecast", response_model=Forecast)
def part_forecast(part_id: uuid.UUID, _: CurrentUser, db: TenantDB) -> Forecast:
    """부품 상세(W-05) 재고 추이 예측선 (#258, 명세 밖).

    시작은 지금 재고 S + 열린 발주 O + 확인된 숨은 재고 H_c, 소모는 최신 새벽 계산의 m.
    발주 시 선은 권장 발주량 R이 기본 공급사 LT90 날에 들어온다. 새벽 계산 전이면 `days`가 빈다.
    """
    part = db.get(Part, part_id)
    if part is None or part.merged_into is not None:
        raise ApiError(ErrorCode.NOT_FOUND, "부품을 찾을 수 없습니다.")
    today = clock.utcnow().astimezone(clock.KST).date()
    stock = stock_of(db, part.id) + open_qty(db, [part.id]).get(part.id, 0)
    metrics = db.scalar(
        select(PartMetrics)
        .where(PartMetrics.part_id == part.id)
        .order_by(PartMetrics.computed_on.desc())
        .limit(1)
    )
    if metrics is None:
        return Forecast(
            as_of=today,
            computed_at=None,
            start_stock=stock,
            monthly_use=0,
            order_qty=0,
            lead_days=0,
            reorder_point=None,
            t_out=None,
            days=[],
        )
    return Forecast.build(
        as_of=today,
        start=stock + metrics.hidden_confirmed,
        monthly_use=metrics.m,
        order_qty=metrics.recommended_qty,
        lead_days=metrics.lt90,
        computed_at=metrics.computed_at.astimezone(clock.KST),
        reorder_point=metrics.reorder_point,
        t_out=metrics.t_out,
    )


class MovementItem(BaseModel):
    id: uuid.UUID
    type: Literal["IN", "OUT", "ADJUST"]
    qty: int
    occurred_at: datetime
    # 작성자 이름. 시스템 기록(초기 이관 등)은 null.
    author: str | None
    source_text: str | None
    equipment_id: uuid.UUID | None
    maintenance_id: uuid.UUID | None
    po_id: uuid.UUID | None
    reason: str | None
    # 정정 기록이면 정정 대상 원장 행
    corrects: uuid.UUID | None


@router.get("/{part_id}/movements", response_model=Page[MovementItem])
def list_movements(
    part_id: uuid.UUID,
    _: CurrentUser,
    db: TenantDB,
    params: Annotated[PageParams, Depends(page_params)],
) -> Page[MovementItem]:
    """LED-01. 부품의 입출고 이력(원문 포함). 최근 발생 순.

    병합된 부품도 이력은 그대로 볼 수 있다. 원장은 고치지 않고 정정 기록을 더한다.
    """
    if db.get(Part, part_id) is None:
        raise ApiError(ErrorCode.NOT_FOUND, "부품을 찾을 수 없습니다.", {"part_id": str(part_id)})
    stmt = (
        select(Movement, User.name.label("author"))
        .outerjoin(User, User.id == Movement.author_id)
        .where(Movement.part_id == part_id)
    )
    return keyset_page(
        db,
        stmt,
        [Movement.occurred_at, Movement.id],
        params,
        to_item=lambda r: MovementItem(
            id=r.Movement.id,
            type=r.Movement.type,
            qty=r.Movement.qty,
            occurred_at=r.Movement.occurred_at,
            author=r.author,
            source_text=r.Movement.source_text,
            equipment_id=r.Movement.equipment_id,
            maintenance_id=r.Movement.maintenance_id,
            po_id=r.Movement.po_id,
            reason=r.Movement.reason,
            corrects=r.Movement.corrects_id,
        ),
        cursor_of=lambda r: [r.Movement.occurred_at, r.Movement.id],
        descending=True,
    )


class PartFields(BaseModel):
    category_id: uuid.UUID | None = None
    default_supplier_id: uuid.UUID | None = None
    spec: dict[str, SpecValue] = {}
    pack_qty: int | None = Field(default=None, ge=1)
    monthly_estimate: int | None = Field(default=None, ge=0)
    # 카테고리와 다른 수입 의존도 (예: 국산 베어링)
    import_override: Dependency | None = None
    location: str | None = Field(default=None, max_length=100)


class PartCreate(PartFields):
    name: str = Field(min_length=1, max_length=200)
    unit: str = Field(min_length=1, max_length=16)
    initial_stock: int = Field(default=0, ge=0)


class PartUpdate(PartFields):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    unit: str | None = Field(default=None, min_length=1, max_length=16)
    spec: dict[str, SpecValue] | None = None


class PartOut(BaseModel):
    id: uuid.UUID
    name: str
    unit: str
    category_id: uuid.UUID | None
    default_supplier_id: uuid.UUID | None
    spec: dict[str, SpecValue]
    pack_qty: int | None
    monthly_estimate: int | None
    import_override: Dependency | None
    location: str | None
    stock: int


def _part_out(db: TenantDB, part: Part) -> PartOut:
    return PartOut(
        id=part.id,
        name=part.name,
        unit=part.unit,
        category_id=part.category_id,
        default_supplier_id=part.default_supplier_id,
        spec=part.spec,
        pack_qty=part.pack_qty,
        monthly_estimate=part.monthly_estimate,
        import_override=part.import_override,
        location=part.location,
        stock=stock_of(db, part.id),
    )


def _check_refs(db: TenantDB, fields: dict) -> None:
    for key, model, label in (
        ("category_id", Category, "카테고리"),
        ("default_supplier_id", Supplier, "공급사"),
    ):
        value = fields.get(key)
        if value is not None and db.get(model, value) is None:
            raise ApiError(ErrorCode.NOT_FOUND, f"{label}를 찾을 수 없습니다.", {key: str(value)})


def _text(fields: dict, key: str) -> None:
    if key in fields:
        if fields[key] is None or not fields[key].strip():
            raise ApiError(ErrorCode.VALIDATION_ERROR, "값을 비울 수 없습니다.", {"field": key})
        fields[key] = fields[key].strip()


@router.post("", status_code=201, response_model=PartOut)
def create_part(body: PartCreate, user: Manager, db: TenantDB, ai: Ai) -> PartOut:
    """SET-05. 부품 등록. 시작 재고는 원장에 ADJUST(사유 `초기 재고`)로 넣는다.

    이름 임베딩을 함께 저장한다(F-SETUP-02 5단계). ai가 실패하면 비워 두고 nightly가 채운다.
    """
    fields = body.model_dump()
    _text(fields, "name")
    _text(fields, "unit")
    _check_refs(db, fields)
    initial_stock = fields.pop("initial_stock")
    now = clock.utcnow()
    part = Part(id=uuid.uuid4(), company_id=user.company_id, updated_at=now, **fields)
    db.add(part)
    db.flush()
    if initial_stock:
        db.add(
            Movement(
                id=uuid.uuid4(),
                company_id=user.company_id,
                part_id=part.id,
                type="ADJUST",
                qty=initial_stock,
                occurred_at=now,
                author_id=user.user_id,
                reason=INITIAL_STOCK_REASON,
            )
        )
        db.flush()
    if ai:
        embed_rows(db, ai, user.company_id, [part])
    return _part_out(db, part)


@router.patch("/{part_id}", response_model=PartOut)
def update_part(
    part_id: uuid.UUID, body: PartUpdate, user: Manager, db: TenantDB, ai: Ai
) -> PartOut:
    """SET-05. 보낸 항목만 고친다. 재고는 바꾸지 않는다(정정·실사 기록으로 맞춘다).

    병합된 부품은 대표 부품을 고친다. name·unit·spec에 null은 400, 나머지는 null로 지운다.
    이름이 바뀌면 이전 임베딩을 지우고 다시 만든다.
    """
    part = db.get(Part, part_id)
    if part is None:
        raise ApiError(ErrorCode.NOT_FOUND, "부품을 찾을 수 없습니다.")
    if part.merged_into is not None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            "병합된 부품입니다. 대표 부품을 수정해 주세요.",
            {"merged_into": str(part.merged_into)},
        )
    fields = body.model_dump(exclude_unset=True)
    _text(fields, "name")
    _text(fields, "unit")
    if "spec" in fields and fields["spec"] is None:
        raise ApiError(ErrorCode.VALIDATION_ERROR, "값을 비울 수 없습니다.", {"field": "spec"})
    _check_refs(db, fields)
    renamed = "name" in fields and fields["name"] != part.name
    for key, value in fields.items():
        setattr(part, key, value)
    part.updated_at = clock.utcnow()
    if renamed:
        part.embedding = part.embedding_model = None
    db.flush()
    if renamed and ai:
        embed_rows(db, ai, user.company_id, [part])
    return _part_out(db, part)
