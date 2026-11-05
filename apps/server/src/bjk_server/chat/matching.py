"""부품 표현 → 후보 부품 (server 규칙, 기능명세서 F-MATCH-01).

규칙은 domain.matching이 정하고, 여기서는 회사의 부품·별칭·재고를 읽어 넘긴다.
선택 카드 후보는 설비에 연결된 부품을 먼저 보여 준다.
ai 의미 유사도(별칭 후보 순위)는 ai 연동 후 순위에 더한다.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bjk_server.db.models import Equipment, EquipmentPart, Movement, Part, PartAlias
from bjk_server.domain.matching import PartText, match_parts
from bjk_server.inventory import stock_subquery

# 선택 카드는 후보 3개까지 (기능명세서 F-CHAT-02)
MAX_CANDIDATES = 3
# 1회 수량이 과거 1회 최대의 5배를 넘으면 경고 카드 (F-CHAT-02)
UNUSUAL_QTY_RATIO = 5


@dataclass(frozen=True)
class Candidate:
    part_id: uuid.UUID
    name: str
    unit: str
    stock: int
    reason: Literal["alias", "equipment_part", "name"]
    pack_qty: int | None = None


@dataclass(frozen=True)
class Matched:
    candidates: list[Candidate]
    # 별칭 일치 또는 규격 완전 일치 후보 1개일 때만 확정. 그 밖에는 사람이 고른다.
    confirmed: Candidate | None


def find_equipment(db: Session, text: str | None) -> Equipment | None:
    if not text or not text.strip():
        return None
    return db.scalar(
        select(Equipment).where(func.lower(Equipment.name) == text.strip().lower()).limit(1)
    )


def find_candidates(db: Session, part_text: str | None, equipment_id: uuid.UUID | None) -> Matched:
    if not part_text or not part_text.strip():
        return Matched([], None)
    stock = stock_subquery()
    rows = db.execute(
        select(
            Part.id,
            Part.name,
            Part.unit,
            Part.spec,
            Part.pack_qty,
            func.coalesce(stock.c.stock, 0).label("stock"),
        )
        .outerjoin(stock, stock.c.part_id == Part.id)
        .where(Part.merged_into.is_(None))
        .order_by(Part.name, Part.id)
    ).all()
    aliases: dict[uuid.UUID, list[tuple[str, bool]]] = defaultdict(list)
    for part_id, text, ambiguous in db.execute(
        select(PartAlias.part_id, PartAlias.text, PartAlias.ambiguous)
    ):
        aliases[part_id].append((text, ambiguous))
    linked = (
        set(
            db.scalars(
                select(EquipmentPart.part_id).where(EquipmentPart.equipment_id == equipment_id)
            )
        )
        if equipment_id
        else set()
    )

    result = match_parts(
        part_text.strip(), [PartText(r.id, r.name, r.spec, aliases[r.id]) for r in rows]
    )
    by_id = {r.id: r for r in rows}

    def candidate(part_id: uuid.UUID, by_alias: bool = False) -> Candidate:
        r = by_id[part_id]
        reason = "alias" if by_alias else "equipment_part" if part_id in linked else "name"
        return Candidate(r.id, r.name, r.unit, r.stock, reason, r.pack_qty)

    ordered = sorted(
        result.ranked, key=lambda m: m.part_id not in linked
    )  # 정렬 안정: 점수 순 유지
    candidates = [candidate(m.part_id) for m in ordered][:MAX_CANDIDATES]
    confirmed = (
        candidate(result.confirmed, by_alias=result.confirmed_by == "alias")
        if result.confirmed
        else None
    )
    return Matched(candidates, confirmed)


def is_unusual_qty(db: Session, part_id: uuid.UUID, intent: str, qty: int) -> bool:
    """같은 부품·같은 방향의 과거 1회 최대 수량 × 5를 넘는지. 이력이 없으면 경고하지 않는다."""
    past_max = db.scalar(
        select(func.max(func.abs(Movement.qty))).where(
            Movement.part_id == part_id, Movement.type == intent
        )
    )
    return past_max is not None and qty > past_max * UNUSUAL_QTY_RATIO
