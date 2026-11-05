"""ai 호출 기록 (`llm_calls`). 비용·장애 측정과 회사별 토큰 상한 판단에 쓴다."""

import uuid

from bjk_contracts import LlmUsage
from sqlalchemy.orm import Session

from bjk_server.db.models import LlmCall


def record_usage(db: Session, company_id: uuid.UUID, usage: LlmUsage | None) -> None:
    """ai가 돌려준 호출 한 번의 사용량을 한 줄로 남긴다. 부르지 못했으면(None) 남기지 않는다."""
    if usage is None:
        return
    db.add(
        LlmCall(
            id=uuid.uuid4(),
            company_id=company_id,
            purpose=usage.purpose.value,
            model=usage.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            latency_ms=usage.latency_ms,
            attempts=usage.attempts,
            success=usage.success,
        )
    )
