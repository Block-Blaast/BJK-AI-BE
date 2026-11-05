"""order-check 배치: 주문 확인·입고 확인 필요 발주 알림 (매일 07:00, F-MISSED-02).

- 승인 후 24시간이 지나도 주문 완료 표시가 없는 발주 → 승인자에게 "주문하셨나요?"
  승인자가 없으면(시드 이력 등) 관리자·사장님에게 보낸다.
- 주문 완료 후 기본 공급사 LT90을 넘겨도 다 들어오지 않은 발주 → 관리자·사장님에게 "입고 확인 필요"
  LT90은 최신 근거 지표(part_metrics), 없으면 발주 공급사 기본 납기, 그것도 없으면 7일이다.
- 같은 발주는 알림 종류마다 사용자당 한 번만 보낸다(dedupe_key). 매일 반복하지 않는다(F-NOTI-03).
"""

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from bjk_server.auth import set_tenant
from bjk_server.db.models import Part, PartMetrics, PurchaseOrder, Supplier, User
from bjk_server.jobs.runner import company_ids, job
from bjk_server.notify.service import notify

ORDER_CONFIRM_AFTER = timedelta(hours=24)
DEFAULT_LEAD_DAYS = 7
MANAGER_ROLES = ("manager", "owner")


@job("order-check")
def run(session: Session, now: datetime) -> dict[str, Any]:
    order_check = receipt_check = 0
    for company_id in company_ids(session):
        set_tenant(session, company_id)
        managers = list(
            session.scalars(
                select(User.id).where(
                    User.company_id == company_id, User.role.in_(MANAGER_ROLES), User.active
                )
            )
        )
        for po in _not_ordered(session, company_id, now):
            part = session.get(Part, po.part_id)
            to = [po.approved_by] if po.approved_by else managers
            title = f"{part.name} {po.qty}{part.unit} 발주를 주문하셨나요?"
            order_check += len(
                notify(
                    session,
                    company_id,
                    to,
                    "order_check",
                    title,
                    now,
                    target=("order", po.id),
                    dedupe_key=f"order_check:{po.id}",
                )
            )
        for po in _ordered(session, company_id):
            if now <= po.ordered_at + timedelta(days=lt90(session, po)):
                continue
            part = session.get(Part, po.part_id)
            title = f"{part.name} 입고 확인이 필요해요. 납기가 지났어요."
            receipt_check += len(
                notify(
                    session,
                    company_id,
                    managers,
                    "receipt_check",
                    title,
                    now,
                    target=("order", po.id),
                    dedupe_key=f"receipt_check:{po.id}",
                )
            )
        session.flush()
    return {"order_check": order_check, "receipt_check": receipt_check}


def _not_ordered(session: Session, company_id: uuid.UUID, now: datetime) -> list[PurchaseOrder]:
    return list(
        session.scalars(
            select(PurchaseOrder).where(
                PurchaseOrder.company_id == company_id,
                PurchaseOrder.status == "approved",
                PurchaseOrder.ordered_at.is_(None),
                PurchaseOrder.approved_at <= now - ORDER_CONFIRM_AFTER,
            )
        )
    )


def _ordered(session: Session, company_id: uuid.UUID) -> list[PurchaseOrder]:
    return list(
        session.scalars(
            select(PurchaseOrder).where(
                PurchaseOrder.company_id == company_id,
                PurchaseOrder.status.in_(("ordered", "partially_received")),
                PurchaseOrder.ordered_at.is_not(None),
            )
        )
    )


def lt90(session: Session, po: PurchaseOrder) -> int:
    """기본 공급사 LT90(일). 근거 지표가 없으면 발주 공급사 기본 납기, 없으면 7일."""
    days = session.scalar(
        select(PartMetrics.lt90)
        .where(PartMetrics.part_id == po.part_id)
        .order_by(PartMetrics.computed_on.desc())
        .limit(1)
    )
    if days is not None:
        return days
    supplier = session.get(Supplier, po.supplier_id)
    return supplier.default_lead_time_days or DEFAULT_LEAD_DAYS
