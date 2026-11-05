"""여러 API가 함께 쓰는 응답 스키마."""

import uuid

from pydantic import BaseModel

from bjk_server.config import get_settings
from bjk_server.security import Role, create_access_token, create_refresh_token


class UserBrief(BaseModel):
    id: uuid.UUID
    name: str
    role: Role


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int

    @classmethod
    def issue(cls, user_id: uuid.UUID, company_id: uuid.UUID, role: Role) -> "TokenPair":
        return cls(
            access_token=create_access_token(user_id, company_id, role),
            refresh_token=create_refresh_token(user_id, company_id, role),
            expires_in=get_settings().access_token_minutes * 60,
        )
