"""실사 응답(COUNT) 의도: 실사 요청에 센 수량을 채팅으로 답한다 (F-CHAT-05, AUD-03)."""

from sqlalchemy import or_, select

from bjk_server.audit.counts import answer_count
from bjk_server.chat.intents.base import IntentContext, IntentResult
from bjk_server.chat.interpreter import Interpretation
from bjk_server.chat.matching import find_candidates
from bjk_server.chat.records import to_base_qty
from bjk_server.db.models import CountRequest, Part

NO_REQUEST_REPLY = "답할 실사 요청이 없어요."
NO_QTY_REPLY = "센 수량을 숫자로 알려 주세요."


def handle(ctx: IntentContext, parsed: Interpretation) -> IntentResult:
    pending = _pending(ctx)
    if not pending:
        return IntentResult(NO_REQUEST_REPLY)
    if len(pending) > 1 and parsed.part_text:
        matched = find_candidates(ctx.db, parsed.part_text, None, ctx.embedder)
        found = [matched.confirmed] if matched.confirmed else matched.candidates
        ids = {c.part_id for c in found}
        pending = [r for r in pending if r.part_id in ids] or pending
    if len(pending) > 1:
        names = ", ".join(ctx.db.get(Part, r.part_id).name for r in pending)
        return IntentResult(f"어떤 부품을 세셨나요? {names}")
    request = pending[0]
    part = ctx.db.get(Part, request.part_id)
    qty = to_base_qty(parsed.qty, parsed.unit, part.pack_qty)
    if qty is None or qty < 0:
        return IntentResult(NO_QTY_REPLY)
    answer = answer_count(ctx.db, ctx.user, request.id, qty, ctx.now)
    return IntentResult(answer.reply, count_request_id=request.id)


def _pending(ctx: IntentContext) -> list[CountRequest]:
    """담당자 본인에게 전달돼 응답을 기다리는 실사 요청. 오래된 요청부터."""
    return list(
        ctx.db.scalars(
            select(CountRequest)
            .where(
                CountRequest.assignee_id == ctx.user.user_id,
                or_(
                    CountRequest.status == "sent",
                    (CountRequest.status == "scheduled") & (CountRequest.scheduled_for <= ctx.now),
                ),
            )
            .order_by(CountRequest.created_at)
        )
    )
