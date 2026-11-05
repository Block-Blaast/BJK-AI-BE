"""부품 이름·별칭 임베딩 (F-SETUP-02 5단계, F-MATCH-01 4단계, docs/ai-integration.md 3장).

저장용(document) 벡터는 등록·이름 변경 때 만들고, 실패하거나 비어 있는 행은 nightly가 다시 채운다.
검색용(query) 벡터는 채팅 부품 표현으로 후보를 찾을 때만 만들고 저장하지 않는다.
벡터는 만든 모델명과 함께 두고, 모델이 같은 벡터끼리만 비교한다.
"""

import uuid
from collections.abc import Callable, Sequence

from bjk_contracts import EMBED_MAX_TEXTS, EmbedTask, LlmUsage
from sqlalchemy import select
from sqlalchemy.orm import Session

from bjk_server.ai.client import QUERY_EMBED_TIMEOUT, AiClient, AiUnavailable
from bjk_server.ai.usage import record_usage
from bjk_server.db.models import Part, PartAlias

# nightly 한 번에 채우는 행 수 (부품 1,000종 기준 한 번에 끝나는 크기)
FILL_LIMIT = 2000


def _text(row: Part | PartAlias) -> str:
    return row.name if isinstance(row, Part) else row.text


def embed_rows(
    db: Session, ai: AiClient, company_id: uuid.UUID, rows: Sequence[Part | PartAlias]
) -> int:
    """저장용 벡터를 만들어 행에 넣고 채운 행 수를 돌려준다. 실패한 묶음부터는 비워 둔다."""
    filled = 0
    for start in range(0, len(rows), EMBED_MAX_TEXTS):
        batch = rows[start : start + EMBED_MAX_TEXTS]
        try:
            response = ai.embed(company_id, EmbedTask.DOCUMENT, [_text(r) for r in batch])
        except AiUnavailable:
            break
        record_usage(db, company_id, response.usage)
        if response.vectors is None:
            break
        for row, vector in zip(batch, response.vectors, strict=True):
            row.embedding, row.embedding_model = vector, response.model
        filled += len(batch)
    db.flush()
    return filled


def fill_missing(db: Session, ai: AiClient, company_id: uuid.UUID) -> int:
    """벡터가 없는 부품(병합되지 않은 것)·별칭을 채운다. 테넌트가 설정된 세션에서 부른다."""
    parts = db.scalars(
        select(Part)
        .where(Part.embedding.is_(None), Part.merged_into.is_(None))
        .order_by(Part.created_at)
        .limit(FILL_LIMIT)
    ).all()
    aliases = db.scalars(
        select(PartAlias)
        .where(PartAlias.embedding.is_(None))
        .order_by(PartAlias.created_at)
        .limit(FILL_LIMIT)
    ).all()
    return embed_rows(db, ai, company_id, [*parts, *aliases])


class AiQueryEmbedder:
    """채팅 부품 표현의 검색용 벡터. 실패하면 None을 돌려 규격·철자 매칭만 한다."""

    def __init__(
        self, ai: AiClient, company_id: uuid.UUID, on_usage: Callable[[LlmUsage], None]
    ) -> None:
        self._ai, self._company_id, self._on_usage = ai, company_id, on_usage

    def embed_query(self, text: str) -> tuple[str, list[float]] | None:
        try:
            response = self._ai.embed(
                self._company_id, EmbedTask.QUERY, [text], timeout=QUERY_EMBED_TIMEOUT
            )
        except (AiUnavailable, ValueError):
            return None
        if response.usage is not None:
            self._on_usage(response.usage)
        if response.vectors is None or response.model is None:
            return None
        return response.model, response.vectors[0]
