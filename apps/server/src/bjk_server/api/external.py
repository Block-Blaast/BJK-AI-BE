"""외부 요인 현황 API (API 명세서 DSH-03, 기능명세서 F-EXT)."""

import uuid
from datetime import date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on

from bjk_server import clock
from bjk_server.api.health import STALE_AFTER
from bjk_server.auth import TenantDB, require_role
from bjk_server.clock import KST
from bjk_server.db.models import (
    CalendarEvent,
    Category,
    CompanySettings,
    ExternalIndicator,
    Supplier,
)
from bjk_server.domain.external import Level, apply_shock, risk_level
from bjk_server.jobs.nightly import shock_enabled
from bjk_server.security import TokenClaims

router = APIRouter(prefix="/external", tags=["external"])

Manager = Annotated[TokenClaims, Depends(require_role("manager"))]
# 다가오는 연휴로 보여줄 기간
HOLIDAY_HORIZON = timedelta(days=90)


class IndicatorStatus(BaseModel):
    code: str
    name: str
    series: Literal["lead", "price"]
    value: float
    as_of: date
    z: float | None
    r: float
    level: Level


class Holiday(BaseModel):
    name: str
    start: date
    end: date
    scope: Literal["KR", "CN", "supplier"]


class CategoryRisk(BaseModel):
    id: uuid.UUID
    name: str
    r_lead: float
    r_price: float
    level: Level


class ExternalStatusResponse(BaseModel):
    indicators: list[IndicatorStatus]
    upcoming_holidays: list[Holiday]
    categories: list[CategoryRisk]
    updated_at: datetime | None
    stale: bool


@router.get("/status", response_model=ExternalStatusResponse)
def external_status(user: Manager, db: TenantDB) -> ExternalStatusResponse:
    """DSH-03. 지표별 최신 위험도, 카테고리 위험도, 다가오는 연휴.

    위험도는 새벽 배치와 같은 값이다. 외부 충격 스위치(DEV-02)가 켜져 있으면 고정값을 보여준다.
    """
    now = clock.utcnow()
    latest = db.scalars(
        select(ExternalIndicator)
        .ext(distinct_on(ExternalIndicator.code))
        .order_by(ExternalIndicator.code, ExternalIndicator.as_of.desc())
    ).all()
    shocked = shock_enabled(db.get(CompanySettings, user.company_id))
    r_by_code = apply_shock({i.code: i.r for i in latest}, shocked)
    indicators = [
        IndicatorStatus(
            code=i.code,
            name=i.name,
            series=i.series,
            value=i.value,
            as_of=i.as_of,
            z=i.z,
            r=r_by_code[i.code],
            level=risk_level(r_by_code[i.code]),
        )
        for i in latest
    ]

    categories = []
    for c in db.scalars(select(Category).order_by(Category.name.collate("C"), Category.id)):
        r_lead = max((r_by_code.get(code, 0.0) for code in c.lead_factors), default=0.0)
        r_price = max((r_by_code.get(code, 0.0) for code in c.price_factors), default=0.0)
        categories.append(
            CategoryRisk(
                id=c.id,
                name=c.name,
                r_lead=r_lead,
                r_price=r_price,
                level=risk_level(max(r_lead, r_price)),
            )
        )

    # 연휴 캘린더(SET-11)와 공급사 휴무일 중 오늘부터 90일 안에 걸치는 것
    today = now.astimezone(KST).date()
    until = today + HOLIDAY_HORIZON
    events = db.scalars(
        select(CalendarEvent).where(
            CalendarEvent.end_date >= today, CalendarEvent.start_date <= until
        )
    )
    holidays = sorted(
        [
            *(
                Holiday(name=e.name, start=e.start_date, end=e.end_date, scope=e.scope)
                for e in events
            ),
            *(
                Holiday(name=f"{s.name} 휴무", start=day, end=day, scope="supplier")
                for s in db.scalars(select(Supplier))
                for day in s.holidays or ()
                if today <= day <= until
            ),
        ],
        key=lambda h: (h.start, h.name),
    )

    updated_at = db.scalar(select(func.max(ExternalIndicator.updated_at)))
    return ExternalStatusResponse(
        indicators=indicators,
        upcoming_holidays=holidays,
        categories=categories,
        updated_at=updated_at,
        stale=updated_at is None or now - updated_at > STALE_AFTER,
    )
