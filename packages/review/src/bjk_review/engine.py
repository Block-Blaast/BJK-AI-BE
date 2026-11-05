"""발주 검토 판정 (F-REVIEW-03~06). 보류 판단 → 체크 9개 → 수정안 → 판정·표시."""

import hashlib
import json

from bjk_contracts import CheckCode, CheckLevel, Flag, HoldReason, Verdict

from bjk_review.checks import C08_SUPPLIER_LEAD, Context, c08_causes, cheaper_supplier, run_checks
from bjk_review.models import (
    AlternativeLine,
    Check,
    CountRequest,
    Line,
    OrderRequest,
    ProposalLine,
    ReviewResult,
    ReviewSettings,
    ReviewSnapshot,
    RiskIfNotOrdered,
    SupplierOffer,
)
from bjk_review.pricing import ceil_to_moq, landed_cost, unit_price_at

QUANTITY_CHECKS = (CheckCode.C01, CheckCode.C02, CheckCode.C03, CheckCode.C04, CheckCode.C07)


def review_hash(snapshot: ReviewSnapshot, request: OrderRequest, settings: ReviewSettings) -> str:
    """같은 입력이면 같은 값. 재검토 미리 보기(`recheck_hash`)와 결정 시 대조에 쓴다."""
    payload = {
        "snapshot": snapshot.model_dump(mode="json"),
        "request": request.model_dump(mode="json"),
        "settings": settings.model_dump(mode="json"),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def hold_reasons(snapshot: ReviewSnapshot, request: OrderRequest) -> list[HoldReason]:
    """F-REVIEW-03. 하나라도 있으면 체크를 돌리지 않고 보류한다."""
    reasons = []
    if snapshot.part_id is None:
        reasons.append(HoldReason.PART_UNRESOLVED)
    if snapshot.offer(request.supplier_id or snapshot.default_supplier_id) is None:
        reasons.append(HoldReason.SUPPLIER_UNRESOLVED)
    if not (
        snapshot.has_usage_history or snapshot.has_maintenance_plan or snapshot.has_usage_estimate
    ):
        reasons.append(HoldReason.NO_DEMAND_DATA)
    return reasons


def _line(qty: int, offer: SupplierOffer | None, unit_price: int | None) -> Line:
    return Line(
        qty=qty,
        supplier_id=offer.supplier_id if offer else None,
        supplier_name=offer.name if offer else None,
        unit_price=unit_price,
        total=qty * unit_price if unit_price is not None else 0,
    )


def _risk(snapshot: ReviewSnapshot) -> RiskIfNotOrdered:
    return RiskIfNotOrdered(
        stockout_date=snapshot.t_out,
        equipment=snapshot.loss_equipment,
        loss=snapshot.loss,
        is_estimate=snapshot.loss_is_estimate,
    )


def recommended_qty(ctx: Context) -> int:
    """R = max(0, D95 − S − O − H_c − P)를 요청 공급사 MOQ 배수로 올림. H_u는 빼지 않는다."""
    s = ctx.snapshot
    shortage = s.d95 - s.stock - s.incoming - s.hidden_confirmed - s.other_requests
    return ceil_to_moq(max(0, shortage), ctx.offer.moq)


def _cheapest_in_time(ctx: Context, qty: int) -> tuple[SupplierOffer, int, int, int] | None:
    """t_need를 맞추는 공급사 중 배송비 포함 총액 최저. (공급사, 수량, 단가, 총액)"""
    options = []
    for offer in ctx.snapshot.suppliers:
        if ctx.arrives_in_time(offer):
            q, price, cost = landed_cost(offer, qty)
            options.append((cost, offer.supplier_id, offer, q, price))
    if not options:
        return None
    cost, _, offer, q, price = min(options, key=lambda o: (o[0], o[1]))
    return offer, q, price, cost


def _fastest(ctx: Context, qty: int) -> tuple[SupplierOffer, int, int]:
    offer = min(
        ctx.snapshot.suppliers,
        key=lambda o: (o.lt90, landed_cost(o, qty)[2], o.supplier_id),
    )
    q, price, _ = landed_cost(offer, qty)
    return offer, q, price


def build_proposal(ctx: Context, checks: list[Check], original: Line) -> ProposalLine:
    """F-REVIEW-05. 모든 변경은 걸린 체크 하나 이상에 근거한다(`basis`)."""
    fired = {c.code for c in checks}
    basis: list[CheckCode] = []

    # 1. 수량: 수량 관련 체크가 하나라도 걸리면 R
    qty_checks = [code for code in QUANTITY_CHECKS if code in fired]
    qty = recommended_qty(ctx) if qty_checks else ctx.qty
    offer, price = ctx.offer, ctx.unit_price
    if qty != ctx.qty:
        basis += qty_checks
        if not ctx.quoted:
            price = unit_price_at(offer, qty)

    # 2. 공급사·단가: C-08(요청 공급사 납기 부족) 또는 C-05일 때만 바꾼다. C-06만이면 바꾸지 않음
    lead_short = CheckCode.C08 in fired and C08_SUPPLIER_LEAD in c08_causes(ctx)
    if qty > 0 and lead_short:
        best = _cheapest_in_time(ctx, qty)
        new_offer, new_qty, new_price = best[:3] if best else _fastest(ctx, qty)
        if new_offer.supplier_id != offer.supplier_id:
            offer, qty, price = new_offer, new_qty, new_price
            basis.append(CheckCode.C08)
    elif qty > 0 and CheckCode.C05 in fired:
        best = _cheapest_in_time(ctx, qty)
        current_cost = qty * price + offer.shipping_fee
        if (
            best is not None
            and best[0].supplier_id != offer.supplier_id
            and best[3] <= current_cost * ctx.settings.c06_ratio
        ):
            offer, qty, price = best[0], best[1], best[2]
            basis.append(CheckCode.C05)

    if qty == 0:
        line = _line(0, None, None)
    else:
        line = _line(qty, offer, price)
    return ProposalLine(
        **line.model_dump(),
        saving=original.total - line.total,
        no_order=qty == 0,
        basis=sorted(basis),
    )


def build_alternatives(
    ctx: Context, checks: list[Check], proposal: ProposalLine
) -> list[AlternativeLine]:
    """판정과 관계없는 대안. 더 싼 공급사(C-06)와 다음 단가 구간."""
    if proposal.no_order or proposal.supplier_id is None or proposal.unit_price is None:
        return []
    s = ctx.snapshot
    alternatives = []

    found = cheaper_supplier(ctx) if any(c.code == CheckCode.C06 for c in checks) else None
    if found is not None and found[0].supplier_id != proposal.supplier_id:
        offer = found[0]
        qty = ceil_to_moq(proposal.qty, offer.moq)
        price = unit_price_at(offer, qty)
        if qty * price < proposal.total:
            alternatives.append(_alternative("cheaper_supplier", offer, qty, price, proposal))

    offer = s.offer(proposal.supplier_id)
    next_tiers = sorted(t.min_qty for t in offer.price_tiers if t.min_qty > proposal.qty)
    if next_tiers:
        qty = next_tiers[0]
        price = unit_price_at(offer, qty)
        within_cost = qty * price <= proposal.total * (1 + ctx.settings.tier_max_increase)
        held = s.stock + s.incoming + s.hidden_confirmed + s.other_requests + qty
        if within_cost and held <= s.d99:
            alternatives.append(_alternative("price_tier", offer, qty, price, proposal))
    return alternatives


def _alternative(kind, offer: SupplierOffer, qty: int, price: int, proposal: ProposalLine):
    return AlternativeLine(
        id=f"{kind}:{offer.supplier_id}:{qty}",
        kind=kind,
        **_line(qty, offer, price).model_dump(),
        saving=proposal.total - qty * price,
    )


def build_flags(
    snapshot: ReviewSnapshot,
    checks: list[Check],
    proposal: ProposalLine,
    alternatives: list[AlternativeLine],
) -> list[Flag]:
    """F-REVIEW-06 표시. 긴급은 C-08 하나뿐이다.

    주의: 미확인 숨은 재고가 있거나, 발주를 하는데 수정안으로 풀지 못한 경고가 남은 경우
    (예: 단가는 높은데 더 싼 공급사가 없음).
    """
    flags = []
    if any(c.code == CheckCode.C08 for c in checks):
        flags.append(Flag.URGENT)
    unresolved = [
        c for c in checks if c.level == CheckLevel.WARNING and c.code not in proposal.basis
    ]
    if snapshot.hidden_unconfirmed > 0 or (not proposal.no_order and unresolved):
        flags.append(Flag.CAUTION)
    if alternatives:
        flags.append(Flag.ALTERNATIVE)
    return flags


def hold_result(
    snapshot: ReviewSnapshot,
    request: OrderRequest,
    settings: ReviewSettings,
    reasons: list[HoldReason],
) -> ReviewResult:
    """보류. 체크·수정안 없이 사유만 담는다(F-REVIEW-03)."""
    offer = snapshot.offer(request.supplier_id or snapshot.default_supplier_id)
    return ReviewResult(
        verdict=Verdict.HOLD,
        flags=[],
        hold_reasons=reasons,
        checks=[],
        original=_line(request.qty, offer, request.unit_price),
        proposal=None,
        alternatives=[],
        risk_if_not_ordered=_risk(snapshot),
        count_requests=[],
        review_hash=review_hash(snapshot, request, settings),
    )


def make_context(
    snapshot: ReviewSnapshot, request: OrderRequest, settings: ReviewSettings
) -> Context:
    """원안 해석. 보류가 아닐 때만 부른다(공급사가 정해져 있어야 함)."""
    offer = snapshot.offer(request.supplier_id or snapshot.default_supplier_id)
    unit_price = (
        request.unit_price
        if request.unit_price is not None
        else unit_price_at(offer, ceil_to_moq(request.qty, offer.moq))
    )
    return Context(
        snapshot=snapshot,
        settings=settings,
        qty=request.qty,
        offer=offer,
        unit_price=unit_price,
        quoted=request.unit_price is not None,
    )


def original_line(ctx: Context) -> Line:
    return _line(ctx.qty, ctx.offer, ctx.unit_price)


def decide(
    ctx: Context,
    request: OrderRequest,
    checks: list[Check],
    proposal: ProposalLine,
    alternatives: list[AlternativeLine],
) -> ReviewResult:
    """판정·표시 (F-REVIEW-06). 판정은 수정안이 원안과 다른가로 정한다."""
    s = ctx.snapshot
    original = original_line(ctx)
    changed = (proposal.qty, proposal.supplier_id, proposal.unit_price) != (
        original.qty,
        original.supplier_id,
        original.unit_price,
    )
    return ReviewResult(
        verdict=Verdict.REVISE if changed else Verdict.OK,
        flags=build_flags(s, checks, proposal, alternatives),
        hold_reasons=[],
        checks=checks,
        original=original,
        proposal=proposal,
        alternatives=alternatives,
        risk_if_not_ordered=_risk(s),
        count_requests=[
            CountRequest(part_id=h.part_id, name=h.name) for h in s.hidden if not h.confirmed
        ],
        review_hash=review_hash(s, request, ctx.settings),
    )


def run_review(
    snapshot: ReviewSnapshot, request: OrderRequest, settings: ReviewSettings | None = None
) -> ReviewResult:
    """보류 판단 → 체크 → 수정안 → 판정을 한 번에.

    검토 그래프(`graph.py`)도 같은 단계 함수를 쓴다.
    """
    settings = settings or ReviewSettings()
    reasons = hold_reasons(snapshot, request)
    if reasons:
        return hold_result(snapshot, request, settings, reasons)
    ctx = make_context(snapshot, request, settings)
    checks = run_checks(ctx)
    proposal = build_proposal(ctx, checks, original_line(ctx))
    alternatives = build_alternatives(ctx, checks, proposal)
    return decide(ctx, request, checks, proposal, alternatives)
