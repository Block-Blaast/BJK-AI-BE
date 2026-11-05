"""중복 등록 부품 후보 탐지 (기능명세서 F-MATCH-03). 순수 함수.

같은 카테고리에서 규격이 완전히 같고 이름이 비슷한 쌍을 병합 후보로 본다.
이름 유사도는 같은 모델의 이름 임베딩 코사인을 쓰고,
한쪽이라도 벡터가 없으면 자모 3-gram 유사도를 쓴다.
"""

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations
from typing import Any

from bjk_server.domain.matching import _spec_value, similarity

# 이름 유사 기준. 명세에 없는 초깃값이다(F-SIM 조정 대상).
# 코사인은 매칭 확정 기준(0.85)보다 낮춰 사람이 판단할 후보를 넓게 잡는다.
MIN_NAME_COSINE = 0.8
# 임베딩이 없을 때의 자모 유사도 기준. 규격이 같다는 조건이 이미 강해서 낮게 둔다.
MIN_NAME_JAMO = 0.3
REASON = "spec_exact+name_similar"


@dataclass(frozen=True)
class MergePart:
    part_id: Any
    category_id: Any | None
    name: str
    spec: Mapping[str, Any]
    embedding: Sequence[float] | None = None
    embedding_model: str | None = None


@dataclass(frozen=True)
class MergePair:
    # part_a < part_b
    part_a: Any
    part_b: Any
    score: float
    reason: str = REASON


def _spec_key(spec: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((k, _spec_value(v)) for k, v in spec.items() if v not in (None, "")))


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def name_score(a: MergePart, b: MergePart) -> tuple[float, bool]:
    """(점수, 기준 통과). 같은 모델 벡터가 있으면 코사인, 없으면 자모 유사도(양방향 최댓값)."""
    if (
        a.embedding is not None
        and b.embedding is not None
        and a.embedding_model
        and a.embedding_model == b.embedding_model
    ):
        score = _cosine(a.embedding, b.embedding)
        return score, score >= MIN_NAME_COSINE
    score = max(similarity(a.name, b.name), similarity(b.name, a.name))
    return score, score >= MIN_NAME_JAMO


def find_duplicates(parts: Iterable[MergePart]) -> list[MergePair]:
    """병합 후보 쌍. 카테고리가 없거나 규격이 비어 있는 부품은 비교하지 않는다."""
    groups: dict[tuple[Any, tuple], list[MergePart]] = defaultdict(list)
    for part in parts:
        key = _spec_key(part.spec)
        if part.category_id is not None and key:
            groups[(part.category_id, key)].append(part)
    pairs = []
    for members in groups.values():
        for a, b in combinations(members, 2):
            score, similar = name_score(a, b)
            if similar:
                first, second = sorted((a.part_id, b.part_id))
                pairs.append(MergePair(first, second, round(score, 4)))
    return sorted(pairs, key=lambda p: (-p.score, str(p.part_a), str(p.part_b)))
