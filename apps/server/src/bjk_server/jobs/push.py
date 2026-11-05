"""웹 푸시 배치 (API 명세서 NOT-04). 10분마다.

조용한 시간으로 미뤘다가 보낼 시각이 된 알림과, 커밋 직후 발송이 돌지 못한 알림을 보낸다.
VAPID 개인 키가 없으면 보내지 않는다.
"""

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from bjk_server.auth import set_tenant
from bjk_server.jobs.runner import company_ids, job
from bjk_server.notify import push


@job("push")
def push_job(session: Session, now: datetime) -> dict[str, Any]:
    sender = push.default_sender()
    if sender is None:
        return {"skipped": "vapid_not_configured"}
    totals = {"notifications": 0, "sent": 0, "failed": 0, "expired": 0}
    for cid in company_ids(session):
        set_tenant(session, cid)
        result = push.dispatch(session, sender, now)
        for key in totals:
            totals[key] += getattr(result, key)
    return totals
