"""부품 표현 → 후보 부품 (server 규칙, 기능명세서 F-MATCH-01).

규칙은 domain.matching이 정하고, 여기서는 회사의 부품·별칭·재고와 의미 유사도 상위 후보를 읽어
넘긴다. 선택 카드 후보는 설비에 연결된 부품을 먼저 보여 준다.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Annotated, Literal, Protocol

from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bjk_server.ai.client import AiClient, get_ai_client
from bjk_server.ai.embeddings import AiQueryEmbedder
from bjk_server.ai.usage import record_usage
from bjk_server.auth import CurrentUser, TenantDB
from bjk_server.db.models import (
    CompanySettings,
    Equipment,
    EquipmentPart,
    Movement,
    Part,
    PartAlias,
)
from bjk_server.defaults import DEFAULT_SETTINGS
from bjk_server.domain.matching import PartText, match_parts
from bjk_server.inventory import stock_subquery

# 선택 카드는 후보 3개까지 (기능명세서 F-CHAT-02)
MAX_CANDIDATES = 3
# 1회 수량이 과거 1회 최대의 5배를 넘으면 경고 카드 (F-CHAT-02)
UNUSUAL_QTY_RATIO = 5
# 의미 유사도 후보 수 (F-MATCH-01 4단계: 코사인 거리 상위 10개)
SEMANTIC_TOP_K = 10


class QueryEmbedder(Protocol):
    """부품 표현의 검색용 벡터 (모델명, 벡터). 만들지 못하면 None."""

    def embed_query(self, text: str) -> tuple[str, list[float]] | None: ...


def get_query_embedder(
    user: CurrentUser,
    db: TenantDB,
    ai: Annotated[AiClient | None, Depends(get_ai_client)],
) -> QueryEmbedder | None:
    if ai is None:
        return None
    company_id = user.company_id
    return AiQueryEmbedder(ai, company_id, lambda usage: record_usage(db, company_id, usage))


Reason = Literal["alias", "equipment_part", "name", "semantic"]


@dataclass(frozen=True)
class Candidate:
    part_id: uuid.UUID
    name: str
    unit: str
    stock: int
    reason: Reason
    pack_qty: int | None = None


@dataclass(frozen=True)
class Matched:
    candidates: list[Candidate]
    # 별칭 일치, 규격 완전 일치 후보 1개, 코사인 확정일 때만 확정. 그 밖에는 사람이 고른다.
    confirmed: Candidate | None


def find_equipment(db: Session, text: str | None) -> Equipment | None:
    if not text or not text.strip():
        return None
    return db.scalar(
        select(Equipment).where(func.lower(Equipment.name) == text.strip().lower()).limit(1)
    )


def semantic_scores(db: Session, model: str, vector: list[float]) -> dict[uuid.UUID, float]:
    """이름·별칭 벡터 중 코사인 거리 상위 10개 부품 → 코사인 유사도 (F-MATCH-01 4단계).

    같은 모델로 만든 벡터만 비교한다. 모호한 별칭은 확정에 쓰지 않으므로 뺀다(F-MATCH-02).
    """
    scores: dict[uuid.UUID, float] = {}
    part_distance = Part.embedding.cosine_distance(vector)
    alias_distance = PartAlias.embedding.cosine_distance(vector)
    queries = (
        select(Part.id, part_distance)
        .where(Part.merged_into.is_(None), Part.embedding_model == model)
        .order_by(part_distance)
        .limit(SEMANTIC_TOP_K),
        select(PartAlias.part_id, alias_distance)
        .where(PartAlias.embedding_model == model, PartAlias.ambiguous.is_(False))
        .order_by(alias_distance)
        .limit(SEMANTIC_TOP_K),
    )
    for query in queries:
        for part_id, distance in db.execute(query):
            scores[part_id] = max(scores.get(part_id, -1.0), 1 - distance)
    top = sorted(scores.items(), key=lambda item: -item[1])[:SEMANTIC_TOP_K]
    return dict(top)


def _confirm_thresholds(db: Session) -> tuple[float, float]:
    """의미 유사도 확정 기준 (SYS-01 system.match_confirm_cosine, match_confirm_gap)."""
    row = db.scalar(select(CompanySettings).limit(1))
    system = {**DEFAULT_SETTINGS["system"], **(row.system if row else {})}
    return float(system["match_confirm_cosine"]), float(system["match_confirm_gap"])


def find_candidates(
    db: Session,
    part_text: str | None,
    equipment_id: uuid.UUID | None,
    embedder: QueryEmbedder | None = None,
) -> Matched:
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

    query_vector = embedder.embed_query(part_text.strip()) if embedder else None
    semantic = semantic_scores(db, *query_vector) if query_vector else None
    result = match_parts(
        part_text.strip(),
        [PartText(r.id, r.name, r.spec, aliases[r.id]) for r in rows],
        semantic,
        *(_confirm_thresholds(db) if semantic else ()),
    )
    by_id = {r.id: r for r in rows}
    semantic_only = {m.part_id for m in result.ranked if m.semantic_only}

    def candidate(part_id: uuid.UUID, by_alias: bool = False) -> Candidate:
        r = by_id[part_id]
        reason: Reason = "name"
        if by_alias:
            reason = "alias"
        elif part_id in linked:
            reason = "equipment_part"
        elif part_id in semantic_only:
            reason = "semantic"
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
