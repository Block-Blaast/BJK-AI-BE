"""카테고리 API (API 명세서 SET-06, 기능명세서 F-SETUP-03)."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from bjk_server.auth import TenantDB, require_role
from bjk_server.db.models import Category
from bjk_server.errors import ApiError, ErrorCode
from bjk_server.pagination import Page, PageParams, keyset_page, page_params
from bjk_server.security import TokenClaims

router = APIRouter(prefix="/categories", tags=["categories"])

Manager = Annotated[TokenClaims, Depends(require_role("manager"))]
Dependency = Literal["high", "medium", "low"]
# 카테고리에 연결할 수 있는 요인 코드 (F-SETUP-03). 명절(HOLIDAY_*)은 연휴 캘린더 범위다.
LeadFactor = Literal["FREIGHT", "HOLIDAY_KR", "HOLIDAY_CN"]
PriceFactor = Literal["USDKRW"]


class CategoryOut(BaseModel):
    id: uuid.UUID
    name: str
    import_dependency: Dependency
    lead_factors: list[LeadFactor]
    price_factors: list[PriceFactor]
    hs_code: str | None


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    import_dependency: Dependency = "low"
    lead_factors: list[LeadFactor] = []
    price_factors: list[PriceFactor] = []
    hs_code: str | None = Field(default=None, max_length=16)


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    import_dependency: Dependency | None = None
    lead_factors: list[LeadFactor] | None = None
    price_factors: list[PriceFactor] | None = None
    hs_code: str | None = Field(default=None, max_length=16)


def _out(c: Category) -> CategoryOut:
    return CategoryOut(
        id=c.id,
        name=c.name,
        import_dependency=c.import_dependency,
        lead_factors=c.lead_factors,
        price_factors=c.price_factors,
        hs_code=c.hs_code,
    )


def _check_name(db: TenantDB, name: str, own_id: uuid.UUID | None = None) -> str:
    name = name.strip()
    if not name:
        raise ApiError(ErrorCode.VALIDATION_ERROR, "이름을 입력해 주세요.", {"field": "name"})
    taken = db.scalar(select(Category.id).where(Category.name == name, Category.id != own_id))
    if taken:
        raise ApiError(ErrorCode.NAME_TAKEN, "이미 있는 카테고리 이름입니다.", {"name": name})
    return name


def _unique(codes: list[str]) -> list[str]:
    return list(dict.fromkeys(codes))


@router.get("", response_model=Page[CategoryOut])
def list_categories(
    _: Manager, db: TenantDB, params: Annotated[PageParams, Depends(page_params)]
) -> Page[CategoryOut]:
    """SET-06 보조. 카테고리와 수입 의존·납기 요인·가격 요인. 이름순(C 정렬)."""
    return keyset_page(
        db,
        select(Category),
        [Category.name.collate("C"), Category.id],
        params,
        to_item=lambda r: _out(r.Category),
        cursor_of=lambda r: [r.Category.name, r.Category.id],
    )


@router.post("", status_code=201, response_model=CategoryOut)
def create_category(body: CategoryCreate, user: Manager, db: TenantDB) -> CategoryOut:
    """SET-06. 카테고리 등록. 연결 요인은 다음 새벽 배치부터 위험도에 반영된다."""
    category = Category(
        id=uuid.uuid4(),
        company_id=user.company_id,
        name=_check_name(db, body.name),
        import_dependency=body.import_dependency,
        lead_factors=_unique(body.lead_factors),
        price_factors=_unique(body.price_factors),
        hs_code=body.hs_code,
    )
    db.add(category)
    db.flush()
    return _out(category)


@router.patch("/{category_id}", response_model=CategoryOut)
def update_category(
    category_id: uuid.UUID, body: CategoryUpdate, _: Manager, db: TenantDB
) -> CategoryOut:
    """SET-06. 보낸 항목만 고친다. hs_code는 null을 보내면 지운다."""
    category = db.get(Category, category_id)
    if category is None:
        raise ApiError(ErrorCode.NOT_FOUND, "카테고리를 찾을 수 없습니다.")
    fields = body.model_dump(exclude_unset=True)
    for key in ("name", "import_dependency", "lead_factors", "price_factors"):
        if key in fields and fields[key] is None:
            raise ApiError(ErrorCode.VALIDATION_ERROR, "값을 비울 수 없습니다.", {"field": key})
    if "name" in fields:
        category.name = _check_name(db, fields["name"], category.id)
    if "import_dependency" in fields:
        category.import_dependency = fields["import_dependency"]
    if "lead_factors" in fields:
        category.lead_factors = _unique(fields["lead_factors"])
    if "price_factors" in fields:
        category.price_factors = _unique(fields["price_factors"])
    if "hs_code" in fields:
        category.hs_code = fields["hs_code"]
    db.flush()
    return _out(category)
