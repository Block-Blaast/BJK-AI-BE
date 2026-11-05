"""사용자 API (API 명세서 AUTH-08·09)."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from bjk_server.api.schemas import UserBrief
from bjk_server.auth import CurrentUser, TenantDB, require_role
from bjk_server.db.models import Company, User
from bjk_server.errors import ApiError, ErrorCode
from bjk_server.security import Role, TokenClaims

router = APIRouter(tags=["users"])


class CompanyBrief(BaseModel):
    id: uuid.UUID
    name: str
    code: str


class MeResponse(UserBrief):
    company: CompanyBrief


@router.get("/me", response_model=MeResponse)
def me(user: CurrentUser, db: TenantDB) -> MeResponse:
    """AUTH-08. 내 정보·역할과 회사 정보."""
    row = db.get(User, user.user_id)
    company = db.get(Company, user.company_id)
    if row is None or not row.active or company is None:
        raise ApiError(ErrorCode.UNAUTHORIZED, "인증이 필요합니다.")
    return MeResponse(
        id=row.id,
        name=row.name,
        role=row.role,
        company=CompanyBrief(id=company.id, name=company.name, code=company.code),
    )


Owner = Annotated[TokenClaims, Depends(require_role("owner"))]


class StaffItem(BaseModel):
    id: uuid.UUID
    name: str
    role: Role
    email: str | None
    has_pin: bool
    active: bool


class StaffList(BaseModel):
    items: list[StaffItem]


class RoleChange(BaseModel):
    # owner 지정·해제는 받지 않는다 (명세에 규정이 없어 사장님 1인 기준으로 정함).
    role: Literal["worker", "manager"]


def _staff(u: User) -> StaffItem:
    return StaffItem(
        id=u.id,
        name=u.name,
        role=u.role,
        email=u.email,
        has_pin=u.pin_hash is not None,
        active=u.active,
    )


@router.get("/users", response_model=StaffList)
def list_users(_: Owner, db: TenantDB) -> StaffList:
    """AUTH-09. 우리 회사 직원 목록. 이름순."""
    rows = db.scalars(select(User).order_by(User.name.collate("C"), User.id))
    return StaffList(items=[_staff(u) for u in rows])


@router.patch("/users/{user_id}", response_model=StaffItem)
def change_role(user_id: uuid.UUID, body: RoleChange, user: Owner, db: TenantDB) -> StaffItem:
    """AUTH-09. 직원 역할 변경. worker·manager 사이만 바꾼다.

    이미 발급된 액세스 토큰은 만료(15분) 전까지 이전 역할을 담고, 토큰 갱신부터 새 역할이 적용된다.
    """
    target = db.get(User, user_id)
    if target is None:
        raise ApiError(ErrorCode.NOT_FOUND, "사용자를 찾을 수 없습니다.")
    if target.id == user.user_id:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR, "본인 역할은 바꿀 수 없습니다.", {"reason": "self"}
        )
    if target.role == "owner":
        raise ApiError(
            ErrorCode.VALIDATION_ERROR, "사장님 역할은 바꿀 수 없습니다.", {"reason": "owner"}
        )
    target.role = body.role
    db.flush()
    return _staff(target)
