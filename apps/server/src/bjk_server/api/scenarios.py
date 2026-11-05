"""시연 시나리오 API (명세 밖, #303). 운영 시연에서 사장님이 외부 충격을 켜고 끈다.

처리는 DEV-02(`/dev/scenarios/external-shock`)와 같다. DEV-02는 개발 모드에서만 열려 운영 시연에서
환율·해상운임 위험(3D 외부 요인 알림, C-09)을 보여 줄 방법이 없어서 사장님 전용으로 연다.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from bjk_server import clock
from bjk_server.auth import TenantDB, require_role
from bjk_server.db.models import CompanySettings
from bjk_server.domain.external import SHOCK_CODE, SHOCK_R
from bjk_server.errors import ApiError, ErrorCode
from bjk_server.jobs.nightly import compute_company, latest_risks, shock_enabled
from bjk_server.security import TokenClaims

router = APIRouter(prefix="/scenarios", tags=["scenarios"])

Owner = Annotated[TokenClaims, Depends(require_role("owner"))]


class ScenarioState(BaseModel):
    external_shock: bool


class ExternalShockRequest(BaseModel):
    enabled: bool


class ExternalShockResponse(BaseModel):
    enabled: bool
    indicator: str
    # 켜져 있으면 고정값, 꺼져 있으면 실제 최신 위험도
    r: float
    parts_computed: int
    computed_at: datetime


def _settings(db: Session, company_id: uuid.UUID) -> CompanySettings:
    settings = db.get(CompanySettings, company_id)
    if settings is None:
        raise ApiError(ErrorCode.NOT_FOUND, "회사 설정이 없습니다.")
    return settings


def switch_external_shock(
    db: Session, company_id: uuid.UUID, enabled: bool
) -> ExternalShockResponse:
    """외부 충격 스위치 (F-EXT-03). 해상운임 r을 3으로 고정하고 근거 지표를 다시 계산한다.

    스위치는 회사 설정에 남아 다음 새벽 배치도 같은 값을 쓴다. 끄면 실제 위험도로 다시 계산한다.
    이미 끝난 검토는 다시 돌리지 않는다. 새 검토부터 바뀐 위험도(C-09)를 쓴다.
    """
    settings = _settings(db, company_id)
    settings.scenarios = {**settings.scenarios, "external_shock": enabled}
    db.flush()
    now = clock.utcnow()
    risks = latest_risks(db)
    parts = compute_company(db, company_id, now, risks)
    return ExternalShockResponse(
        enabled=enabled,
        indicator=SHOCK_CODE,
        r=SHOCK_R if enabled else risks.get(SHOCK_CODE, 0.0),
        parts_computed=parts,
        computed_at=now,
    )


@router.get("", response_model=ScenarioState)
def get_scenarios(owner: Owner, db: TenantDB) -> ScenarioState:
    """켜져 있는 시연 시나리오."""
    return ScenarioState(external_shock=shock_enabled(_settings(db, owner.company_id)))


@router.post("/external-shock", response_model=ExternalShockResponse)
def external_shock(body: ExternalShockRequest, owner: Owner, db: TenantDB) -> ExternalShockResponse:
    """외부 충격 켜기·끄기. DEV-02와 같은 처리를 운영에서도 사장님에게 연다."""
    return switch_external_shock(db, owner.company_id, body.enabled)
