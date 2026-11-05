"""사용자 API (API 명세서 AUTH-08·09)."""

import uuid

from fastapi import APIRouter
from pydantic import BaseModel

from bjk_server.api.schemas import UserBrief
from bjk_server.auth import CurrentUser, TenantDB
from bjk_server.db.models import Company, User
from bjk_server.errors import ApiError, ErrorCode

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
