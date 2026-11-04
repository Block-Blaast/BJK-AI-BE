"""부품 표현 → 후보 부품 (server 규칙).

순서: 확정 별칭 일치 → 이름 부분 일치(설비에 연결된 부품 먼저).
ai 별칭 후보 순위는 ai 연동 후 이 결과를 보강한다.
"""

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bjk_server.db.models import Equipment, EquipmentPart, Part, PartAlias
from bjk_server.inventory import stock_subquery

MAX_CANDIDATES = 5


@dataclass(frozen=True)
class Candidate:
    part_id: uuid.UUID
    name: str
    unit: str
    stock: int
    reason: Literal["alias", "equipment_part", "name"]


def find_equipment(db: Session, text: str | None) -> Equipment | None:
    if not text or not text.strip():
        return None
    return db.scalar(
        select(Equipment).where(func.lower(Equipment.name) == text.strip().lower()).limit(1)
    )


def find_candidates(
    db: Session, part_text: str | None, equipment_id: uuid.UUID | None
) -> list[Candidate]:
    if not part_text or not part_text.strip():
        return []
    text = part_text.strip()
    stock = stock_subquery()
    columns = (Part.id, Part.name, Part.unit, func.coalesce(stock.c.stock, 0).label("stock"))
    base = (
        select(*columns)
        .outerjoin(stock, stock.c.part_id == Part.id)
        .where(Part.merged_into.is_(None))
    )

    alias_rows = db.execute(
        base.join(PartAlias, PartAlias.part_id == Part.id).where(
            func.lower(PartAlias.text) == text.lower(), PartAlias.ambiguous.is_(False)
        )
    ).all()
    if len(alias_rows) == 1:
        r = alias_rows[0]
        return [Candidate(r.id, r.name, r.unit, r.stock, "alias")]

    linked = (
        select(EquipmentPart.part_id).where(EquipmentPart.equipment_id == equipment_id)
        if equipment_id
        else None
    )
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    rows = db.execute(base.where(Part.name.ilike(f"%{escaped}%")).order_by(Part.name)).all()
    linked_ids = set(db.scalars(linked)) if linked is not None else set()
    candidates = [
        Candidate(r.id, r.name, r.unit, r.stock, "equipment_part" if r.id in linked_ids else "name")
        for r in rows
    ]
    candidates.sort(key=lambda c: c.reason != "equipment_part")
    return candidates[:MAX_CANDIDATES]
