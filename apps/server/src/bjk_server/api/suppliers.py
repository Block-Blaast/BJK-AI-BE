"""공급사 API (API 명세서 SET-10, 기능명세서 F-SETUP-04).

공급사는 발주·납기 이력의 기준이라 삭제하지 않는다. 부품별 거래 조건만 지울 수 있다.
"""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select

from bjk_server.auth import TenantDB, require_role
from bjk_server.db.models import Part, Supplier, SupplierPart
from bjk_server.errors import ApiError, ErrorCode
from bjk_server.pagination import Page, PageParams, keyset_page, page_params
from bjk_server.security import TokenClaims

router = APIRouter(prefix="/suppliers", tags=["suppliers"])

Manager = Annotated[TokenClaims, Depends(require_role("manager"))]


class PriceTier(BaseModel):
    min_qty: int = Field(ge=1)
    unit_price: int = Field(ge=0)


class SupplierTerms(BaseModel):
    unit_price: int = Field(ge=0)
    moq: int = Field(default=1, ge=1)
    price_tiers: list[PriceTier] = []
    shipping_fee: int = Field(default=0, ge=0)

    @field_validator("price_tiers")
    @classmethod
    def _increasing(cls, tiers: list[PriceTier]) -> list[PriceTier]:
        mins = [t.min_qty for t in tiers]
        if mins != sorted(set(mins)):
            raise ValueError("단가 구간은 최소 수량이 겹치지 않게 오름차순으로 보내 주세요.")
        return tiers


class SupplierPartOut(SupplierTerms):
    part_id: uuid.UUID
    name: str


class SupplierOut(BaseModel):
    id: uuid.UUID
    name: str
    contact: str | None
    # 비어 있으면 납기 계산에 7일을 쓴다.
    default_lead_time_days: int | None
    holidays: list[date]
    part_count: int


class SupplierDetail(SupplierOut):
    parts: list[SupplierPartOut]


class SupplierCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    contact: str | None = Field(default=None, max_length=100)
    default_lead_time_days: int | None = Field(default=None, ge=1, le=365)
    holidays: list[date] = []


class SupplierUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    contact: str | None = Field(default=None, max_length=100)
    default_lead_time_days: int | None = Field(default=None, ge=1, le=365)
    holidays: list[date] | None = None


def _supplier(db: TenantDB, supplier_id: uuid.UUID) -> Supplier:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise ApiError(ErrorCode.NOT_FOUND, "공급사를 찾을 수 없습니다.")
    return supplier


def _check_name(db: TenantDB, name: str, own_id: uuid.UUID | None = None) -> str:
    name = name.strip()
    if not name:
        raise ApiError(ErrorCode.VALIDATION_ERROR, "이름을 입력해 주세요.", {"field": "name"})
    if db.scalar(select(Supplier.id).where(Supplier.name == name, Supplier.id != own_id)):
        raise ApiError(ErrorCode.NAME_TAKEN, "이미 있는 공급사 이름입니다.", {"name": name})
    return name


def _detail(db: TenantDB, supplier: Supplier) -> SupplierDetail:
    rows = db.execute(
        select(SupplierPart, Part.name)
        .join(Part, Part.id == SupplierPart.part_id)
        .where(SupplierPart.supplier_id == supplier.id)
        .order_by(Part.name.collate("C"), Part.id)
    ).all()
    parts = [
        SupplierPartOut(
            part_id=sp.part_id,
            name=name,
            unit_price=sp.unit_price,
            moq=sp.moq,
            price_tiers=sp.price_tiers,
            shipping_fee=sp.shipping_fee,
        )
        for sp, name in rows
    ]
    return SupplierDetail(
        id=supplier.id,
        name=supplier.name,
        contact=supplier.contact,
        default_lead_time_days=supplier.default_lead_time_days,
        holidays=sorted(supplier.holidays or []),
        part_count=len(parts),
        parts=parts,
    )


@router.get("", response_model=Page[SupplierOut])
def list_suppliers(
    _: Manager, db: TenantDB, params: Annotated[PageParams, Depends(page_params)]
) -> Page[SupplierOut]:
    """SET-10. 공급사 목록. 이름순(C 정렬)."""
    part_count = (
        select(func.count())
        .where(SupplierPart.supplier_id == Supplier.id)
        .correlate(Supplier)
        .scalar_subquery()
        .label("part_count")
    )
    return keyset_page(
        db,
        select(Supplier, part_count),
        [Supplier.name.collate("C"), Supplier.id],
        params,
        to_item=lambda r: SupplierOut(
            id=r.Supplier.id,
            name=r.Supplier.name,
            contact=r.Supplier.contact,
            default_lead_time_days=r.Supplier.default_lead_time_days,
            holidays=sorted(r.Supplier.holidays or []),
            part_count=r.part_count,
        ),
        cursor_of=lambda r: [r.Supplier.name, r.Supplier.id],
    )


@router.get("/{supplier_id}", response_model=SupplierDetail)
def get_supplier(supplier_id: uuid.UUID, _: Manager, db: TenantDB) -> SupplierDetail:
    """SET-10. 공급사와 부품별 단가·MOQ·단가 구간·배송비."""
    return _detail(db, _supplier(db, supplier_id))


@router.post("", status_code=201, response_model=SupplierDetail)
def create_supplier(body: SupplierCreate, user: Manager, db: TenantDB) -> SupplierDetail:
    supplier = Supplier(
        id=uuid.uuid4(),
        company_id=user.company_id,
        name=_check_name(db, body.name),
        contact=body.contact,
        default_lead_time_days=body.default_lead_time_days,
        holidays=sorted(set(body.holidays)),
    )
    db.add(supplier)
    db.flush()
    return _detail(db, supplier)


@router.patch("/{supplier_id}", response_model=SupplierDetail)
def update_supplier(
    supplier_id: uuid.UUID, body: SupplierUpdate, _: Manager, db: TenantDB
) -> SupplierDetail:
    """SET-10. 보낸 항목만 고친다. contact·default_lead_time_days는 null로 지울 수 있다."""
    supplier = _supplier(db, supplier_id)
    fields = body.model_dump(exclude_unset=True)
    for key in ("name", "holidays"):
        if key in fields and fields[key] is None:
            raise ApiError(ErrorCode.VALIDATION_ERROR, "값을 비울 수 없습니다.", {"field": key})
    if "name" in fields:
        supplier.name = _check_name(db, fields["name"], supplier.id)
    if "contact" in fields:
        supplier.contact = fields["contact"]
    if "default_lead_time_days" in fields:
        supplier.default_lead_time_days = fields["default_lead_time_days"]
    if "holidays" in fields:
        supplier.holidays = sorted(set(body.holidays))
    db.flush()
    return _detail(db, supplier)


@router.put("/{supplier_id}/parts/{part_id}", response_model=SupplierPartOut)
def put_supplier_part(
    supplier_id: uuid.UUID, part_id: uuid.UUID, body: SupplierTerms, user: Manager, db: TenantDB
) -> SupplierPartOut:
    """SET-10. 부품별 거래 조건 등록·수정. 이미 있으면 통째로 바꾼다."""
    supplier = _supplier(db, supplier_id)
    part = db.get(Part, part_id)
    if part is None or part.merged_into is not None:
        raise ApiError(ErrorCode.NOT_FOUND, "부품을 찾을 수 없습니다.", {"part_id": str(part_id)})
    terms = db.scalar(
        select(SupplierPart).where(
            SupplierPart.supplier_id == supplier.id, SupplierPart.part_id == part.id
        )
    )
    if terms is None:
        terms = SupplierPart(
            id=uuid.uuid4(), company_id=user.company_id, supplier_id=supplier.id, part_id=part.id
        )
        db.add(terms)
    terms.unit_price, terms.moq, terms.shipping_fee = body.unit_price, body.moq, body.shipping_fee
    terms.price_tiers = [t.model_dump() for t in body.price_tiers]
    db.flush()
    return SupplierPartOut(part_id=part.id, name=part.name, **body.model_dump())


@router.delete("/{supplier_id}/parts/{part_id}", status_code=204)
def delete_supplier_part(
    supplier_id: uuid.UUID, part_id: uuid.UUID, _: Manager, db: TenantDB
) -> Response:
    """SET-10. 부품별 거래 조건 삭제. 공급사 자체는 지우지 않는다."""
    terms = db.scalar(
        select(SupplierPart).where(
            SupplierPart.supplier_id == supplier_id, SupplierPart.part_id == part_id
        )
    )
    if terms is None:
        raise ApiError(ErrorCode.NOT_FOUND, "거래 조건을 찾을 수 없습니다.")
    db.delete(terms)
    return Response(status_code=204)
