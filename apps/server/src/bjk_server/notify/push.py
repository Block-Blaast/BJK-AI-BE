"""웹 푸시 발송 (API 명세서 NOT-04, 기능명세서 F-NOTI-04).

- `push` 채널 알림 중 보낼 시각(`sent_at`)이 지났고 아직 보내지 않은 것(`pushed_at` 없음)을 받는
  사람의 모든 구독으로 보낸다. 성공·실패와 관계없이 `pushed_at`을 남겨 한 번만 시도한다.
- 만료 응답(404·410)을 받은 구독은 지운다. 푸시가 실패해도 알림 목록(NOT-01)에는 그대로 남는다.
- 알림을 만든 트랜잭션이 커밋되면 바로 보내고, 조용한 시간으로 미룬 알림은 `push` 배치가 보낸다.
- VAPID 개인 키가 없으면 보내지 않는다(구독만 저장).
"""

import json
import logging
import uuid
from collections.abc import Callable, Iterable
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, event, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from bjk_server import clock
from bjk_server.auth import set_tenant
from bjk_server.config import get_settings
from bjk_server.db.models import Notification, PushSubscription

logger = logging.getLogger(__name__)

EXPIRED_STATUSES = (404, 410)
SEND_TIMEOUT = 5.0
# 구독 하나에 보내고 HTTP 상태 코드를 돌려준다. 연결 실패는 None.
Sender = Callable[[PushSubscription, str], int | None]


def _webpush_sender(private_key: str, subject: str) -> Sender:
    from pywebpush import WebPushException, webpush

    def send(sub: PushSubscription, payload: str) -> int | None:
        info = {"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}}
        try:
            response = webpush(
                info,
                payload,
                vapid_private_key=private_key,
                vapid_claims={"sub": subject},
                timeout=SEND_TIMEOUT,
            )
        except WebPushException as exc:
            return exc.response.status_code if exc.response is not None else None
        except Exception:  # noqa: BLE001 - 연결 실패도 다음 구독 발송을 막지 않는다
            return None
        return response.status_code

    return send


def default_sender() -> Sender | None:
    settings = get_settings()
    if not settings.vapid_private_key:
        return None
    return _webpush_sender(settings.vapid_private_key, settings.vapid_subject)


def payload_of(n: Notification) -> str:
    """서비스 워커가 띄울 내용. 화면은 target으로 해당 화면을 연다."""
    target = {"type": n.target_type, "id": str(n.target_id)} if n.target_type else None
    return json.dumps(
        {"notification_id": str(n.id), "kind": n.kind, "title": n.title, "target": target},
        ensure_ascii=False,
    )


@dataclass(frozen=True)
class PushResult:
    notifications: int = 0
    sent: int = 0
    failed: int = 0
    expired: int = 0


def dispatch(
    db: Session,
    sender: Sender,
    now: datetime,
    notification_ids: Iterable[uuid.UUID] | None = None,
) -> PushResult:
    """현재 회사(RLS)의 보낼 푸시를 보낸다. 같은 알림을 두 곳에서 동시에 보내지 않게 잠근다."""
    query = (
        select(Notification)
        .where(
            Notification.channels.any_() == "push",
            Notification.pushed_at.is_(None),
            Notification.sent_at <= now,
        )
        .order_by(Notification.sent_at, Notification.id)
        .with_for_update(skip_locked=True)
    )
    if notification_ids is not None:
        query = query.where(Notification.id.in_(list(notification_ids)))
    notifications = db.scalars(query).all()
    sent = failed = expired = 0
    for n in notifications:
        subs = db.scalars(
            select(PushSubscription)
            .where(PushSubscription.user_id == n.user_id)
            .order_by(PushSubscription.created_at, PushSubscription.id)
        ).all()
        payload = payload_of(n)
        for sub in subs:
            status = sender(sub, payload)
            if status is not None and 200 <= status < 300:
                sent += 1
            elif status in EXPIRED_STATUSES:
                expired += 1
                db.execute(delete(PushSubscription).where(PushSubscription.id == sub.id))
            else:
                failed += 1
                logger.warning("웹 푸시 실패 status=%s subscription=%s", status, sub.id)
        n.pushed_at = now
    db.flush()
    return PushResult(len(notifications), sent, failed, expired)


def _run(bind: Engine | Connection, company_id: uuid.UUID, ids: list[uuid.UUID]) -> None:
    sender = default_sender()
    if sender is None:
        return
    try:
        with Session(bind) as db, db.begin():
            set_tenant(db, company_id)
            dispatch(db, sender, clock.utcnow(), ids)
    except Exception:
        logger.exception("웹 푸시 발송 실패 company=%s", company_id)


_executor: Executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="push")


def push_after_commit(db: Session, company_id: uuid.UUID, ids: list[uuid.UUID]) -> None:
    """알림을 만든 트랜잭션이 커밋된 뒤 백그라운드로 보낸다. 롤백되면 보내지 않는다."""
    if not ids or get_settings().vapid_private_key is None:
        return
    bind = db.get_bind()

    def submit(_session: Session) -> None:
        _executor.submit(_run, bind, company_id, list(ids))

    event.listen(db, "after_commit", submit, once=True)
