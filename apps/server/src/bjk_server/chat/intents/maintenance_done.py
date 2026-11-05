"""정비 완료(MAINTENANCE_DONE) 의도: 설비의 가장 가까운 미완료 정비를 확인 카드로 보여준다.

확정(CHAT-03)하면 정비 완료(SET-09)와 같은 결과를 남긴다 (F-CHAT-06).
"""

from sqlalchemy import func, select

from bjk_server.chat.intents.base import IntentContext, IntentResult, equipment_ref
from bjk_server.chat.interpreter import Interpretation
from bjk_server.chat.matching import find_equipment
from bjk_server.chat.schemas import Card, MaintenanceRef
from bjk_server.clock import KST
from bjk_server.db.models import Maintenance

NO_EQUIPMENT_REPLY = "어느 설비의 정비인지 알려 주세요."


def handle(ctx: IntentContext, parsed: Interpretation) -> IntentResult:
    equipment = find_equipment(ctx.db, parsed.equipment_text)
    if equipment is None:
        return IntentResult(NO_EQUIPMENT_REPLY)
    today = ctx.now.astimezone(KST).date()
    # 오늘과 가장 가까운 미완료 정비. 거리가 같으면 앞선 일정.
    maintenance = ctx.db.scalar(
        select(Maintenance)
        .where(Maintenance.equipment_id == equipment.id, Maintenance.completed_at.is_(None))
        .order_by(func.abs(Maintenance.scheduled_date - today), Maintenance.scheduled_date)
        .limit(1)
    )
    if maintenance is None:
        return IntentResult(f"{equipment.name}에 완료할 정비 일정이 없어요.")
    payload = {
        "maintenance_id": str(maintenance.id),
        "equipment_id": str(equipment.id),
        "source_text": ctx.text,
    }
    entry = ctx.add_entry("confirm", "MAINTENANCE_DONE", payload)
    card = Card(
        type="confirm",
        entry_id=entry.id,
        intent="MAINTENANCE_DONE",
        equipment=equipment_ref(equipment),
        maintenance=MaintenanceRef(id=maintenance.id, scheduled_date=maintenance.scheduled_date),
        expires_at=entry.expires_at,
    )
    reply = f"{equipment.name} {maintenance.scheduled_date:%m/%d} 예정 정비를 완료할까요?"
    return IntentResult(reply, [card])
