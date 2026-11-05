"""3D 창고 배치·예측 (화면 W-11, 명세 밖, #281).

기능명세서·API 명세서에 없는 화면이라 프론트 제안 형식(`types/twin.ts`)을 따른다. 3D는 계산하지
않고 그리기만 하므로 색·숫자는 모두 이 응답에서 온다. 배치는 회사별 `twin_layouts` 한 줄(지금은
시연 시드 더미), 예측은 원장·최신 근거 지표·열린 발주·정비 일정으로 조회할 때 계산한다.
"""

import json
import uuid
from datetime import date, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from bjk_server import clock
from bjk_server.auth import TenantDB, require_role
from bjk_server.chat.intents.incoming import DEFAULT_LEAD_DAYS, expected_date, lead_days
from bjk_server.clock import KST
from bjk_server.db.models import (
    AuditFlag,
    Equipment,
    EquipmentPart,
    Maintenance,
    Part,
    Review,
    TwinLayout,
)
from bjk_server.domain.twin import (
    DEFAULT_CV,
    HORIZON_DAYS,
    PATTERN_CV,
    BinInput,
    BinStatus,
    EquipmentStatus,
    project_bin,
    project_equipment,
)
from bjk_server.inventory import latest_metrics_subquery, merged_owners, stock_subquery
from bjk_server.purchasing.orders import open_orders, remaining_qty
from bjk_server.security import TokenClaims

router = APIRouter(prefix="/twin", tags=["twin"])

Manager = Annotated[TokenClaims, Depends(require_role("manager"))]
EquipmentKind = Literal["lathe", "mill", "press", "compressor", "conveyor"]
OPEN_FLAG = ("open", "count_requested")
# 배치가 없는 회사의 빈 바닥 크기(m)
EMPTY_SIZE = {"width": 20, "depth": 16}


class Size(BaseModel):
    width: float
    depth: float


class Zone(BaseModel):
    id: str
    kind: Literal["storage", "machines", "dock"]
    label: str
    x: float
    z: float
    width: float
    depth: float


class Rack(BaseModel):
    id: str
    label: str
    levels: int
    slots: int
    x: float
    z: float
    rotation: float
    purpose: str


class TwinEquipment(BaseModel):
    id: uuid.UUID
    name: str
    kind: EquipmentKind
    x: float
    z: float
    part_ids: list[uuid.UUID]


class Placement(BaseModel):
    part_id: uuid.UUID
    rack_id: str
    level: int
    slot: int


class Layout(BaseModel):
    size: Size
    zones: list[Zone]
    racks: list[Rack]
    equipment: list[TwinEquipment]
    placements: list[Placement]


def _equipment_parts(
    db: Session, owners: dict[uuid.UUID, uuid.UUID]
) -> dict[uuid.UUID, list[uuid.UUID]]:
    """설비 → 쓰는 부품(병합된 부품은 대표 부품으로, 중복 제거)."""
    parts: dict[uuid.UUID, list[uuid.UUID]] = {}
    for link in db.scalars(select(EquipmentPart).order_by(EquipmentPart.part_id)):
        part_id = owners.get(link.part_id, link.part_id)
        ids = parts.setdefault(link.equipment_id, [])
        if part_id not in ids:
            ids.append(part_id)
    return parts


@router.get("/layout", response_model=Layout)
def layout(user: Manager, db: TenantDB) -> Layout:
    """선반·구역·설비 좌표와 부품이 놓인 칸. 배치가 없는 회사는 빈 바닥."""
    row = db.get(TwinLayout, user.company_id)
    stored: dict[str, Any] = row.layout if row else {"size": EMPTY_SIZE}
    owners = merged_owners(db, user.company_id)
    equipment = {e.id: e for e in db.scalars(select(Equipment))}
    uses = _equipment_parts(db, owners)
    live = set(db.scalars(select(Part.id).where(Part.merged_into.is_(None))))
    placed: list[Placement] = []
    seen: set[uuid.UUID] = set()
    for p in stored.get("placements", []):
        part_id = uuid.UUID(p["part_id"])
        part_id = owners.get(part_id, part_id)
        if part_id in live and part_id not in seen:
            seen.add(part_id)
            placed.append(Placement(**{**p, "part_id": part_id}))
    return Layout(
        size=Size(**stored["size"]),
        zones=[Zone(**z) for z in stored.get("zones", [])],
        racks=[Rack(**r) for r in stored.get("racks", [])],
        equipment=[
            TwinEquipment(
                id=e.id,
                name=e.name,
                kind=pos["kind"],
                x=pos["x"],
                z=pos["z"],
                part_ids=uses.get(e.id, []),
            )
            for pos in stored.get("equipment", [])
            if (e := equipment.get(uuid.UUID(pos["equipment_id"]))) is not None
        ],
        placements=placed,
    )


class BinAudit(BaseModel):
    id: uuid.UUID
    reason: str
    grade: str


class BinMaintenance(BaseModel):
    date: date
    qty: int
    equipment: str


class Bin(BaseModel):
    part_id: uuid.UUID
    reorder_point: int | None
    qty: list[float]
    status: list[BinStatus]
    p_out: list[float]
    same_spec_group: str | None
    audit: BinAudit | None
    maintenance: list[BinMaintenance]


class EquipmentProjection(BaseModel):
    equipment_id: uuid.UUID
    status: list[EquipmentStatus]
    loss: list[int | None]
    cause_part_ids: list[list[uuid.UUID]]


class Arrival(BaseModel):
    part_id: uuid.UUID
    qty: int
    eta: date
    kind: Literal["ordered", "proposal"]
    review_id: uuid.UUID | None


class Projection(BaseModel):
    base_date: date
    horizon_days: int
    with_orders: bool
    computed_at: datetime | None
    is_mock: bool
    bins: list[Bin]
    equipment: list[EquipmentProjection]
    arrivals: list[Arrival]


def _spec_key(part: Part) -> str | None:
    if not part.spec:
        return None
    return f"{part.category_id}:{json.dumps(part.spec, sort_keys=True, ensure_ascii=False)}"


def _arrivals(db: Session, owners, live: set[uuid.UUID], base: date, with_orders, lt50):
    """열린 발주의 미입고분(도착 예상일이 지났으면 오늘), 발주하면 결정 대기 검토의 수정안."""
    ids = list(live | set(owners))
    arrivals = [
        Arrival(
            part_id=owners.get(po.part_id, po.part_id),
            qty=remaining_qty(po),
            eta=max(expected_date(db, po), base),
            kind="ordered",
            review_id=None,
        )
        for po in open_orders(db, ids)
        if remaining_qty(po) > 0
    ]
    if with_orders:
        for r in db.scalars(select(Review).where(Review.status == "reviewed").order_by(Review.id)):
            proposal = (r.result or {}).get("proposal")
            if r.part_id not in live or not proposal or proposal["qty"] <= 0:
                continue
            supplier = proposal.get("supplier_id")
            days = (
                lead_days(db, r.part_id, uuid.UUID(supplier))
                if supplier
                else lt50.get(r.part_id, DEFAULT_LEAD_DAYS)
            )
            arrivals.append(
                Arrival(
                    part_id=r.part_id,
                    qty=proposal["qty"],
                    eta=base + timedelta(days=days),
                    kind="proposal",
                    review_id=r.id,
                )
            )
    return arrivals


def _maintenance(db: Session, owners, base: date) -> dict[uuid.UUID, list[BinMaintenance]]:
    """끝나지 않은 오늘 이후 정비의 부품별 확정 필요량. 일정의 필요 부품, 없으면 설비 기준."""
    per_equipment: dict[uuid.UUID, list[tuple[uuid.UUID, int]]] = {}
    for link in db.scalars(select(EquipmentPart)):
        per_equipment.setdefault(link.equipment_id, []).append(
            (link.part_id, link.qty_per_maintenance)
        )
    names = dict(db.execute(select(Equipment.id, Equipment.name)).all())
    needs: dict[uuid.UUID, list[BinMaintenance]] = {}
    rows = db.scalars(
        select(Maintenance)
        .where(Maintenance.completed_at.is_(None), Maintenance.scheduled_date >= base)
        .order_by(Maintenance.scheduled_date, Maintenance.id)
    )
    for m in rows:
        parts = (
            [(uuid.UUID(r["part_id"]), int(r["qty"])) for r in m.required_parts]
            if m.required_parts is not None
            else per_equipment.get(m.equipment_id, [])
        )
        for part_id, qty in parts:
            needs.setdefault(owners.get(part_id, part_id), []).append(
                BinMaintenance(date=m.scheduled_date, qty=qty, equipment=names[m.equipment_id])
            )
    return needs


@router.get("/projection", response_model=Projection)
def projection(user: Manager, db: TenantDB, with_orders: bool = False) -> Projection:
    """부품별 8주 날짜별 재고·상태·결품 확률, 설비 상태·손실, 입고 예정.

    `with_orders=true`면 결정 대기 검토의 수정안을 발주한 것으로 보고 더한다.
    """
    base = clock.utcnow().astimezone(KST).date()
    owners = merged_owners(db, user.company_id)
    stock = stock_subquery()
    m = latest_metrics_subquery()
    rows = db.execute(
        select(Part, stock.c.stock, m.c.m, m.c.demand_class, m.c.lt50, m.c.lt90)
        .add_columns(m.c.reorder_point, m.c.computed_at)
        .outerjoin(stock, stock.c.part_id == Part.id)
        .outerjoin(m, m.c.part_id == Part.id)
        .where(Part.merged_into.is_(None))
        .order_by(Part.name, Part.id)
    ).all()
    live = {r.Part.id for r in rows}
    lt50 = {r.Part.id: r.lt50 for r in rows if r.lt50 is not None}
    arrivals = _arrivals(db, owners, live, base, with_orders, lt50)
    needs = _maintenance(db, owners, base)
    flags = {
        f.part_id: BinAudit(id=f.id, reason=f.rule, grade=f.level)
        for f in db.scalars(
            select(AuditFlag).where(AuditFlag.status.in_(OPEN_FLAG)).order_by(AuditFlag.id)
        )
    }
    keys = {r.Part.id: _spec_key(r.Part) for r in rows}
    counts: dict[str, int] = {}
    for k in keys.values():
        if k:
            counts[k] = counts.get(k, 0) + 1

    bins: list[Bin] = []
    paths = {}
    for r in rows:
        pid = r.Part.id
        path = project_bin(
            BinInput(
                stock=float(r.stock or 0),
                daily=(r.m or 0.0) / 30,
                cv=PATTERN_CV.get(r.demand_class, DEFAULT_CV),
                lt90=r.lt90 if r.lt90 is not None else DEFAULT_LEAD_DAYS,
                reorder_point=r.reorder_point,
                arrivals=[(a.eta, a.qty) for a in arrivals if a.part_id == pid],
                maintenance=[(n.date, n.qty) for n in needs.get(pid, [])],
            ),
            base,
        )
        paths[str(pid)] = path
        key = keys[pid]
        bins.append(
            Bin(
                part_id=pid,
                reorder_point=r.reorder_point,
                qty=path.qty,
                status=path.status,
                p_out=path.p_out,
                same_spec_group=key if key and counts[key] > 1 else None,
                audit=flags.get(pid),
                maintenance=needs.get(pid, []),
            )
        )

    uses = _equipment_parts(db, owners)
    lead = {str(k): v for k, v in lt50.items()}
    equipment = []
    for e in db.scalars(select(Equipment).order_by(Equipment.name, Equipment.id)):
        days = project_equipment(
            [str(p) for p in uses.get(e.id, [])],
            paths,
            lead,
            e.loss_per_hour * e.operating_hours,
        )
        equipment.append(
            EquipmentProjection(
                equipment_id=e.id,
                status=[d.status for d in days],
                loss=[d.loss for d in days],
                cause_part_ids=[[uuid.UUID(p) for p in d.causes] for d in days],
            )
        )
    computed = [r.computed_at for r in rows if r.computed_at is not None]
    return Projection(
        base_date=base,
        horizon_days=HORIZON_DAYS,
        with_orders=with_orders,
        computed_at=max(computed) if computed else None,
        is_mock=False,
        bins=bins,
        equipment=equipment,
        arrivals=arrivals,
    )
