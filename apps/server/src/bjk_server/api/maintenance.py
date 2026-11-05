"""정비 일정 API (API 명세서 SET-08, 기능명세서 F-SETUP-04)."""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import exists, select

from bjk_server.auth import TenantDB, require_role
from bjk_server.db.models import Equipment, EquipmentPart, Maintenance, Movement, Part
from bjk_server.errors import ApiError, ErrorCode
from bjk_server.pagination import Page, PageParams, keyset_page, page_params
from bjk_server.security import TokenClaims

router = APIRouter(prefix="/maintenance", tags=["maintenance"])

Manager = Annotated[TokenClaims, Depends(require_role("manager"))]


class RequiredPart(BaseModel):
    part_id: uuid.UUID
    qty: int = Field(ge=1)


def _unique(parts: list[RequiredPart] | None) -> list[RequiredPart] | None:
    ids = [p.part_id for p in parts or []]
    if len(ids) != len(set(ids)):
        raise ValueError("같은 부품을 두 번 넣을 수 없습니다.")
    return parts


class MaintenanceCreate(BaseModel):
    equipment_id: uuid.UUID
    scheduled_date: date
    # 비우면(null) 설비의 정비 1회당 부품·수량을 쓴다.
    required_parts: list[RequiredPart] | None = None

    _parts = field_validator("required_parts")(_unique)


class MaintenanceUpdate(BaseModel):
    equipment_id: uuid.UUID | None = None
    scheduled_date: date | None = None
    required_parts: list[RequiredPart] | None = None

    _parts = field_validator("required_parts")(_unique)


class EquipmentRef(BaseModel):
    id: uuid.UUID
    name: str


class PartNeed(BaseModel):
    part_id: uuid.UUID
    name: str
    qty: int


class MaintenanceOut(BaseModel):
    id: uuid.UUID
    equipment: EquipmentRef
    scheduled_date: date
    required_parts: list[RequiredPart] | None
    # 실제로 쓰는 필요 부품: 정비 일정의 required_parts, 없으면 설비 기준 (합산하지 않음)
    parts: list[PartNeed]
    parts_source: Literal["schedule", "equipment"]
    completed_at: datetime | None


def _out(db: TenantDB, m: Maintenance) -> MaintenanceOut:
    equipment = db.get(Equipment, m.equipment_id)
    if m.required_parts is not None:
        needs = [(uuid.UUID(r["part_id"]), int(r["qty"])) for r in m.required_parts]
        source = "schedule"
    else:
        needs = [
            (link.part_id, link.qty_per_maintenance)
            for link in db.scalars(
                select(EquipmentPart).where(EquipmentPart.equipment_id == m.equipment_id)
            )
        ]
        source = "equipment"
    names = dict(
        db.execute(select(Part.id, Part.name).where(Part.id.in_([p for p, _ in needs]))).all()
    )
    parts = sorted(
        (PartNeed(part_id=p, name=names.get(p, ""), qty=q) for p, q in needs),
        key=lambda n: (n.name, str(n.part_id)),
    )
    return MaintenanceOut(
        id=m.id,
        equipment=EquipmentRef(id=equipment.id, name=equipment.name),
        scheduled_date=m.scheduled_date,
        required_parts=m.required_parts,
        parts=parts,
        parts_source=source,
        completed_at=m.completed_at,
    )


def get_maintenance(db: TenantDB, maintenance_id: uuid.UUID) -> Maintenance:
    m = db.get(Maintenance, maintenance_id)
    if m is None:
        raise ApiError(ErrorCode.NOT_FOUND, "정비 일정을 찾을 수 없습니다.")
    return m


def _check_equipment(db: TenantDB, equipment_id: uuid.UUID) -> None:
    if db.get(Equipment, equipment_id) is None:
        raise ApiError(
            ErrorCode.NOT_FOUND, "설비를 찾을 수 없습니다.", {"equipment_id": str(equipment_id)}
        )


def _required(db: TenantDB, parts: list[RequiredPart] | None) -> list[dict] | None:
    if parts is None:
        return None
    for item in parts:
        part = db.get(Part, item.part_id)
        if part is None or part.merged_into is not None:
            raise ApiError(
                ErrorCode.NOT_FOUND, "부품을 찾을 수 없습니다.", {"part_id": str(item.part_id)}
            )
    return [{"part_id": str(p.part_id), "qty": p.qty} for p in parts]


def _not_completed(m: Maintenance) -> None:
    if m.completed_at is not None:
        raise ApiError(
            ErrorCode.ALREADY_CONFIRMED,
            "완료된 정비는 바꿀 수 없습니다.",
            {"status": "completed", "completed_at": m.completed_at.isoformat()},
        )


@router.get("", response_model=Page[MaintenanceOut])
def list_maintenance(
    _: Manager,
    db: TenantDB,
    params: Annotated[PageParams, Depends(page_params)],
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    equipment_id: uuid.UUID | None = None,
    completed: bool | None = None,
) -> Page[MaintenanceOut]:
    """SET-08. 정비 일정 목록. 예정일 순."""
    stmt = select(Maintenance)
    if date_from:
        stmt = stmt.where(Maintenance.scheduled_date >= date_from)
    if date_to:
        stmt = stmt.where(Maintenance.scheduled_date <= date_to)
    if equipment_id:
        stmt = stmt.where(Maintenance.equipment_id == equipment_id)
    if completed is not None:
        stmt = stmt.where(
            Maintenance.completed_at.is_not(None)
            if completed
            else Maintenance.completed_at.is_(None)
        )
    page = keyset_page(
        db,
        stmt,
        [Maintenance.scheduled_date, Maintenance.id],
        params,
        to_item=lambda r: r.Maintenance,
        cursor_of=lambda r: [r.Maintenance.scheduled_date, r.Maintenance.id],
    )
    return Page(items=[_out(db, m) for m in page.items], next_cursor=page.next_cursor)


@router.get("/{maintenance_id}", response_model=MaintenanceOut)
def read_maintenance(maintenance_id: uuid.UUID, _: Manager, db: TenantDB) -> MaintenanceOut:
    return _out(db, get_maintenance(db, maintenance_id))


@router.post("", status_code=201, response_model=MaintenanceOut)
def create_maintenance(body: MaintenanceCreate, user: Manager, db: TenantDB) -> MaintenanceOut:
    """SET-08. 정비 일정 등록. 다음 새벽 배치부터 확정 필요량 F에 들어간다."""
    _check_equipment(db, body.equipment_id)
    m = Maintenance(
        id=uuid.uuid4(),
        company_id=user.company_id,
        equipment_id=body.equipment_id,
        scheduled_date=body.scheduled_date,
        required_parts=_required(db, body.required_parts),
    )
    db.add(m)
    db.flush()
    return _out(db, m)


@router.patch("/{maintenance_id}", response_model=MaintenanceOut)
def update_maintenance(
    maintenance_id: uuid.UUID, body: MaintenanceUpdate, _: Manager, db: TenantDB
) -> MaintenanceOut:
    """SET-08. 보낸 항목만 고친다. required_parts에 null을 보내면 설비 기준으로 돌아간다."""
    m = get_maintenance(db, maintenance_id)
    _not_completed(m)
    fields = body.model_dump(exclude_unset=True)
    for key in ("equipment_id", "scheduled_date"):
        if key in fields and fields[key] is None:
            raise ApiError(ErrorCode.VALIDATION_ERROR, "값을 비울 수 없습니다.", {"field": key})
    if "equipment_id" in fields:
        _check_equipment(db, body.equipment_id)
        m.equipment_id = body.equipment_id
    if "scheduled_date" in fields:
        m.scheduled_date = body.scheduled_date
    if "required_parts" in fields:
        m.required_parts = _required(db, body.required_parts)
    db.flush()
    return _out(db, m)


@router.delete("/{maintenance_id}", status_code=204)
def delete_maintenance(maintenance_id: uuid.UUID, _: Manager, db: TenantDB) -> Response:
    """SET-08. 취소한 정비 일정 삭제. 완료됐거나 출고가 연결된 정비는 기록 보존을 위해 막는다."""
    m = get_maintenance(db, maintenance_id)
    _not_completed(m)
    if db.scalar(select(exists().where(Movement.maintenance_id == m.id))):
        raise ApiError(
            ErrorCode.ALREADY_CONFIRMED,
            "출고가 연결된 정비는 삭제할 수 없습니다.",
            {"status": "linked"},
        )
    db.delete(m)
    return Response(status_code=204)
