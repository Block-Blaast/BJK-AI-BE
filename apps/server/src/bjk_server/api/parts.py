"""부품 API (API 명세서 3-2 SET)."""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import exists, false, func, or_, select

from bjk_server.auth import CurrentUser, TenantDB
from bjk_server.db.models import Category, Part, PartAlias
from bjk_server.inventory import latest_metrics_subquery, stock_subquery
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
