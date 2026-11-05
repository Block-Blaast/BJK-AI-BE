"""상태 확인 (API 명세서 SYS-02). 공개 API라 회사 데이터는 담지 않는다."""

from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from bjk_server import clock
from bjk_server.ai.client import AiClient, LlmStatus, get_ai_client
from bjk_server.db.models import ExternalIndicator, JobRun
from bjk_server.db.session import get_db

router = APIRouter(tags=["system"])

# 외부 지표가 이 시간 넘게 갱신되지 않으면 stale (API 명세서 DSH-03)
STALE_AFTER = timedelta(hours=24)


class LastBatch(BaseModel):
    nightly: datetime | None
    status: Literal["ok", "error", "skipped"] | None


class ExternalStatus(BaseModel):
    updated_at: datetime | None
    stale: bool


class HealthResponse(BaseModel):
    db: Literal["ok", "error"]
    # ai 주소 미설정 또는 ai에 LLM 미설정이면 not_configured, ai에 연결하지 못하면 error.
    llm: LlmStatus
    last_batch: LastBatch | None
    external_indicators: ExternalStatus | None


@router.get("/health", response_model=HealthResponse)
def health(
    db: Annotated[Session, Depends(get_db)],
    ai: Annotated[AiClient | None, Depends(get_ai_client)],
):
    """SYS-02. DB·LLM·배치·외부 지표 상태. DB에 연결하지 못하면 503."""
    llm: LlmStatus = ai.health() if ai else "not_configured"
    try:
        db.execute(text("SELECT 1"))
        run = db.scalar(
            select(JobRun)
            .where(JobRun.name == "nightly")
            .order_by(JobRun.started_at.desc())
            .limit(1)
        )
        updated_at = db.scalar(select(func.max(ExternalIndicator.updated_at)))
    except SQLAlchemyError:
        body = HealthResponse(db="error", llm=llm, last_batch=None, external_indicators=None)
        return JSONResponse(body.model_dump(mode="json"), 503)
    stale = updated_at is None or clock.utcnow() - updated_at > STALE_AFTER
    return HealthResponse(
        db="ok",
        llm=llm,
        last_batch=LastBatch(
            nightly=run.finished_at if run else None, status=run.status if run else None
        ),
        external_indicators=ExternalStatus(updated_at=updated_at, stale=stale),
    )
