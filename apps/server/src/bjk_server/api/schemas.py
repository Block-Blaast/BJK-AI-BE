"""여러 API가 함께 쓰는 응답 스키마."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel

from bjk_server.config import get_settings
from bjk_server.domain.forecast import forecast_days
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


class ForecastPoint(BaseModel):
    date: date
    with_order: float
    without_order: float


class Forecast(BaseModel):
    """재고 추이 예측선 (#258, 명세 밖). `bjk_server.domain.forecast` 단순 추정."""

    as_of: date
    computed_at: datetime | None
    start_stock: float  # S + O + H_c
    monthly_use: float  # m
    order_qty: int  # 발주 시 선에 더하는 수량
    lead_days: int  # 발주 수량이 들어오는 날 (LT90)
    reorder_point: int | None
    t_out: date | None
    days: list[ForecastPoint]

    @classmethod
    def build(
        cls,
        *,
        as_of: date,
        start: float,
        monthly_use: float,
        order_qty: int,
        lead_days: int,
        **fields,
    ) -> "Forecast":
        points = forecast_days(as_of, start, monthly_use, order_qty, lead_days)
        return cls(
            as_of=as_of,
            start_stock=start,
            monthly_use=monthly_use,
            order_qty=order_qty,
            lead_days=lead_days,
            days=[ForecastPoint(**vars(p)) for p in points],
            **fields,
        )
