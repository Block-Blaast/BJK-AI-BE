"""개발·시연 전용 API (API 명세서 DEV-01~04). APP_ENV=dev일 때만 라우트를 등록한다."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from bjk_server.auth import require_role
from bjk_server.db.session import get_admin_db
from bjk_server.security import TokenClaims
from bjk_server.seed.demo import COMPANY_CODE, KST, seed_demo

router = APIRouter(prefix="/api/v1/dev", tags=["dev"])

Owner = Annotated[TokenClaims, Depends(require_role("owner"))]


class SeedResetRequest(BaseModel):
    scenario: Literal["demo_v1"] = "demo_v1"


class SeedResetResponse(BaseModel):
    scenario: str
    company_code: str
    reset_at: datetime


@router.post("/seed/reset", response_model=SeedResetResponse)
def reset_seed(
    body: SeedResetRequest,
    _: Owner,
    admin_db: Annotated[Session, Depends(get_admin_db)],
) -> SeedResetResponse:
    """DEV-03. 모든 데이터를 지우고 시연 시드로 되돌린다.

    시드 ID가 고정이라 시연 계정 토큰은 초기화 뒤에도 그대로 쓸 수 있다.
    """
    seed_demo(admin_db, body.scenario)
    return SeedResetResponse(
        scenario=body.scenario, company_code=COMPANY_CODE, reset_at=datetime.now(KST)
    )
