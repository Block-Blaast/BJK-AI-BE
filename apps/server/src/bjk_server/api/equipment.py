"""설비 API (API 명세서 SET-07, 기능명세서 F-SETUP-04).

설비는 출고·정비 원장에 연결되므로 삭제하지 않는다.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select

from bjk_server.auth import TenantDB, require_role
from bjk_server.db.models import Equipment, EquipmentPart, Part
from bjk_server.errors import ApiError, ErrorCode
from bjk_server.pagination import Page, PageParams, keyset_page, page_params
from bjk_server.security import TokenClaims

router = APIRouter(prefix="/equipment", tags=["equipment"])

Manager = Annotated[TokenClaims, Depends(require_role("manager"))]


class EquipmentPartIn(BaseModel):
    part_id: uuid.UUID
    qty_per_maintenance: int = Field(ge=1)


class EquipmentPartOut(EquipmentPartIn):
    name: str


def _unique_parts(parts: list[EquipmentPartIn] | None) -> list[EquipmentPartIn] | None:
    ids = [p.part_id for p in parts or []]
    if len(ids) != len(set(ids)):
        raise ValueError("같은 부품을 두 번 넣을 수 없습니다.")
    return parts


class EquipmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    # 0이면 손실액 미입력: 금액 대신 "멈추는 설비"만 표시한다.
    loss_per_hour: int = Field(default=0, ge=0)
    loss_is_estimate: bool = True
    operating_hours: int = Field(default=8, ge=1, le=24)
    parts: list[EquipmentPartIn] = []

    _parts = field_validator("parts")(_unique_parts)


class EquipmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    loss_per_hour: int | None = Field(default=None, ge=0)
    loss_is_estimate: bool | None = None
    operating_hours: int | None = Field(default=None, ge=1, le=24)
    # 보내면 연결 부품 전체를 바꾼다.
    parts: list[EquipmentPartIn] | None = None

    _parts = field_validator("parts")(_unique_parts)


class EquipmentOut(BaseModel):
    id: uuid.UUID
    name: str
    loss_per_hour: int
    loss_is_estimate: bool
    operating_hours: int
    parts: list[EquipmentPartOut]


def _parts_of(db: TenantDB, ids: list[uuid.UUID]) -> dict[uuid.UUID, list[EquipmentPartOut]]:
    parts: dict[uuid.UUID, list[EquipmentPartOut]] = {i: [] for i in ids}
    for link, name in db.execute(
        select(EquipmentPart, Part.name)
        .join(Part, Part.id == EquipmentPart.part_id)
        .where(EquipmentPart.equipment_id.in_(ids))
        .order_by(Part.name.collate("C"), Part.id)
    ):
        parts[link.equipment_id].append(
            EquipmentPartOut(
                part_id=link.part_id, name=name, qty_per_maintenance=link.qty_per_maintenance
            )
        )
    return parts


def _out(e: Equipment, parts: list[EquipmentPartOut]) -> EquipmentOut:
    return EquipmentOut(
        id=e.id,
        name=e.name,
        loss_per_hour=e.loss_per_hour,
        loss_is_estimate=e.loss_is_estimate,
        operating_hours=e.operating_hours,
        parts=parts,
    )


def _get(db: TenantDB, equipment_id: uuid.UUID) -> Equipment:
    equipment = db.get(Equipment, equipment_id)
    if equipment is None:
        raise ApiError(ErrorCode.NOT_FOUND, "설비를 찾을 수 없습니다.")
    return equipment


def _check_name(db: TenantDB, name: str, own_id: uuid.UUID | None = None) -> str:
    """채팅이 설비를 이름(대소문자 무시)으로 찾으므로 회사 안에서 겹치지 않게 한다."""
    name = name.strip()
    if not name:
        raise ApiError(ErrorCode.VALIDATION_ERROR, "이름을 입력해 주세요.", {"field": "name"})
    taken = db.scalar(
        select(Equipment.id).where(
            func.lower(Equipment.name) == name.lower(), Equipment.id != own_id
        )
    )
    if taken:
        raise ApiError(ErrorCode.NAME_TAKEN, "이미 있는 설비 이름입니다.", {"name": name})
    return name


def _set_parts(db: TenantDB, equipment: Equipment, parts: list[EquipmentPartIn]) -> None:
    for item in parts:
        part = db.get(Part, item.part_id)
        if part is None or part.merged_into is not None:
            raise ApiError(
                ErrorCode.NOT_FOUND, "부품을 찾을 수 없습니다.", {"part_id": str(item.part_id)}
            )
    db.execute(delete(EquipmentPart).where(EquipmentPart.equipment_id == equipment.id))
    for item in parts:
        db.add(
            EquipmentPart(
                id=uuid.uuid4(),
                company_id=equipment.company_id,
                equipment_id=equipment.id,
                part_id=item.part_id,
                qty_per_maintenance=item.qty_per_maintenance,
            )
        )
    db.flush()


@router.get("", response_model=Page[EquipmentOut])
def list_equipment(
    _: Manager, db: TenantDB, params: Annotated[PageParams, Depends(page_params)]
) -> Page[EquipmentOut]:
    """SET-07. 설비와 정비 1회당 부품·수량. 이름순(C 정렬)."""
    page = keyset_page(
        db,
        select(Equipment),
        [Equipment.name.collate("C"), Equipment.id],
        params,
        to_item=lambda r: r.Equipment,
        cursor_of=lambda r: [r.Equipment.name, r.Equipment.id],
    )
    parts = _parts_of(db, [e.id for e in page.items])
    return Page(items=[_out(e, parts[e.id]) for e in page.items], next_cursor=page.next_cursor)


@router.get("/{equipment_id}", response_model=EquipmentOut)
def get_equipment(equipment_id: uuid.UUID, _: Manager, db: TenantDB) -> EquipmentOut:
    equipment = _get(db, equipment_id)
    return _out(equipment, _parts_of(db, [equipment.id])[equipment.id])


@router.post("", status_code=201, response_model=EquipmentOut)
def create_equipment(body: EquipmentCreate, user: Manager, db: TenantDB) -> EquipmentOut:
    equipment = Equipment(
        id=uuid.uuid4(),
        company_id=user.company_id,
        name=_check_name(db, body.name),
        loss_per_hour=body.loss_per_hour,
        loss_is_estimate=body.loss_is_estimate,
        operating_hours=body.operating_hours,
    )
    db.add(equipment)
    db.flush()
    _set_parts(db, equipment, body.parts)
    return _out(equipment, _parts_of(db, [equipment.id])[equipment.id])


@router.patch("/{equipment_id}", response_model=EquipmentOut)
def update_equipment(
    equipment_id: uuid.UUID, body: EquipmentUpdate, _: Manager, db: TenantDB
) -> EquipmentOut:
    """SET-07. 보낸 항목만 고친다. parts를 보내면 연결 부품 전체를 바꾼다."""
    equipment = _get(db, equipment_id)
    fields = body.model_dump(exclude_unset=True)
    for key, value in fields.items():
        if value is None:
            raise ApiError(ErrorCode.VALIDATION_ERROR, "값을 비울 수 없습니다.", {"field": key})
    if "name" in fields:
        equipment.name = _check_name(db, fields["name"], equipment.id)
    for key in ("loss_per_hour", "loss_is_estimate", "operating_hours"):
        if key in fields:
            setattr(equipment, key, fields[key])
    if body.parts is not None:
        _set_parts(db, equipment, body.parts)
    db.flush()
    return _out(equipment, _parts_of(db, [equipment.id])[equipment.id])
