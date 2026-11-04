"""개발·시연 전용 API (API 명세서 DEV-01~04). APP_ENV=dev일 때만 라우트를 등록한다."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from bjk_server.api.auth import LoginResponse
from bjk_server.api.schemas import TokenPair, UserBrief
from bjk_server.auth import TenantDB, require_role
from bjk_server.db.models import User
from bjk_server.db.session import get_admin_db
from bjk_server.errors import ApiError, ErrorCode
from bjk_server.security import Role, TokenClaims
from bjk_server.seed.demo import COMPANY_CODE, KST, demo_id, seed_demo

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


class ImpersonateRequest(BaseModel):
    role: Role


@router.post("/impersonate", response_model=LoginResponse)
def impersonate(body: ImpersonateRequest, owner: Owner, db: TenantDB) -> LoginResponse:
    """DEV-04. 같은 회사에서 해당 역할의 시연 계정 토큰을 발급한다.

    시드 계정(owner, manager, worker)이 있으면 그 계정, 없으면 가장 먼저 만든 계정을 쓴다.
    """
    user = db.get(User, demo_id("user", body.role))
    is_demo = user is not None and user.active and user.role == body.role
    if not is_demo or user.company_id != owner.company_id:
        user = db.scalar(
            select(User)
            .where(User.role == body.role, User.active)
            .order_by(User.created_at, User.id)
            .limit(1)
        )
    if user is None:
        raise ApiError(ErrorCode.NOT_FOUND, "해당 역할의 계정이 없습니다.", {"role": body.role})
    tokens = TokenPair.issue(user.id, user.company_id, user.role)
    return LoginResponse(
        **tokens.model_dump(), user=UserBrief(id=user.id, name=user.name, role=user.role)
    )
