"""부품 매칭 규칙 (기능명세서 F-MATCH-01). 순수 함수.

단계: 1 정규화 → 2 별칭 일치 → 3 규격 필터 → 5 자모 3-gram 철자 유사도.
4 임베딩 의미 유사도와 6 RRF 결합은 ai 연동 후 더한다. 지금 순위는 철자 유사도만으로 정한다.
"""

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

# 철자 유사도 기준. 이 값 미만이거나 1위 점수의 절반 미만인 후보는 뺀다.
MIN_SIMILARITY = 0.2
RELATIVE_CUTOFF = 0.5

_CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_JUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
_JONG = ["", *"ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ"]

# 규격 키 → 추출 정규식. 키는 parts.spec의 키와 같다. 정규화 전(소문자) 문자열에 적용한다.
_SPEC_PATTERNS: tuple[tuple[str, re.Pattern[str], int], ...] = (
    ("bearing_no", re.compile(r"(?<![\d.])(\d{4,5})(?:zz|2rs|rs|2z|z)?(?!\d)"), 1),
    ("shield", re.compile(r"(?<!\d)\d{4,5}\s*-?\s*(zz|2rs|rs|2z)(?![a-z])"), 1),
    ("thread", re.compile(r"(?<![a-z])(m\d{1,2})(?:\s*[x×*\-]\s*\d{1,3})?(?!\d)"), 1),
    ("length_mm", re.compile(r"(?<![a-z])m\d{1,2}\s*[x×*\-]\s*(\d{1,3})(?!\d)"), 1),
    ("type", re.compile(r"(?<![a-z\d])([a-e])\s*-?\s*\d{2,3}(?!\d)"), 1),
    ("length", re.compile(r"(?<![a-z\d])[a-e]\s*-?\s*(\d{2,3})(?!\d)"), 1),
    ("size", re.compile(r"(?<![a-z])(p\s*-?\s*\d{1,3})(?!\d)"), 1),
    ("volume_l", re.compile(r"(?<![\d.])(\d{1,3})\s*l(?![a-z])"), 1),
)


def normalize(text: str) -> str:
    """대소문자·전각·공백·기호를 통일한다. 규격 구분자(M8-20, M8*20, M8 x 20)는 x로 맞춘다."""
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"(?<=\d)\s*[x×*\-]\s*(?=\d)", "x", text)
    return re.sub(r"[\s\-_·./()]+", "", text)


def jamo(text: str) -> str:
    """한글 음절을 초성·중성·종성 자모로 분해한다 ("베어링" ↔ "베아링" 오타를 잡기 위해)."""
    out = []
    for ch in text:
        code = ord(ch) - 0xAC00
        if 0 <= code < 11172:
            out += [_CHO[code // 588], _JUNG[(code % 588) // 28], _JONG[code % 28]]
        else:
            out.append(ch)
    return "".join(out)


def _grams(text: str, n: int = 3) -> set[str]:
    padded = f"^{text}$"
    if len(padded) < n:
        return {padded}
    return {padded[i : i + n] for i in range(len(padded) - n + 1)}


def similarity(query: str, target: str) -> float:
    """자모 3-gram Jaccard. 대상은 띄어쓰기 단위와 전체 중 가장 비슷한 것으로 본다."""
    q = _grams(jamo(normalize(query)))
    best = 0.0
    for piece in [*target.split(), target]:
        t = _grams(jamo(normalize(piece)))
        best = max(best, len(q & t) / len(q | t))
    return best


def _spec_value(value: Any) -> str:
    return re.sub(r"[\s\-]", "", str(value)).upper()


def extract_spec(text: str) -> dict[str, str]:
    """부품 표현에서 규격 값을 뽑는다. 예: "볼베어링 6205ZZ" → {bearing_no: 6205, shield: ZZ}."""
    lowered = unicodedata.normalize("NFKC", text).lower()
    spec: dict[str, str] = {}
    for key, pattern, group in _SPEC_PATTERNS:
        found = pattern.search(lowered)
        if found:
            spec[key] = _spec_value(found.group(group))
    return spec


def spec_relation(query_spec: Mapping[str, str], part_spec: Mapping[str, Any]) -> str:
    """규격 관계.

    conflict: 같은 키의 값이 다름(이름이 비슷해도 매칭 금지), match: 뽑은 키가 모두 같음, none.
    """
    shared = [k for k in query_spec if k in part_spec]
    if any(query_spec[k] != _spec_value(part_spec[k]) for k in shared):
        return "conflict"
    if query_spec and len(shared) == len(query_spec):
        return "match"
    return "none"


@dataclass(frozen=True)
class PartText:
    """매칭 대상 부품의 이름·별칭·규격."""

    part_id: Any
    name: str
    spec: Mapping[str, Any]
    aliases: Sequence[tuple[str, bool]] = field(default_factory=tuple)  # (호칭, 모호 여부)


@dataclass(frozen=True)
class Ranked:
    part_id: Any
    score: float
    spec_match: bool


@dataclass(frozen=True)
class MatchResult:
    ranked: list[Ranked]
    # 확정된 부품: 별칭 일치 또는 규격 완전 일치 후보 1개. 없으면 사람에게 고르게 한다.
    confirmed: Any | None
    confirmed_by: str | None


def match_parts(query: str, parts: Sequence[PartText]) -> MatchResult:
    q_norm = normalize(query)
    q_spec = extract_spec(query)
    allowed = [p for p in parts if spec_relation(q_spec, p.spec) != "conflict"]

    alias_hits = {
        p.part_id
        for p in allowed
        for text, ambiguous in p.aliases
        if not ambiguous and normalize(text) == q_norm
    }
    shared_alias = {
        p.part_id for p in allowed for text, _ in p.aliases if normalize(text) == q_norm
    }

    ranked = []
    for p in allowed:
        score = max([similarity(query, p.name), *(similarity(query, a) for a, _ in p.aliases)])
        spec_match = spec_relation(q_spec, p.spec) == "match"
        if p.part_id in shared_alias:
            score = 1.0
        ranked.append(Ranked(p.part_id, score, spec_match))
    top = max((r.score for r in ranked), default=0.0)
    keep = [
        r
        for r in ranked
        if r.spec_match or (r.score >= MIN_SIMILARITY and r.score >= top * RELATIVE_CUTOFF)
    ]
    keep.sort(key=lambda r: (not r.spec_match, -r.score))

    if len(alias_hits) == 1 and len(shared_alias) == 1:
        return MatchResult(keep, next(iter(alias_hits)), "alias")
    spec_hits = [r for r in keep if r.spec_match]
    if len(spec_hits) == 1:
        return MatchResult(keep, spec_hits[0].part_id, "spec")
    return MatchResult(keep, None, None)
