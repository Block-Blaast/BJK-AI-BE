"""토큰 발급·검증과 비밀번호·PIN 해시 (API 명세서 1-2)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from bjk_server.config import get_settings
from bjk_server.errors import ApiError, ErrorCode

ALGORITHM = "HS256"
Role = Literal["worker", "manager", "owner"]
TokenType = Literal["access", "refresh"]

_hasher = PasswordHasher()


def hash_secret(raw: str) -> str:
    """비밀번호와 PIN 모두 argon2로 저장한다."""
    return _hasher.hash(raw)


def verify_secret(hashed: str | None, raw: str) -> bool:
    if not hashed:
        return False
    try:
        return _hasher.verify(hashed, raw)
    except (VerificationError, InvalidHashError):
        return False


@dataclass(frozen=True)
class TokenClaims:
    user_id: uuid.UUID
    company_id: uuid.UUID
    role: Role
    type: TokenType
    jti: str


def _issue(user_id: uuid.UUID, company_id: uuid.UUID, role: Role, type_: TokenType) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    ttl = (
        timedelta(minutes=settings.access_token_minutes)
        if type_ == "access"
        else timedelta(days=settings.refresh_token_days)
    )
    payload = {
        "user_id": str(user_id),
        "company_id": str(company_id),
        "role": role,
        "type": type_,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + ttl,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def create_access_token(user_id: uuid.UUID, company_id: uuid.UUID, role: Role) -> str:
    return _issue(user_id, company_id, role, "access")


def create_refresh_token(user_id: uuid.UUID, company_id: uuid.UUID, role: Role) -> str:
    return _issue(user_id, company_id, role, "refresh")


def decode_token(token: str, expected: TokenType) -> TokenClaims:
    try:
        payload = jwt.decode(
            token,
            get_settings().jwt_secret,
            algorithms=[ALGORITHM],
            options={"require": ["exp", "user_id", "company_id", "role", "type", "jti"]},
        )
        claims = TokenClaims(
            user_id=uuid.UUID(payload["user_id"]),
            company_id=uuid.UUID(payload["company_id"]),
            role=payload["role"],
            type=payload["type"],
            jti=payload["jti"],
        )
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise ApiError(ErrorCode.UNAUTHORIZED, "인증이 필요합니다.") from exc
    if claims.type != expected or claims.role not in ("worker", "manager", "owner"):
        raise ApiError(ErrorCode.UNAUTHORIZED, "인증이 필요합니다.")
    return claims
