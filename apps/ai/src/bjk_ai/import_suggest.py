"""엑셀 이관 규격 추출·카테고리 제안 (F-SETUP-02).

줄을 묶음으로 나눠 동시에 부른다. 한 묶음이라도 실패하면 전체를 대체 응답으로 돌려 server가
정규식 규격만 쓰게 한다(줄마다 결과 출처가 섞이지 않게).
"""

import asyncio
import json
import re
from enum import StrEnum

from bjk_contracts import (
    SPEC_KEYS,
    AiMeta,
    FallbackReason,
    ImportRow,
    ImportSuggestRequest,
    ImportSuggestResponse,
    LlmPurpose,
    RowSuggestion,
)
from pydantic import BaseModel

from bjk_ai.config import Settings
from bjk_ai.gateway import AttemptFailed, CallLog, LlmGateway, call_with_retry, usage_from

CHUNK_SIZE = 50

SpecKey = StrEnum("SpecKey", {key: key for key in SPEC_KEYS})

SYSTEM_PROMPT = (
    """\
너는 제조 현장 부품 목록을 정리한다. 엑셀의 각 줄에서 부품 이름(name)과 규격 열(spec_text)을 보고
규격(spec)을 뽑고 카테고리를 제안한다. JSON으로만 답한다.

규격 규칙:
- 아래 키만 쓴다. 해당하지 않으면 그 키는 넣지 않는다. 이름에 없는 값은 추측하지 않는다.
"""
    + "\n".join(f"  - {key}: {desc}" for key, desc in SPEC_KEYS.items())
    + """
- 예: "볼베어링 6205ZZ" → bearing_no 6205, shield ZZ
      "육각볼트 M8-20" → thread M8, length_mm 20
      "V벨트 A-42" → type A, length 42
      "오링 P-20" → size P20
      "수용성 절삭유 20L" → volume_l 20

카테고리 규칙:
- categories 목록의 id 중 하나만 고른다. 목록에 맞는 것이 없으면 category_id는 null.
- confidence는 0~1. 이름만으로 확실하면 0.9 이상, 헷갈리면 0.5 이하, 고르지 못하면 0.

rows의 모든 row에 대해 정확히 하나씩 답한다.
"""
)


class _LlmSpec(BaseModel):
    key: SpecKey
    value: str


class _LlmRow(BaseModel):
    row: int
    spec: list[_LlmSpec]
    category_id: str | None = None
    confidence: float


class _LlmOutput(BaseModel):
    rows: list[_LlmRow]


def normalize_spec_value(value: str) -> str:
    """server 매칭과 같은 정규화: 공백·하이픈 제거, 대문자."""
    return re.sub(r"[\s\-]", "", value).upper()


def build_prompt(request: ImportSuggestRequest, rows: list[ImportRow]) -> str:
    payload = {
        "categories": [c.model_dump() for c in request.categories],
        "rows": [r.model_dump(exclude_none=True) for r in rows],
    }
    return json.dumps(payload, ensure_ascii=False, indent=1)


def to_suggestions(
    output: _LlmOutput, rows: list[ImportRow], category_ids: set[str]
) -> list[RowSuggestion]:
    by_row = {item.row: item for item in output.rows}
    if set(by_row) != {r.row for r in rows} or len(output.rows) != len(rows):
        raise AttemptFailed(FallbackReason.SCHEMA_INVALID)
    suggestions = []
    for row in rows:
        item = by_row[row.row]
        spec = {}
        for pair in item.spec:
            value = normalize_spec_value(pair.value)
            if value:
                spec[pair.key.value] = value
        known = item.category_id in category_ids
        suggestions.append(
            RowSuggestion(
                row=row.row,
                spec=spec,
                category_id=item.category_id if known else None,
                confidence=min(max(item.confidence, 0.0), 1.0) if known else 0.0,
            )
        )
    return suggestions


async def suggest_import(
    request: ImportSuggestRequest, *, gateway: LlmGateway | None, settings: Settings
) -> ImportSuggestResponse:
    if gateway is None:
        return ImportSuggestResponse(
            suggestions=None, ai=AiMeta(used=False, fallback=True, reason=FallbackReason.ERROR)
        )

    category_ids = {c.id for c in request.categories}
    chunks = [request.rows[i : i + CHUNK_SIZE] for i in range(0, len(request.rows), CHUNK_SIZE)]

    async def run_chunk(rows: list[ImportRow]):
        prompt = build_prompt(request, rows)

        async def attempt(log: CallLog) -> list[RowSuggestion]:
            result = await gateway.generate_json(
                purpose=LlmPurpose.IMPORT_SUGGEST,
                system=SYSTEM_PROMPT,
                prompt=prompt,
                schema=_LlmOutput,
                max_tokens=8192,
                attempt=log.attempts,
            )
            log.record(result)
            output = _LlmOutput.model_validate_json(result.text)
            return to_suggestions(output, rows, category_ids)

        return await call_with_retry(attempt, budget_seconds=settings.import_budget_seconds)

    results = await asyncio.gather(*(run_chunk(rows) for rows in chunks))

    total = CallLog()
    for _, _, log in results:
        total.attempts += log.attempts
        total.input_tokens += log.input_tokens
        total.output_tokens += log.output_tokens
        total.model = log.model or total.model
        total.latency_ms = max(total.latency_ms, log.latency_ms)
    reasons = [reason for _, reason, _ in results if reason is not None]
    usage = usage_from(total, purpose=LlmPurpose.IMPORT_SUGGEST, success=not reasons)
    if reasons:
        return ImportSuggestResponse(suggestions=None, ai=AiMeta.failed(reasons[0]), usage=usage)
    suggestions = [s for chunk, _, _ in results for s in chunk]
    return ImportSuggestResponse(suggestions=suggestions, ai=AiMeta.ok(), usage=usage)
