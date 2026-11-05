"""새벽 배치 (매일 03:00): 외부 지표 위험도 → 부품 근거 지표 → 장부 검증.

기능명세서 F-EXT-02, F-ANAL, F-AUDIT. 재고 요약 대조(F-LEDGER-02)는 요약 도입 시 더한다.
"""

import csv
import math
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.orm import Session

from bjk_server.audit.flags import audit_company
from bjk_server.auth import set_tenant
from bjk_server.clock import KST
from bjk_server.db.models import (
    Category,
    CompanySettings,
    Equipment,
    EquipmentPart,
    ExternalIndicator,
    Maintenance,
    Movement,
    Part,
    PartMetrics,
    PartSupplierMetrics,
    Supplier,
    SupplierPart,
)
from bjk_server.defaults import default_settings
from bjk_server.domain import analytics as an
from bjk_server.domain.external import indicator_risk, risk_level
from bjk_server.jobs.runner import company_ids, job

INDICATOR_CSV = Path(__file__).resolve().parents[1] / "seed" / "data" / "external_indicators.csv"
# 지표 코드 → (이름, 계열). 카테고리의 lead_factors·price_factors가 이 코드를 가리킨다.
INDICATORS = {
    "FREIGHT": ("컨테이너 운임지수", "lead"),
    "USDKRW": ("원/달러 환율", "price"),
}
FALLBACK_LEAD_DAYS = 7  # 공급사도 기본 납기도 없을 때
HISTORY_WEEKS = 52
IMPORT_DEPENDENT = ("high", "medium")


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
    latest = (
        select(ExternalIndicator.code, ExternalIndicator.r)
        .ext(distinct_on(ExternalIndicator.code))
        .order_by(ExternalIndicator.code, ExternalIndicator.as_of.desc())
    )
    return {code: r for code, r in session.execute(latest)}


@dataclass(frozen=True)
class SupplierTerms:
    supplier_id: uuid.UUID
    unit_price: int
    moq: int
    base_lead_days: int
    holidays: tuple[date, ...]


def lead_time(
    terms: SupplierTerms | None, import_dependent: bool, r_lead: float, k: float, today: date
) -> int:
    """납기 표본이 없을 때의 납기 (F-ANAL-04, F-EXT-02).

    기본 납기 × (1 + k × r_lead, 수입 의존 부품만) + 납기 구간에 겹치는 공급사 휴무일.
    """
    base = terms.base_lead_days if terms else FALLBACK_LEAD_DAYS
    days = math.ceil(base * (1 + k * r_lead) if import_dependent else base)
    holidays = terms.holidays if terms else ()
    return days + sum(1 for h in holidays if today < h <= today + timedelta(days=days))


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
    service_level = settings["review"]["service_level"]
    next_order_days = settings["review"]["next_order_weeks"] * 7
    k = settings["system"]["external_k"]

    parts = session.scalars(
        select(Part).where(Part.company_id == company_id, Part.merged_into.is_(None))
    ).all()
    categories = {
        c.id: c for c in session.scalars(select(Category).where(Category.company_id == company_id))
    }
    suppliers = {
        s.id: s for s in session.scalars(select(Supplier).where(Supplier.company_id == company_id))
    }
    terms_by_part: dict[uuid.UUID, dict[uuid.UUID, SupplierTerms]] = defaultdict(dict)
    for sp in session.scalars(select(SupplierPart).where(SupplierPart.company_id == company_id)):
        supplier = suppliers[sp.supplier_id]
        terms_by_part[sp.part_id][sp.supplier_id] = SupplierTerms(
            sp.supplier_id,
            sp.unit_price,
            sp.moq,
            supplier.default_lead_time_days or FALLBACK_LEAD_DAYS,
            tuple(supplier.holidays or ()),
        )

    stock = dict(
        session.execute(
            select(Movement.part_id, func.sum(Movement.qty))
            .where(Movement.company_id == company_id)
            .group_by(Movement.part_id)
        ).all()
    )
    first_seen = dict(
        session.execute(
            select(Movement.part_id, func.min(Movement.occurred_at))
            .where(Movement.company_id == company_id)
            .group_by(Movement.part_id)
        ).all()
    )
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
            outs[part_id].append((occurred_at.astimezone(KST).date(), -qty))
        if occurred_at >= year_ago:
            usage_qty[part_id] += -qty

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

        lead = {
            sid: lead_time(t, import_dependent, r_lead, k, today)
            for sid, t in terms_by_part[part.id].items()
        }
        for sid, t in terms_by_part[part.id].items():
            session.add(
                PartSupplierMetrics(
                    company_id=company_id,
                    part_id=part.id,
                    supplier_id=sid,
                    computed_on=today,
                    computed_at=now,
                    lt50=lead[sid],
                    lt90=lead[sid],
                    samples=0,
                    unit_price=t.unit_price,
                    moq=t.moq,
                )
            )
        terms = default_terms(part)
        lt = (
            lead[terms.supplier_id]
            if terms
            else lead_time(None, import_dependent, r_lead, k, today)
        )
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
        hidden = [
            int(stock.get(o.id, 0))
            for o in parts
            if o.id != part.id
            and part.spec
            and o.category_id == part.category_id
            and o.spec == part.spec
        ]
        # 실사 기록 기능 전이라 같은 규격 부품의 재고는 모두 미확인(H_u)으로 본다 (F-MATCH-03).
        h_c, h_u = 0, sum(hidden)
        paths = an.simulate_paths(
            s + h_c,
            weekly_samples,
            [(f["offset"], f["qty"]) for f in maintenance_needs(part.id, 56)],
            lt,
            rng,
        )
        t_out = today + timedelta(days=paths.t_out_day) if paths.t_out_day is not None else None

        linked = [equipment[link.equipment_id] for link in links[part.id]]
        loss = an.expected_loss([(e.loss_per_hour, e.operating_hours) for e in linked], lt)
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
                lt50=lt,
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
                recommended_qty=an.recommended_qty(d95, s, 0, h_c, terms.moq if terms else 1),
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
    parts = flags = 0
    for cid in companies:
        parts += compute_company(session, cid, now, r_by_code)
        flags += audit_company(session, cid, now)
    return {
        "companies": len(companies),
        "parts_computed": parts,
        "audit_flags_created": flags,
        "indicators": len(r_by_code),
    }
