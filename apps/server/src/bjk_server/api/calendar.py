"""연휴 캘린더 API (API 명세서 SET-11, 기능명세서 F-EXT-01)."""

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from bjk_server.auth import TenantDB, require_role
from bjk_server.db.models import CalendarEvent, Supplier
from bjk_server.errors import ApiError, ErrorCode
from bjk_server.pagination import Page, PageParams, keyset_page, page_params
from bjk_server.security import TokenClaims

router = APIRouter(prefix="/calendar", tags=["calendar"])

Manager = Annotated[TokenClaims, Depends(require_role("manager"))]
Scope = Literal["KR", "CN", "supplier"]


class CalendarEventIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    start: date
    end: date
    scope: Scope
    # scope가 supplier일 때만 넣는다.
    supplier_id: uuid.UUID | None = None


class CalendarEventUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    start: date | None = None
    end: date | None = None
    scope: Scope | None = None
    supplier_id: uuid.UUID | None = None


class CalendarEventOut(CalendarEventIn):
    id: uuid.UUID


def _out(e: CalendarEvent) -> CalendarEventOut:
    return CalendarEventOut(
        id=e.id,
        name=e.name,
        start=e.start_date,
        end=e.end_date,
        scope=e.scope,
        supplier_id=e.supplier_id,
    )


def _validate(db: TenantDB, event: CalendarEvent) -> None:
    if event.end_date < event.start_date:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR, "종료일이 시작일보다 빠릅니다.", {"field": "end"}
        )
    if (event.scope == "supplier") != (event.supplier_id is not None):
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "공급사 휴무(scope: supplier)에만 supplier_id를 넣어 주세요.",
            {"field": "supplier_id"},
        )
    if event.supplier_id is not None and db.get(Supplier, event.supplier_id) is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            "공급사를 찾을 수 없습니다.",
            {"supplier_id": str(event.supplier_id)},
        )


def _get(db: TenantDB, event_id: uuid.UUID) -> CalendarEvent:
    event = db.get(CalendarEvent, event_id)
    if event is None:
        raise ApiError(ErrorCode.NOT_FOUND, "연휴 일정을 찾을 수 없습니다.")
    return event


@router.get("", response_model=Page[CalendarEventOut])
def list_calendar(
    _: Manager,
    db: TenantDB,
    params: Annotated[PageParams, Depends(page_params)],
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    scope: Scope | None = None,
) -> Page[CalendarEventOut]:
    """SET-11. 연휴 목록. 시작일 순. from·to는 기간과 겹치는 일정을 고른다."""
    stmt = select(CalendarEvent)
    if date_from:
        stmt = stmt.where(CalendarEvent.end_date >= date_from)
    if date_to:
        stmt = stmt.where(CalendarEvent.start_date <= date_to)
    if scope:
        stmt = stmt.where(CalendarEvent.scope == scope)
    return keyset_page(
        db,
        stmt,
        [CalendarEvent.start_date, CalendarEvent.id],
        params,
        to_item=lambda r: _out(r.CalendarEvent),
        cursor_of=lambda r: [r.CalendarEvent.start_date, r.CalendarEvent.id],
    )


@router.post("", status_code=201, response_model=CalendarEventOut)
def create_calendar_event(body: CalendarEventIn, user: Manager, db: TenantDB) -> CalendarEventOut:
    """SET-11. 연휴 등록. 다음 새벽 배치부터 납기에 반영된다."""
    event = CalendarEvent(
        id=uuid.uuid4(),
        company_id=user.company_id,
        name=body.name.strip(),
        start_date=body.start,
        end_date=body.end,
        scope=body.scope,
        supplier_id=body.supplier_id,
    )
    _validate(db, event)
    db.add(event)
    db.flush()
    return _out(event)


@router.patch("/{event_id}", response_model=CalendarEventOut)
def update_calendar_event(
    event_id: uuid.UUID, body: CalendarEventUpdate, _: Manager, db: TenantDB
) -> CalendarEventOut:
    """SET-11. 보낸 항목만 고친다. scope를 바꾸면 supplier_id도 함께 맞춰 보낸다."""
    event = _get(db, event_id)
    fields = body.model_dump(exclude_unset=True)
    for key in ("name", "start", "end", "scope"):
        if key in fields and fields[key] is None:
            raise ApiError(ErrorCode.VALIDATION_ERROR, "값을 비울 수 없습니다.", {"field": key})
    if "name" in fields:
        event.name = fields["name"].strip()
    if "start" in fields:
        event.start_date = fields["start"]
    if "end" in fields:
        event.end_date = fields["end"]
    if "scope" in fields:
        event.scope = fields["scope"]
    if "supplier_id" in fields:
        event.supplier_id = fields["supplier_id"]
    _validate(db, event)
    db.flush()
    return _out(event)


@router.delete("/{event_id}", status_code=204)
def delete_calendar_event(event_id: uuid.UUID, _: Manager, db: TenantDB) -> Response:
    db.delete(_get(db, event_id))
    return Response(status_code=204)
