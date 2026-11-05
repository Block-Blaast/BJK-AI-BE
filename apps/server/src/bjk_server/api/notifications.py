"""알림 API (API 명세서 NOT-01·02). 자기 알림만 보고 읽음 처리한다."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select

from bjk_server import clock
from bjk_server.auth import CurrentUser, TenantDB
from bjk_server.db.models import Notification
from bjk_server.errors import ApiError, ErrorCode
from bjk_server.notify.service import Channel, Kind, TargetType
from bjk_server.pagination import PageParams, keyset_page, page_params

router = APIRouter(prefix="/notifications", tags=["notifications"])


class Target(BaseModel):
    type: TargetType
    id: uuid.UUID


class NotificationItem(BaseModel):
    id: uuid.UUID
    kind: Kind
    target: Target | None
    title: str
    channels: list[Channel]
    read: bool
    sent_at: datetime


class NotificationPage(BaseModel):
    items: list[NotificationItem]
    unread: int
    next_cursor: str | None


def _item(n: Notification) -> NotificationItem:
    target = Target(type=n.target_type, id=n.target_id) if n.target_type and n.target_id else None
    return NotificationItem(
        id=n.id,
        kind=n.kind,
        target=target,
        title=n.title,
        channels=n.channels,
        read=n.read_at is not None,
        sent_at=n.sent_at.astimezone(clock.KST),
    )


@router.get("", response_model=NotificationPage)
def list_notifications(
    user: CurrentUser, db: TenantDB, params: Annotated[PageParams, Depends(page_params)]
) -> NotificationPage:
    """NOT-01. 보낸 시각이 지난 내 알림, 최신 순."""
    now = clock.utcnow()
    mine = (Notification.user_id == user.user_id, Notification.sent_at <= now)
    page = keyset_page(
        db,
        select(Notification).where(*mine),
        [Notification.sent_at, Notification.id],
        params,
        to_item=lambda r: _item(r.Notification),
        cursor_of=lambda r: [r.Notification.sent_at, r.Notification.id],
        descending=True,
    )
    unread = db.scalar(select(func.count()).where(*mine, Notification.read_at.is_(None)))
    return NotificationPage(items=page.items, unread=unread or 0, next_cursor=page.next_cursor)


@router.post("/{notification_id}/read", response_model=NotificationItem)
def read_notification(
    notification_id: uuid.UUID, user: CurrentUser, db: TenantDB
) -> NotificationItem:
    """NOT-02. 이미 읽은 알림은 처음 읽은 시각을 유지한다. 다른 사람 알림은 404."""
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != user.user_id:
        raise ApiError(ErrorCode.NOT_FOUND, "알림을 찾을 수 없습니다.")
    if n.read_at is None:
        n.read_at = clock.utcnow()
    return _item(n)
