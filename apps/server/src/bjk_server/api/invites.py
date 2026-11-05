"""직원 초대 API (API 명세서 AUTH-06·07).

사장님이 일회용 초대 토큰(72시간)을 만들고, 화면이 join_url로 QR을 그린다. 직원은 QR로
이름·PIN을 등록하고 바로 로그인 토큰과 회사 코드를 받는다.
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from bjk_server import clock
from bjk_server.api.schemas import TokenPair, UserBrief
from bjk_server.auth import require_role, set_tenant, tenant_db
from bjk_server.config import get_settings
from bjk_server.db.models import Company, Invite, User
from bjk_server.db.session import get_db
from bjk_server.errors import ApiError, ErrorCode
from bjk_server.security import TokenClaims, hash_secret

router = APIRouter(prefix="/auth/invites", tags=["auth"])

INVITE_TTL = timedelta(hours=72)
TOKEN_PREFIX = "inv_"

Owner = Annotated[TokenClaims, Depends(require_role("owner"))]
TenantDB = Annotated[Session, Depends(tenant_db)]
DB = Annotated[Session, Depends(get_db)]


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class InviteRequest(BaseModel):
    # owner는 초대로 만들지 않는다.
    role: Literal["worker", "manager"]


class InviteResponse(BaseModel):
    token: str
    join_url: str
    role: Literal["worker", "manager"]
    expires_at: datetime


@router.post("", response_model=InviteResponse, status_code=201)
def create_invite(body: InviteRequest, user: Owner, db: TenantDB) -> InviteResponse:
    """AUTH-06. 초대 토큰 생성. 원문은 응답에서만 주고 DB에는 해시만 남긴다."""
    token = TOKEN_PREFIX + secrets.token_urlsafe(24)
    expires_at = clock.utcnow() + INVITE_TTL
    db.add(
        Invite(
            company_id=user.company_id,
            token_hash=token_hash(token),
            role=body.role,
            created_by=user.user_id,
            expires_at=expires_at,
        )
    )
    db.flush()
    join_url = f"{get_settings().web_base_url.rstrip('/')}/join/{token}"
    return InviteResponse(token=token, join_url=join_url, role=body.role, expires_at=expires_at)


class AcceptRequest(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
    pin: str = Field(pattern=r"^\d{4}$")


class AcceptResponse(TokenPair):
    company_code: str
    user: UserBrief


def _expired(reason: Literal["used", "expired"]) -> ApiError:
    return ApiError(ErrorCode.INVITE_EXPIRED, "사장님께 새 QR을 요청하세요.", {"reason": reason})


@router.post("/{token}/accept", response_model=AcceptResponse, status_code=201)
def accept_invite(token: str, body: AcceptRequest, db: DB) -> AcceptResponse:
    """AUTH-07. 초대 수락. 이름·PIN을 등록하고 로그인 토큰과 회사 코드를 준다."""
    found = db.execute(
        text("SELECT invite_id, company_id FROM auth_invite_by_token(:h)"),
        {"h": token_hash(token)},
    ).first()
    if found is None:
        raise ApiError(ErrorCode.NOT_FOUND, "초대를 찾을 수 없습니다.")
    set_tenant(db, found.company_id)
    # 같은 토큰 동시 수락은 행 잠금으로 줄을 세워 한 명만 만든다.
    invite = db.scalar(select(Invite).where(Invite.id == found.invite_id).with_for_update())
    if invite is None:
        raise ApiError(ErrorCode.NOT_FOUND, "초대를 찾을 수 없습니다.")
    if invite.used_at is not None:
        raise _expired("used")
    now = clock.utcnow()
    if invite.expires_at <= now:
        raise _expired("expired")

    user = User(
        id=uuid.uuid4(),
        company_id=invite.company_id,
        name=body.name,
        role=invite.role,
        pin_hash=hash_secret(body.pin),
    )
    db.add(user)
    db.flush()
    invite.used_at = now
    invite.used_by = user.id
    company = db.get(Company, invite.company_id)

    tokens = TokenPair.issue(user.id, user.company_id, user.role)
    return AcceptResponse(
        **tokens.model_dump(),
        company_code=company.code,
        user=UserBrief(id=user.id, name=user.name, role=user.role),
    )
