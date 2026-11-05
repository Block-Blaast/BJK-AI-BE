"""인증 API (API 명세서 3-1 AUTH)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from bjk_server import pin_lock, ratelimit
from bjk_server.api.schemas import TokenPair, UserBrief
from bjk_server.auth import set_tenant
from bjk_server.db.models import User
from bjk_server.db.session import get_db
from bjk_server.errors import ApiError, ErrorCode
from bjk_server.security import decode_token, hash_secret, verify_secret

router = APIRouter(prefix="/auth", tags=["auth"])

DB = Annotated[Session, Depends(get_db)]

# 없는 이메일도 해시 검증 시간을 똑같이 쓰게 해 계정 존재 여부가 드러나지 않게 한다.
_DUMMY_HASH = hash_secret("dummy-password-for-timing")


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(TokenPair):
    user: UserBrief


def _invalid_credentials() -> ApiError:
    return ApiError(ErrorCode.INVALID_CREDENTIALS, "이메일 또는 비밀번호가 맞지 않습니다.")


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, db: DB) -> LoginResponse:
    """AUTH-02. 사장님·관리자 이메일 로그인."""
    found = db.execute(
        text("SELECT user_id, company_id FROM auth_lookup_by_email(:email)"),
        {"email": body.email.strip()},
    ).first()
    if found is None:
        verify_secret(_DUMMY_HASH, body.password)
        raise _invalid_credentials()

    set_tenant(db, found.company_id)
    user = db.get(User, found.user_id)
    if user is None or not verify_secret(user.password_hash, body.password):
        raise _invalid_credentials()

    tokens = TokenPair.issue(user.id, user.company_id, user.role)
    return LoginResponse(
        **tokens.model_dump(), user=UserBrief(id=user.id, name=user.name, role=user.role)
    )


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/refresh", response_model=TokenPair)
def refresh(body: RefreshRequest, db: DB) -> TokenPair:
    """AUTH-05. 리프레시 토큰으로 액세스·리프레시 토큰을 새로 발급한다.

    역할이 바뀌었을 수 있어 현재 사용자 정보로 발급한다. 이전 리프레시 토큰 폐기는
    명세에 없어 하지 않는다(만료 14일까지 유효).
    """
    claims = decode_token(body.refresh_token, "refresh")
    set_tenant(db, claims.company_id)
    user = db.get(User, claims.user_id)
    if user is None or not user.active:
        raise ApiError(ErrorCode.UNAUTHORIZED, "인증이 필요합니다.")
    return TokenPair.issue(user.id, user.company_id, user.role)


MEMBERS_PER_MINUTE = 10


def _company_id(db: Session, code: str) -> uuid.UUID:
    company_id = db.execute(
        text("SELECT auth_company_by_code(:code)"), {"code": code.strip()}
    ).scalar_one()
    if company_id is None:
        raise ApiError(ErrorCode.NOT_FOUND, "회사 코드를 찾을 수 없습니다.")
    return company_id


class Member(BaseModel):
    user_id: uuid.UUID
    name: str


class MembersResponse(BaseModel):
    items: list[Member]


@router.get("/companies/{code}/members", response_model=MembersResponse)
def members(code: str, request: Request, db: DB) -> MembersResponse:
    """AUTH-03. PIN 로그인용 이름 목록. 이름 외의 정보는 주지 않는다."""
    client_ip = request.client.host if request.client else "unknown"
    ratelimit.hit(db.get_bind(), f"members:{client_ip}", MEMBERS_PER_MINUTE, 60)
    set_tenant(db, _company_id(db, code))
    rows = db.execute(
        select(User.id, User.name)
        .where(User.active, User.pin_hash.is_not(None))
        .order_by(User.name, User.id)
    ).all()
    return MembersResponse(items=[Member(user_id=r.id, name=r.name) for r in rows])


class PinLoginRequest(BaseModel):
    company_code: str
    user_id: uuid.UUID
    pin: str


@router.post("/pin-login", response_model=LoginResponse)
def pin_login(body: PinLoginRequest, db: DB) -> LoginResponse:
    """AUTH-04. 이름 선택 + PIN 로그인. 같은 계정 5회 연속 실패 시 10분 잠금."""
    company_id = _company_id(db, body.company_code)
    set_tenant(db, company_id)
    user = db.get(User, body.user_id)
    if user is None or not user.active or user.pin_hash is None:
        raise ApiError(ErrorCode.NOT_FOUND, "사용자를 찾을 수 없습니다.")

    now = pin_lock.utcnow()
    pin_lock.ensure_not_locked(db, user.id, now)
    if not verify_secret(user.pin_hash, body.pin):
        raise pin_lock.record_failure(db.get_bind(), company_id, user.id, now)
    pin_lock.reset(db, user.id)

    tokens = TokenPair.issue(user.id, user.company_id, user.role)
    return LoginResponse(
        **tokens.model_dump(), user=UserBrief(id=user.id, name=user.name, role=user.role)
    )
