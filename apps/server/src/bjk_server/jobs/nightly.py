"""새벽 배치 (매일 03:00): 외부 지표 위험도 → 부품 근거 지표 → 장부 검증 → 빈 임베딩 채우기.

기능명세서 F-EXT-02, F-ANAL, F-AUDIT, F-SETUP-02 5단계. 재고 요약 대조(F-LEDGER-02)는 요약 도입 시
더한다.
"""

import csv
import math
import uuid
from collections import defaultdict
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.orm import Session

from bjk_server.ai.client import get_ai_client
from bjk_server.ai.embeddings import fill_missing
from bjk_server.audit.flags import audit_company
from bjk_server.auth import set_tenant
from bjk_server.clock import KST
from bjk_server.db.models import (
    AuditFlag,
    CalendarEvent,
    Category,
    CompanySettings,
    CountRequest,
    Equipment,
    EquipmentPart,
    ExternalIndicator,
    Maintenance,
    Movement,
    Part,
    PartMetrics,
    PartSupplierMetrics,
    PurchaseOrder,
    Supplier,
    SupplierPart,
)
from bjk_server.defaults import default_settings
from bjk_server.domain import analytics as an
from bjk_server.domain import hidden_stock as hs
from bjk_server.domain import purchase_order as po
from bjk_server.domain.external import (
    apply_shock,
    extend_for_holidays,
    indicator_risk,
    risk_level,
)
from bjk_server.inventory import merged_owners
from bjk_server.jobs.runner import company_ids, job
from bjk_server.purchasing.orders import open_qty

INDICATOR_CSV = Path(__file__).resolve().parents[1] / "seed" / "data" / "external_indicators.csv"
# 지표 코드 → (이름, 계열). 카테고리의 lead_factors·price_factors가 이 코드를 가리킨다.
INDICATORS = {
    "FREIGHT": ("컨테이너 운임지수", "lead"),
    "USDKRW": ("원/달러 환율", "price"),
}
FALLBACK_LEAD_DAYS = 7  # 공급사도 기본 납기도 없을 때
HISTORY_WEEKS = 52
IMPORT_DEPENDENT = ("high", "medium")
# 카테고리 납기 요인 → 연휴 캘린더 범위
HOLIDAY_FACTORS = {"HOLIDAY_KR": "KR", "HOLIDAY_CN": "CN"}
# 납기 계산에 읽어 둘 연휴 기간 (납기 최대 2배 + 다음 발주 기간보다 넉넉히)
CALENDAR_HORIZON_DAYS = 365


def load_indicators(session: Session, path: Path = INDICATOR_CSV) -> dict[str, float]:
    """CSV 지표를 적재하고 지표별 최신 위험도 r을 돌려준다. 파일이 없으면 직전 값을 유지한다."""
    if path.exists():
        series: dict[str, list[tuple[date, float]]] = defaultdict(list)
        with path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row["code"] in INDICATORS:
                    series[row["code"]].append(
                        (date.fromisoformat(row["as_of"]), float(row["value"]))
                    )
        for code, points in series.items():
            points.sort()
            name, kind = INDICATORS[code]
            values = [v for _, v in points]
            for i, (as_of, value) in enumerate(points):
                z, r = indicator_risk(values[: i + 1])
                stmt = insert(ExternalIndicator).values(
                    code=code,
                    name=name,
                    series=kind,
                    as_of=as_of,
                    value=value,
                    z=z,
                    r=r,
                    level=risk_level(r),
                )
                session.execute(
                    stmt.on_conflict_do_update(
                        index_elements=[ExternalIndicator.code, ExternalIndicator.as_of],
                        set_={
                            "value": value,
                            "z": z,
                            "r": r,
                            "level": risk_level(r),
                            "updated_at": func.now(),
                        },
                    )
                )
    return latest_risks(session)


def latest_risks(session: Session) -> dict[str, float]:
    """지표별 최신 위험도 r."""
    latest = (
        select(ExternalIndicator.code, ExternalIndicator.r)
        .ext(distinct_on(ExternalIndicator.code))
        .order_by(ExternalIndicator.code, ExternalIndicator.as_of.desc())
    )
    return {code: r for code, r in session.execute(latest)}


def shock_enabled(settings_row: CompanySettings | None) -> bool:
    return bool(settings_row and settings_row.scenarios.get("external_shock"))


@dataclass(frozen=True)
class SupplierTerms:
    supplier_id: uuid.UUID
    unit_price: int
    moq: int
    base_lead_days: int
    holidays: tuple[date, ...]


def lead_time(
    terms: SupplierTerms | None,
    import_dependent: bool,
    r_lead: float,
    k: float,
    today: date,
    holidays: Collection[date] = (),
) -> int:
    """납기 표본이 없을 때의 납기 (F-ANAL-04, F-EXT-02).

    기본 납기 × (1 + k × r_lead, 수입 의존 부품만)에 납기 구간과 겹치는 연휴를 더한다.
    연휴는 공급사 휴무일과 holidays(카테고리 납기 요인의 명절 캘린더)를 합친다.
    """
    base = terms.base_lead_days if terms else FALLBACK_LEAD_DAYS
    days = math.ceil(base * (1 + k * r_lead) if import_dependent else base)
    off = {*holidays, *(terms.holidays if terms else ())}
    return extend_for_holidays(today, days, off)


def _weekly(outs: list[tuple[date, int]], start: date, today: date) -> np.ndarray:
    weeks = max(0, min(HISTORY_WEEKS, (today - start).days // 7))
    buckets = np.zeros(weeks)
    for day, qty in outs:
        index = weeks - 1 - (today - day).days // 7
        if 0 <= index < weeks:
            buckets[index] += qty
    return buckets


def compute_company(
    session: Session, company_id: uuid.UUID, now: datetime, r_by_code: dict[str, float]
) -> int:
    today = now.astimezone(KST).date()
    set_tenant(session, company_id)
    settings_row = session.get(CompanySettings, company_id)
    settings = (
        {"review": settings_row.review, "system": settings_row.system}
        if settings_row
        else default_settings()
    )
    r_by_code = apply_shock(r_by_code, shock_enabled(settings_row))
    service_level = settings["review"]["service_level"]
    next_order_days = settings["review"]["next_order_weeks"] * 7
    k = settings["system"]["external_k"]
    count_days = settings["system"]["hidden_stock_count_days"]

    parts = session.scalars(
        select(Part).where(Part.company_id == company_id, Part.merged_into.is_(None))
    ).all()
    categories = {
        c.id: c for c in session.scalars(select(Category).where(Category.company_id == company_id))
    }
    suppliers = {
        s.id: s for s in session.scalars(select(Supplier).where(Supplier.company_id == company_id))
    }
    # 연휴 캘린더: 국내·중국 명절은 카테고리 납기 요인으로, 공급사 휴무는 그 공급사 납기에 반영
    region_days: dict[str, set[date]] = defaultdict(set)
    supplier_days: dict[uuid.UUID, set[date]] = defaultdict(set)
    horizon = today + timedelta(days=CALENDAR_HORIZON_DAYS)
    for event in session.scalars(
        select(CalendarEvent).where(
            CalendarEvent.company_id == company_id,
            CalendarEvent.end_date > today,
            CalendarEvent.start_date <= horizon,
        )
    ):
        days = {
            event.start_date + timedelta(days=i)
            for i in range((event.end_date - event.start_date).days + 1)
        }
        if event.scope == "supplier":
            supplier_days[event.supplier_id] |= days
        else:
            region_days[event.scope] |= days
    terms_by_part: dict[uuid.UUID, dict[uuid.UUID, SupplierTerms]] = defaultdict(dict)
    for sp in session.scalars(select(SupplierPart).where(SupplierPart.company_id == company_id)):
        supplier = suppliers[sp.supplier_id]
        terms_by_part[sp.part_id][sp.supplier_id] = SupplierTerms(
            sp.supplier_id,
            sp.unit_price,
            sp.moq,
            supplier.default_lead_time_days or FALLBACK_LEAD_DAYS,
            tuple(sorted({*(supplier.holidays or ()), *supplier_days[sp.supplier_id]})),
        )

    # 병합된 부품의 원장·발주는 흡수된 부품 id로 남아 있다. 대표 부품으로 합산한다(F-LEDGER-02).
    owners = merged_owners(session, company_id)

    def owner(part_id: uuid.UUID) -> uuid.UUID:
        return owners.get(part_id, part_id)

    stock: dict[uuid.UUID, int] = defaultdict(int)
    for part_id, qty in session.execute(
        select(Movement.part_id, func.sum(Movement.qty))
        .where(Movement.company_id == company_id)
        .group_by(Movement.part_id)
    ):
        stock[owner(part_id)] += int(qty)
    # 숨은 재고 확인 여부 (F-MATCH-03): 마지막 실사 응답 시각, 열린 장부 의심 항목
    last_counted = dict(
        session.execute(
            select(CountRequest.part_id, func.max(CountRequest.answered_at))
            .where(CountRequest.company_id == company_id, CountRequest.answered_at <= now)
            .group_by(CountRequest.part_id)
        ).all()
    )
    suspect = set(
        session.scalars(
            select(AuditFlag.part_id).where(
                AuditFlag.company_id == company_id, AuditFlag.status != "closed"
            )
        )
    )
    first_seen: dict[uuid.UUID, datetime] = {}
    for part_id, seen in session.execute(
        select(Movement.part_id, func.min(Movement.occurred_at))
        .where(Movement.company_id == company_id)
        .group_by(Movement.part_id)
    ):
        key = owner(part_id)
        first_seen[key] = min(seen, first_seen.get(key, seen))
    # 통계 예측 입력: 정비에 연결되지 않은 출고만 (F-ANAL-03)
    outs: dict[uuid.UUID, list[tuple[date, int]]] = defaultdict(list)
    usage_qty: dict[uuid.UUID, float] = defaultdict(float)
    year_ago = now - timedelta(days=365)
    for part_id, occurred_at, qty, maintenance_id in session.execute(
        select(Movement.part_id, Movement.occurred_at, Movement.qty, Movement.maintenance_id).where(
            Movement.company_id == company_id, Movement.type == "OUT"
        )
    ):
        if maintenance_id is None:
            outs[owner(part_id)].append((occurred_at.astimezone(KST).date(), -qty))
        if occurred_at >= year_ago:
            usage_qty[owner(part_id)] += -qty

    equipment = {
        e.id: e
        for e in session.scalars(select(Equipment).where(Equipment.company_id == company_id))
    }
    links: dict[uuid.UUID, list[EquipmentPart]] = defaultdict(list)
    per_maintenance: dict[tuple[uuid.UUID, uuid.UUID], int] = {}
    for link in session.scalars(
        select(EquipmentPart).where(EquipmentPart.company_id == company_id)
    ):
        links[link.part_id].append(link)
        per_maintenance[(link.equipment_id, link.part_id)] = link.qty_per_maintenance
    upcoming = session.scalars(
        select(Maintenance).where(
            Maintenance.company_id == company_id,
            Maintenance.completed_at.is_(None),
            Maintenance.scheduled_date >= today,
        )
    ).all()

    def default_terms(part: Part) -> SupplierTerms | None:
        options = terms_by_part.get(part.id, {})
        if part.default_supplier_id in options:
            return options[part.default_supplier_id]
        return min(options.values(), key=lambda t: t.unit_price, default=None)

    # 실제 납기 표본: 주문 완료 → 입고 완료 일수. 주문 완료 표시 없이 입고된 건은 뺀다 (F-LEDGER-04)
    lead_by_pair: dict[tuple[uuid.UUID, uuid.UUID], list[int]] = defaultdict(list)
    lead_by_supplier: dict[uuid.UUID, list[int]] = defaultdict(list)
    for part_id, supplier_id, ordered_at, received_at in session.execute(
        select(
            PurchaseOrder.part_id,
            PurchaseOrder.supplier_id,
            PurchaseOrder.ordered_at,
            PurchaseOrder.received_at,
        ).where(
            PurchaseOrder.company_id == company_id,
            PurchaseOrder.status == "received",
            PurchaseOrder.implicit_order.is_(False),
            PurchaseOrder.ordered_at.is_not(None),
            PurchaseOrder.received_at <= now,
        )
    ):
        days = max(0, (received_at - ordered_at).days)
        lead_by_pair[(owner(part_id), supplier_id)].append(days)
        lead_by_supplier[supplier_id].append(days)
    # 입고 예정 O: 열린 발주(승인됨·발주됨·부분입고)의 미입고 수량 (F-ANAL-09)
    incoming: dict[uuid.UUID, int] = defaultdict(int)
    for part_id, qty in open_qty(session, [p.id for p in parts] + list(owners)).items():
        incoming[owner(part_id)] += qty

    priced = all(default_terms(p) for p in parts)
    usage = {p.id: usage_qty[p.id] * (default_terms(p).unit_price if priced else 1) for p in parts}
    abc = an.abc_classes(usage)

    def maintenance_needs(part_id: uuid.UUID, horizon: int) -> list[dict[str, Any]]:
        """기간 안 확정 필요량 F (F-SETUP-04).

        정비 일정에 필요 부품이 있으면 그것, 없으면 설비의 정비 1회당 수량. 둘을 더하지 않는다.
        """
        items = []
        for m in upcoming:
            offset = (m.scheduled_date - today).days
            if offset > horizon:
                continue
            if m.required_parts is not None:
                qty = sum(int(r["qty"]) for r in m.required_parts if r["part_id"] == str(part_id))
            else:
                qty = per_maintenance.get((m.equipment_id, part_id), 0)
            if qty:
                items.append(
                    {
                        "maintenance_id": str(m.id),
                        "equipment": equipment[m.equipment_id].name,
                        "date": m.scheduled_date.isoformat(),
                        "qty": qty,
                        "offset": offset,
                    }
                )
        return items

    computed = 0
    session.execute(
        delete(PartMetrics).where(
            PartMetrics.company_id == company_id, PartMetrics.computed_on == today
        )
    )
    session.execute(
        delete(PartSupplierMetrics).where(
            PartSupplierMetrics.company_id == company_id, PartSupplierMetrics.computed_on == today
        )
    )
    for part in parts:
        rng = np.random.default_rng(an.seed_for(company_id, part.id, today))
        category = categories.get(part.category_id)
        dependency = part.import_override or (category.import_dependency if category else "low")
        import_dependent = dependency in IMPORT_DEPENDENT
        r_lead = max(
            (r_by_code.get(c, 0.0) for c in (category.lead_factors if category else [])),
            default=0.0,
        )
        r_price = max(
            (r_by_code.get(c, 0.0) for c in (category.price_factors if category else [])),
            default=0.0,
        )

        festive = {
            day
            for factor in (category.lead_factors if category else [])
            if factor in HOLIDAY_FACTORS
            for day in region_days[HOLIDAY_FACTORS[factor]]
        }
        # 공급사별 (LT50, LT90, 표본 수). 실제 납기 표본이 없으면 기본 납기 하나로 둘 다 쓴다.
        lead: dict[uuid.UUID, tuple[int, int, int]] = {}
        for sid, t in terms_by_part[part.id].items():
            samples = po.lead_time_samples(lead_by_pair[(part.id, sid)], lead_by_supplier[sid])
            if samples:
                off = {*festive, *t.holidays}
                q50, q90 = po.lead_quantiles(samples, import_dependent, r_lead, k)
                lead[sid] = (
                    extend_for_holidays(today, q50, off),
                    extend_for_holidays(today, q90, off),
                    len(samples),
                )
            else:
                base = lead_time(t, import_dependent, r_lead, k, today, festive)
                lead[sid] = (base, base, 0)
        for sid, t in terms_by_part[part.id].items():
            session.add(
                PartSupplierMetrics(
                    company_id=company_id,
                    part_id=part.id,
                    supplier_id=sid,
                    computed_on=today,
                    computed_at=now,
                    lt50=lead[sid][0],
                    lt90=lead[sid][1],
                    samples=lead[sid][2],
                    unit_price=t.unit_price,
                    moq=t.moq,
                )
            )
        terms = default_terms(part)
        if terms:
            lt50, lt, _ = lead[terms.supplier_id]
        else:
            lt50 = lt = lead_time(None, import_dependent, r_lead, k, today, festive)
        # lt는 기본 공급사 LT90: 대비 기간 T, 재주문점, 발주 마감일에 쓴다.
        # LT50은 다음 입고 가능일(결품 확률)과 예상 손실에 쓴다.
        period = lt + next_order_days

        start = first_seen.get(part.id)
        weekly = (
            _weekly(outs[part.id], start.astimezone(KST).date(), today) if start else np.zeros(0)
        )
        demand_class = an.classify(weekly)
        statistical = demand_class != "insufficient"
        forecast = (
            an.forecast_weekly(weekly, demand_class)
            if statistical
            else (part.monthly_estimate or 0) * 12 / 52
        )

        f_period = maintenance_needs(part.id, period)
        f_lead = [f for f in f_period if f["offset"] <= lt]
        f_total, f_lead_total = sum(f["qty"] for f in f_period), sum(f["qty"] for f in f_lead)
        if statistical:
            period_samples = an.bootstrap_demand(weekly, period, rng)
            lead_samples = an.bootstrap_demand(weekly, lt, rng)
            weekly_samples = weekly
        else:
            period_samples = an.poisson_demand(part.monthly_estimate, period, rng)
            lead_samples = an.poisson_demand(part.monthly_estimate, lt, rng)
            weekly_samples = an.poisson_demand(part.monthly_estimate, 7, rng, n=1000)
        d95 = an.upper_quantile(period_samples, 0.95, f_total)
        d99 = an.upper_quantile(period_samples, 0.99, f_total)
        reorder_point = an.upper_quantile(lead_samples, service_level[abc[part.id]], f_lead_total)

        s = int(stock.get(part.id, 0))
        hidden = hs.split_hidden(
            (
                hs.HiddenPart(
                    o.id, int(stock.get(o.id, 0)), last_counted.get(o.id), o.id in suspect
                )
                for o in parts
                if o.id != part.id
                and hs.same_spec(part.category_id, part.spec, o.category_id, o.spec)
            ),
            now,
            count_days,
        )
        h_c, h_u = hidden.h_c, hidden.h_u
        paths = an.simulate_paths(
            s + h_c,
            weekly_samples,
            [(f["offset"], f["qty"]) for f in maintenance_needs(part.id, 56)],
            lt50,
            rng,
        )
        t_out = today + timedelta(days=paths.t_out_day) if paths.t_out_day is not None else None

        linked = [equipment[link.equipment_id] for link in links[part.id]]
        loss = an.expected_loss([(e.loss_per_hour, e.operating_hours) for e in linked], lt50)
        session.add(
            PartMetrics(
                company_id=company_id,
                part_id=part.id,
                computed_on=today,
                computed_at=now,
                abc=abc[part.id],
                abc_basis="amount" if priced else "qty",
                demand_class=demand_class,
                data_mode="statistical" if statistical else "estimated",
                forecast_weekly=round(forecast, 4),
                m=round(forecast * 52 / 12, 4),
                f_items=[{k_: v for k_, v in f.items() if k_ != "offset"} for f in f_period],
                default_supplier_id=terms.supplier_id if terms else None,
                lt50=lt50,
                lt90=lt,
                period_days=period,
                d95=d95,
                d99=d99,
                reorder_point=reorder_point,
                stock=s,
                hidden_confirmed=h_c,
                hidden_unconfirmed=h_u,
                t_out=t_out,
                t_deadline=t_out - timedelta(days=lt) if t_out else None,
                p_out=round(paths.p_out, 4),
                loss=loss,
                loss_equipment=[e.name for e in linked],
                loss_is_estimate=any(e.loss_is_estimate for e in linked),
                priority=round(paths.p_out * loss, 2),
                recommended_qty=an.recommended_qty(
                    d95, s, incoming.get(part.id, 0), h_c, terms.moq if terms else 1
                ),
                r_lead=r_lead,
                r_price=r_price,
                external_level=risk_level(max(r_lead, r_price)),
            )
        )
        computed += 1
    session.flush()
    return computed


@job("nightly")
def nightly(session: Session, now: datetime) -> dict[str, Any]:
    r_by_code = load_indicators(session)
    companies = company_ids(session)
    ai = get_ai_client()
    parts = flags = embedded = 0
    for cid in companies:
        parts += compute_company(session, cid, now, r_by_code)
        flags += audit_company(session, cid, now)
        if ai:
            set_tenant(session, cid)
            embedded += fill_missing(session, ai, cid)
    return {
        "companies": len(companies),
        "parts_computed": parts,
        "audit_flags_created": flags,
        "indicators": len(r_by_code),
        "embeddings_filled": embedded,
    }
