"""웹 푸시 구독 (API 명세서 NOT-04, Web Push VAPID). 자기 구독만 보고 지운다.

발송은 알림 생성(`bjk_server.notify`)에 붙인다(#184 후속). 푸시를 못 받는 기기도 NOT-01 목록에서
같은 내용을 본다.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from bjk_server import clock
from bjk_server.auth import CurrentUser, TenantDB
from bjk_server.config import get_settings
from bjk_server.db.models import PushSubscription
from bjk_server.errors import ApiError, ErrorCode

router = APIRouter(prefix="/push", tags=["push"])


class PushKeys(BaseModel):
    p256dh: Annotated[str, Field(min_length=1, max_length=200)]
    auth: Annotated[str, Field(min_length=1, max_length=100)]


class SubscribeRequest(BaseModel):
    endpoint: HttpUrl
    keys: PushKeys


class SubscriptionOut(BaseModel):
    id: uuid.UUID
    endpoint: str
    created_at: datetime


class VapidKey(BaseModel):
    public_key: str | None


def _out(row: PushSubscription) -> SubscriptionOut:
    return SubscriptionOut(
        id=row.id, endpoint=row.endpoint, created_at=row.created_at.astimezone(clock.KST)
    )


@router.get("/vapid-key", response_model=VapidKey)
def vapid_key(user: CurrentUser) -> VapidKey:
    """브라우저 구독(`applicationServerKey`)에 쓰는 공개 키. 설정이 없으면 null."""
    return VapidKey(public_key=get_settings().vapid_public_key)


@router.post("/subscriptions", response_model=SubscriptionOut, status_code=201)
def subscribe(body: SubscribeRequest, user: CurrentUser, db: TenantDB) -> SubscriptionOut:
    """NOT-04. 같은 endpoint를 다시 보내면 키와 사용자를 새 값으로 바꾼다."""
    endpoint = str(body.endpoint)
    if not endpoint.startswith("https://"):
        raise ApiError(ErrorCode.VALIDATION_ERROR, "endpoint는 https 주소여야 합니다.")
    now = clock.utcnow()
    stmt = insert(PushSubscription).values(
        company_id=user.company_id,
        user_id=user.user_id,
        endpoint=endpoint,
        p256dh=body.keys.p256dh,
        auth=body.keys.auth,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_push_subscriptions_company_endpoint",
        set_={
            "user_id": stmt.excluded.user_id,
            "p256dh": stmt.excluded.p256dh,
            "auth": stmt.excluded.auth,
            "updated_at": now,
        },
    ).returning(PushSubscription.id)
    row = db.get(PushSubscription, db.scalar(stmt), populate_existing=True)
    return _out(row)


@router.get("/subscriptions", response_model=list[SubscriptionOut])
def my_subscriptions(user: CurrentUser, db: TenantDB) -> list[SubscriptionOut]:
    rows = db.scalars(
        select(PushSubscription)
        .where(PushSubscription.user_id == user.user_id)
        .order_by(PushSubscription.created_at.desc(), PushSubscription.id)
    )
    return [_out(r) for r in rows]


@router.delete("/subscriptions/{subscription_id}", status_code=204)
def unsubscribe(subscription_id: uuid.UUID, user: CurrentUser, db: TenantDB) -> Response:
    row = db.get(PushSubscription, subscription_id)
    if row is None or row.user_id != user.user_id:
        raise ApiError(ErrorCode.NOT_FOUND, "구독을 찾을 수 없습니다.")
    db.delete(row)
    return Response(status_code=204)
