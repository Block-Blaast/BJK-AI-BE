"""아침 브리핑 조회 (API 명세서 DSH-01, 화면 M-04)."""

import uuid
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from bjk_server import clock
from bjk_server.auth import TenantDB, require_role
from bjk_server.briefing.service import build_briefing
from bjk_server.security import TokenClaims

router = APIRouter(prefix="/briefing", tags=["briefing"])

Manager = Annotated[TokenClaims, Depends(require_role("manager"))]


class MissedOrderItem(BaseModel):
    review_id: uuid.UUID
    part: str | None
    verdict: str | None
    flags: list[str]
    t_deadline: date | None
    expected_loss: int


class MissedOrders(BaseModel):
    count: int
    expected_loss_total: int
    items: list[MissedOrderItem]


class Briefing(BaseModel):
    date: date
    generated_at: datetime
    should_notify: bool
    missed_orders: MissedOrders
    pending_reviews: int
    count_needed: int
    order_check_needed: int
    maintenance_check_needed: int


@router.get("/today", response_model=Briefing)
def briefing_today(user: Manager, db: TenantDB) -> Briefing:
    """DSH-01. 오늘 확인할 일. 모두 0이면 `should_notify: false`."""
    return Briefing(**build_briefing(db, clock.utcnow()))
