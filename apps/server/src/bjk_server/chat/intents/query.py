"""재고 조회(QUERY) 의도: 현재 재고, 입고 예정, 소진 예상일 답변 (F-CHAT-03)."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from bjk_server.chat.intents.base import IntentContext, IntentResult
from bjk_server.chat.intents.incoming import incoming_sentence
from bjk_server.chat.interpreter import Interpretation
from bjk_server.chat.matching import QueryEmbedder, find_candidates
from bjk_server.clock import KST
from bjk_server.db.models import PartMetrics

# 소진일 경로 시뮬레이션 기간 (F-ANAL-07)
STOCKOUT_HORIZON_WEEKS = 8


def _copula(word: str) -> str:
    """받침이 있으면 '이에요', 없으면 '예요' (예: 통이에요, 개예요)."""
    last = word[-1:] if word else ""
    has_final = "가" <= last <= "힣" and (ord(last) - ord("가")) % 28 != 0
    return "이에요" if has_final else "예요"


def handle(ctx: IntentContext, parsed: Interpretation) -> IntentResult:
    return IntentResult(_reply(ctx.db, parsed, ctx.now, ctx.embedder))


def _reply(
    db: Session, parsed: Interpretation, now: datetime, embedder: QueryEmbedder | None = None
) -> str:
    matched = find_candidates(db, parsed.part_text, None, embedder)
    candidates = [matched.confirmed] if matched.confirmed else matched.candidates
    if not candidates:
        return f"'{parsed.part_text or ''}'에 해당하는 부품을 찾지 못했어요."
    if len(candidates) > 1:
        names = ", ".join(c.name for c in candidates)
        return f"어떤 부품인지 알려 주세요: {names}"
    part = candidates[0]
    at = now.astimezone(KST).strftime("%m/%d %H:%M")
    reply = f"{part.name} 현재 재고 {part.stock}{part.unit}{_copula(part.unit)}."
    reply = f"{reply} {incoming_sentence(db, part.part_id, part.unit)}"
    # 소진 예상일은 최신 새벽 계산(part_metrics) 값이다.
    metrics = db.execute(
        select(PartMetrics.t_out, PartMetrics.computed_at)
        .where(PartMetrics.part_id == part.part_id)
        .order_by(PartMetrics.computed_on.desc())
        .limit(1)
    ).first()
    if metrics is None:
        return f"{reply} 소진 예상일은 새벽 계산 뒤에 알려 드려요. (재고 기준 {at})"
    computed = metrics.computed_at.astimezone(KST).strftime("%m/%d %H:%M")
    if metrics.t_out is None:
        outlook = f"앞으로 {STOCKOUT_HORIZON_WEEKS}주 안에는 다 쓰지 않을 것으로 보여요."
    else:
        outlook = f"소진 예상일은 {metrics.t_out:%m/%d}이에요."
    return f"{reply} {outlook} (재고 기준 {at}, 예상 계산 {computed})"
