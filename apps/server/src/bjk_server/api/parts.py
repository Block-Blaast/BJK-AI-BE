"""부품 API (API 명세서 3-2 SET)."""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import exists, func, or_, select

from bjk_server import clock
from bjk_server.auth import CurrentUser, TenantDB, require_role
from bjk_server.db.models import AuditFlag, Category, Movement, Part, PartAlias, Supplier
from bjk_server.errors import ApiError, ErrorCode
from bjk_server.inventory import latest_metrics_subquery, stock_of, stock_subquery
from bjk_server.pagination import Page, PageParams, keyset_page, page_params
from bjk_server.security import TokenClaims

router = APIRouter(prefix="/parts", tags=["parts"])

Manager = Annotated[TokenClaims, Depends(require_role("manager"))]
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
def create_part(body: PartCreate, user: Manager, db: TenantDB) -> PartOut:
    """SET-05. 부품 등록. 시작 재고는 원장에 ADJUST(사유 `초기 재고`)로 넣는다."""
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
    return _part_out(db, part)


@router.patch("/{part_id}", response_model=PartOut)
def update_part(part_id: uuid.UUID, body: PartUpdate, _: Manager, db: TenantDB) -> PartOut:
    """SET-05. 보낸 항목만 고친다. 재고는 바꾸지 않는다(정정·실사 기록으로 맞춘다).

    병합된 부품은 대표 부품을 고친다. name·unit·spec에 null은 400, 나머지는 null로 지운다.
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
    for key, value in fields.items():
        setattr(part, key, value)
    part.updated_at = clock.utcnow()
    db.flush()
    return _part_out(db, part)
