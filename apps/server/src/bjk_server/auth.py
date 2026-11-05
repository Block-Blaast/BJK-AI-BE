"""요청 인증·역할 검사·회사 격리 의존성 (API 명세서 1-2)."""

from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.orm import Session

from bjk_server.db.session import get_db
from bjk_server.errors import ApiError, ErrorCode
from bjk_server.security import Role, TokenClaims, decode_token

ROLE_RANK: dict[Role, int] = {"worker": 0, "manager": 1, "owner": 2}

_bearer = HTTPBearer(auto_error=False)


def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> TokenClaims:
    if credentials is None:
        raise ApiError(ErrorCode.UNAUTHORIZED, "인증이 필요합니다.")
    return decode_token(credentials.credentials, "access")


def require_role(minimum: Role) -> Callable[[TokenClaims], TokenClaims]:
    """minimum 이상 역할만 통과시킨다. 예: require_role("manager")는 manager·owner."""

    def check(user: Annotated[TokenClaims, Depends(current_user)]) -> TokenClaims:
        if ROLE_RANK[user.role] < ROLE_RANK[minimum]:
            raise ApiError(
                ErrorCode.FORBIDDEN_ROLE,
                "이 작업을 할 권한이 없습니다.",
                {"required": minimum, "role": user.role},
            )
        return user

    return check


def set_tenant(session: Session, company_id: object) -> None:
    """현재 트랜잭션에만 회사를 지정한다(SET LOCAL). RLS 정책이 이 값으로 행을 거른다."""
    session.execute(
        text("SELECT set_config('app.company_id', :company_id, true)"),
        {"company_id": str(company_id)},
    )


def tenant_db(
    user: Annotated[TokenClaims, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Iterator[Session]:
    set_tenant(db, user.company_id)
    yield db


CurrentUser = Annotated[TokenClaims, Depends(current_user)]
TenantDB = Annotated[Session, Depends(tenant_db)]
