"""설정 API (API 명세서 SYS-01). 사장님은 notify·review만 바꾸고 system은 바꾸지 못한다."""

import re
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from bjk_server.auth import require_role, tenant_db
from bjk_server.db.models import CompanySettings
from bjk_server.defaults import default_settings
from bjk_server.security import TokenClaims

router = APIRouter(prefix="/settings", tags=["settings"])

Owner = Annotated[TokenClaims, Depends(require_role("owner"))]
TenantDB = Annotated[Session, Depends(tenant_db)]

_HHMM = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def _hhmm(value: str) -> str:
    if not _HHMM.match(value):
        raise ValueError("HH:MM 형식이어야 합니다.")
    return value


class _Patch(BaseModel):
    # 정의되지 않은 키(system 포함)는 400으로 거절한다.
    model_config = ConfigDict(extra="forbid")


class QuietHoursPatch(_Patch):
    start: str = Field(default=None)
    end: str = Field(default=None)

    _check = field_validator("start", "end")(_hhmm)


class NotifyPatch(_Patch):
    quiet_hours: QuietHoursPatch = Field(default=None)
    briefing_time: str = Field(default=None)

    @field_validator("briefing_time")
    @classmethod
    def _briefing_range(cls, value: str) -> str:
        _hhmm(value)
        if not "06:00" <= value <= "10:00":
            raise ValueError("06:00~10:00 사이여야 합니다.")
        return value


ServiceLevel = Annotated[float, Field(ge=0.80, le=0.995)]


class ServiceLevelPatch(_Patch):
    A: ServiceLevel = Field(default=None)
    B: ServiceLevel = Field(default=None)
    C: ServiceLevel = Field(default=None)


class ReviewPatch(_Patch):
    service_level: ServiceLevelPatch = Field(default=None)
    next_order_weeks: int = Field(default=None, ge=1, le=8)
    c02_months: int = Field(default=None, ge=3, le=24)
    c05_sigma: float = Field(default=None, ge=1, le=3)
    c06_ratio: float = Field(default=None, ge=0.5, le=0.95)
    c08_days: int = Field(default=None, ge=1, le=14)


class SettingsPatch(_Patch):
    notify: NotifyPatch = Field(default=None)
    review: ReviewPatch = Field(default=None)


class SettingsResponse(BaseModel):
    notify: dict[str, Any]
    review: dict[str, Any]
    system: dict[str, Any]
    updated_at: datetime | None


def _merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _response(row: CompanySettings | None) -> SettingsResponse:
    if row is None:
        return SettingsResponse(**default_settings(), updated_at=None)
    return SettingsResponse(
        notify=row.notify, review=row.review, system=row.system, updated_at=row.updated_at
    )


@router.get("", response_model=SettingsResponse)
def get_settings(user: Owner, db: TenantDB) -> SettingsResponse:
    """SYS-01. 설정 행이 없는 회사는 기본값을 준다."""
    return _response(db.get(CompanySettings, user.company_id))


@router.patch("", response_model=SettingsResponse)
def patch_settings(body: SettingsPatch, user: Owner, db: TenantDB) -> SettingsResponse:
    """SYS-01. 보낸 키만 바꾸고 나머지는 유지한다. 다음 검토·다음 배치부터 적용된다."""
    patch = body.model_dump(exclude_unset=True)
    row = db.get(CompanySettings, user.company_id)
    if row is None:
        row = CompanySettings(company_id=user.company_id, **default_settings())
        db.add(row)
    # JSONB 열은 새 dict를 대입해야 변경으로 기록된다.
    row.notify = _merge(row.notify, patch.get("notify", {}))
    row.review = _merge(row.review, patch.get("review", {}))
    row.updated_at = func.now()
    db.flush()
    db.refresh(row)
    return _response(row)
