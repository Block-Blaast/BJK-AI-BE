"""체크 9개 (F-REVIEW-04). 데이터가 없는 체크는 건너뛴다."""

from dataclasses import dataclass
from datetime import date, timedelta

from bjk_contracts import CheckCode, CheckLevel

from bjk_review.models import Check, ReviewSettings, ReviewSnapshot, SupplierOffer
from bjk_review.pricing import ceil_to_moq, unit_price_at

# C-08 원인. 요청 공급사 납기 때문이면 수정안이 공급사를 바꾼다(F-REVIEW-05 2번).
C08_DEADLINE = "deadline"
C08_SUPPLIER_LEAD = "supplier_lead"


@dataclass(frozen=True)
class Context:
    """체크와 수정안이 함께 쓰는 원안 해석 결과."""

    snapshot: ReviewSnapshot
    settings: ReviewSettings
    qty: int  # Q
    offer: SupplierOffer  # 요청 공급사(없으면 기본 공급사)
    unit_price: int  # 요청 단가(없으면 그 공급사 단가)
    quoted: bool  # 요청에 단가가 있었는지. 없으면 수량이 바뀔 때 단가 구간을 다시 본다

    @property
    def today(self) -> date:
        return self.snapshot.as_of

    @property
    def t_need(self) -> date | None:
        return self.snapshot.t_out

    def arrives_in_time(self, offer: SupplierOffer) -> bool:
        return self.t_need is None or self.today + timedelta(days=offer.lt90) <= self.t_need


def _number(value: float) -> int | float:
    value = round(value, 1)
    return int(value) if value == int(value) else value


def c01_over_quantity(ctx: Context) -> Check | None:
    s = ctx.snapshot
    over = s.stock + s.incoming + s.hidden_confirmed + ctx.qty - s.d99
    if over <= ctx.offer.moq:
        return None
    return Check(
        code=CheckCode.C01,
        level=CheckLevel.WARNING,
        facts={
            "S": s.stock,
            "O": s.incoming,
            "H_c": s.hidden_confirmed,
            "Q": ctx.qty,
            "D99": s.d99,
            "MOQ": ctx.offer.moq,
        },
    )


def c02_long_term_stock(ctx: Context) -> Check | None:
    s = ctx.snapshot
    if ctx.qty <= 0:
        return None
    monthly = s.m + s.f_12m / 12
    facts = {"Q": ctx.qty, "m": _number(s.m), "F_12m": s.f_12m}
    if monthly <= 0:
        # 사용 기록·정비 수요가 모두 없으면 "최근 사용 기록 없음"으로 건다.
        return Check(
            code=CheckCode.C02,
            level=CheckLevel.WARNING,
            facts={**facts, "months": None, "note": "no_recent_usage"},
        )
    months = ctx.qty / monthly
    if months <= ctx.settings.c02_months:
        return None
    return Check(
        code=CheckCode.C02, level=CheckLevel.WARNING, facts={**facts, "months": _number(months)}
    )


def c03_duplicate_order(ctx: Context) -> Check | None:
    s = ctx.snapshot
    if not s.open_orders and not s.open_requests:
        return None
    facts: dict[str, int | float | str | None] = {}
    if s.open_orders:
        facts["incoming_qty"] = sum(o.qty for o in s.open_orders)
        etas = [o.eta for o in s.open_orders if o.eta is not None]
        facts["eta"] = min(etas).isoformat() if etas else None
    if s.open_requests:
        facts["open_request_qty"] = s.other_requests
    return Check(code=CheckCode.C03, level=CheckLevel.WARNING, facts=facts)


def c04_hidden_stock(ctx: Context) -> Check | None:
    s = ctx.snapshot
    if s.hidden_confirmed + s.hidden_unconfirmed <= 0:
        return None
    return Check(
        code=CheckCode.C04,
        level=CheckLevel.WARNING,
        facts={"H_c": s.hidden_confirmed, "H_u": s.hidden_unconfirmed},
    )


def c05_price_anomaly(ctx: Context) -> Check | None:
    stats, settings = ctx.snapshot.price_stats, ctx.settings
    if stats.n == 0 or stats.mean is None:
        return None
    if stats.n >= 3:
        hit = (
            ctx.unit_price > stats.mean + settings.c05_sigma * stats.sigma
            and ctx.unit_price > stats.mean * settings.c05_min_ratio
        )
    else:
        hit = ctx.unit_price > stats.mean * settings.c05_small_n_ratio
    if not hit:
        return None
    return Check(
        code=CheckCode.C05,
        level=CheckLevel.WARNING,
        facts={
            "unit_price": ctx.unit_price,
            "p_mean": _number(stats.mean),
            "sigma": _number(stats.sigma),
            "n": stats.n,
        },
    )


def cheaper_supplier(ctx: Context) -> tuple[SupplierOffer, int] | None:
    """C-06 조건을 만족하는 공급사 중 단가가 가장 낮은 곳과 그 단가."""
    found: list[tuple[int, str, SupplierOffer]] = []
    for offer in ctx.snapshot.suppliers:
        if offer.supplier_id == ctx.offer.supplier_id or not ctx.arrives_in_time(offer):
            continue
        price = unit_price_at(offer, ceil_to_moq(ctx.qty, offer.moq))
        if price <= ctx.unit_price * ctx.settings.c06_ratio:
            found.append((price, offer.supplier_id, offer))
    if not found:
        return None
    price, _, offer = min(found, key=lambda f: (f[0], f[1]))
    return offer, price


def c06_cheaper_supplier(ctx: Context) -> Check | None:
    if ctx.qty <= 0:
        return None
    found = cheaper_supplier(ctx)
    if found is None:
        return None
    offer, price = found
    return Check(
        code=CheckCode.C06,
        level=CheckLevel.INFO,
        facts={"supplier": offer.name, "unit_price": price, "LT90": offer.lt90},
    )


def c07_short_quantity(ctx: Context) -> Check | None:
    s = ctx.snapshot
    covered = s.stock + s.incoming + s.hidden_confirmed + s.other_requests + ctx.qty
    if covered >= s.d95:
        return None
    return Check(
        code=CheckCode.C07,
        level=CheckLevel.WARNING,
        facts={
            "S": s.stock,
            "O": s.incoming,
            "H_c": s.hidden_confirmed,
            "P": s.other_requests,
            "Q": ctx.qty,
            "D95": s.d95,
        },
    )


def c08_causes(ctx: Context) -> list[str]:
    """마감 5일 이내(지났으면 무조건)와 요청 공급사 납기 부족은 따로 판단한다."""
    s = ctx.snapshot
    causes = []
    if s.t_deadline is not None and (s.t_deadline - ctx.today).days <= ctx.settings.c08_days:
        causes.append(C08_DEADLINE)
    if not ctx.arrives_in_time(ctx.offer):
        causes.append(C08_SUPPLIER_LEAD)
    return causes


def c08_deadline(ctx: Context) -> Check | None:
    causes = c08_causes(ctx)
    if not causes:
        return None
    s = ctx.snapshot
    facts: dict[str, int | float | str | None] = {"cause": ",".join(causes)}
    if s.t_deadline is not None:
        facts["deadline"] = s.t_deadline.isoformat()
        facts["days_left"] = (s.t_deadline - ctx.today).days
    if s.t_out is not None:
        facts["t_need"] = s.t_out.isoformat()
    facts["LT90"] = ctx.offer.lt90
    return Check(code=CheckCode.C08, level=CheckLevel.URGENT, facts=facts)


def c09_external_risk(ctx: Context) -> Check | None:
    s = ctx.snapshot
    risky = s.import_dependent and (s.r_lead >= 1 or s.r_price >= 1)
    if not risky and not s.holidays_in_lead:
        return None
    facts: dict[str, int | float | str | None] = {
        "r_lead": _number(s.r_lead),
        "r_price": _number(s.r_price),
    }
    if s.holidays_in_lead:
        facts["holiday"] = ", ".join(s.holidays_in_lead)
    return Check(code=CheckCode.C09, level=CheckLevel.INFO, facts=facts)


CHECKS = (
    c01_over_quantity,
    c02_long_term_stock,
    c03_duplicate_order,
    c04_hidden_stock,
    c05_price_anomaly,
    c06_cheaper_supplier,
    c07_short_quantity,
    c08_deadline,
    c09_external_risk,
)


def run_checks(ctx: Context) -> list[Check]:
    return [check for run in CHECKS if (check := run(ctx)) is not None]
