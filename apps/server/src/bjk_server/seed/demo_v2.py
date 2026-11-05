"""시연 시드 확장 (demo_v2).

demo_v1을 그대로 만든 뒤 그 위에 더한다. ID가 demo_v1과 같아 시연 계정·토큰이 그대로 쓰인다.
더하는 값은 프론트 가상 공장 목업(BJKFE `mocks/fixtures`, 2026-11-05)을 옮긴
`data/demo_v2.json`이다.
부품 100종·공급사 7곳·설비 3대·정비·3D 창고 배치를 넣고, 부품마다 52주 출고 이력과 재주문·입고를
고정 난수로 시뮬레이션한다. 입고는 발주와 원장을 연결해 납기·단가 표본이 된다.

근거 지표·검토는 새벽 배치와 검토 엔진이 계산한다. 시드 CLI가 `finish_demo_v2`로 이어서 돌린다.
테스트·시연 전용 값이며 운영 데이터로 쓰지 않는다.
"""

import json
import math
import random
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from bjk_review import OrderRequest
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from bjk_server.ai.client import get_ai_client
from bjk_server.auth import set_tenant
from bjk_server.clock import KST
from bjk_server.db.models import (
    AuditFlag,
    Category,
    CountRequest,
    Equipment,
    EquipmentPart,
    Maintenance,
    Movement,
    Part,
    PurchaseOrder,
    Supplier,
    SupplierPart,
    TwinLayout,
)
from bjk_server.domain.matching import extract_spec
from bjk_server.jobs import registry  # noqa: F401 - 작업 등록
from bjk_server.jobs.runner import run_job
from bjk_server.reviews.service import create_review, run_review
from bjk_server.seed.demo import COMPANY_CODE, EQUIPMENT, demo_id

DATA = Path(__file__).resolve().parent / "data" / "demo_v2.json"
HISTORY_WEEKS = 52
# 이력이 없는 부품(신규 등록·중복 등록)을 등록한 시점
NEW_PART_DAYS_AGO = 18
# 입고 시각. 같은 날 출고(09시 이후)보다 앞서야 원장 중간 재고가 0 밑으로 가지 않는다
RECEIPT_HOUR = 8
# 정기 실사: 이 비율의 부품은 최근 COUNT_DAYS_AGO일 안에 실사를 마쳤다.
# 나머지는 실사 기한 지남(F-AUDIT-05) 시연용으로 둔다.
COUNTED_SHARE = 0.9
COUNT_DAYS_AGO = (20, 70)

# demo_v1 기본 카테고리 4개에 더하는 카테고리 (키, 이름, 수입 의존, 납기 요인, 단가 요인, HS 코드)
EXTRA_CATEGORIES = (
    ("seal", "씰·오링", "medium", ["FREIGHT", "HOLIDAY_KR"], ["USDKRW"], "4016"),
    ("pneumatic", "공압·유압", "high", ["FREIGHT", "HOLIDAY_CN"], ["USDKRW"], "8481"),
    ("tool", "절삭공구", "high", ["FREIGHT", "HOLIDAY_CN"], ["USDKRW"], "8207"),
    ("filter", "필터", "low", ["HOLIDAY_KR"], [], "8421"),
)
# 수입 의존이 높은 카테고리는 1년 동안 단가가 이만큼 오른다 (환율 영향 표현)
PRICE_DRIFT = {"bearing": 0.06, "pneumatic": 0.05, "tool": 0.05}

# 대체 공급사: 기본 공급사 → (대체 공급사, 단가 비율, 납기 차이 일). 더 싸지만 늦다(C-06 시연).
ALT_SUPPLIERS = {
    "f-bearing-shop": ("f-b", 0.88, 4),
    "f-b": ("f-bearing-shop", 0.9, 3),
    "f-bolt": ("a", 0.85, 3),
    "f-oil": ("a", 0.9, 4),
    "f-pneu": ("f-a", 0.9, 3),
}
# 대체 공급사가 있는 부품 중 이 비율의 발주를 대체 공급사로 낸다 (공급사별 납기 표본)
ALT_ORDER_SHARE = 0.2

# 수요 패턴: (주마다 출고가 있을 확률, 변동계수)
PATTERNS = {
    "smooth": (1.0, 0.35),
    "erratic": (1.0, 0.9),
    "intermittent": (0.3, 0.35),
    "lumpy": (0.2, 0.9),
}
SEASON_AMPLITUDE = 0.15

# 3D 창고 바닥 구역 (프론트 목업 ZONES 그대로)
TWIN_SIZE = {"width": 22, "depth": 18}
TWIN_ZONES = (
    ("zone-a", "storage", "A  소모품", -7, 0, 4.4, 8),
    ("zone-b", "storage", "B  부품", 0.3, 0, 7.6, 8),
    ("zone-c", "storage", "C  필터·예비", 7, 0, 4.4, 8),
)


@dataclass(frozen=True)
class V2Part:
    key: str
    name: str
    category: str | None
    unit: str
    stock: int
    monthly: float | None
    pattern: str | None
    supplier: str | None
    unit_price: int | None
    moq: int
    lt50: int | None
    lt90: int | None
    place: tuple[str, int, int] | None


@dataclass
class SimOrder:
    supplier: str
    qty: int
    unit_price: int
    approved_on: date
    received_on: date


@dataclass
class SimResult:
    opening: int
    outs: list[tuple[date, int]] = field(default_factory=list)
    orders: list[SimOrder] = field(default_factory=list)
    adjust: int = 0


def load_data(path: Path = DATA) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["parts"] = [
        V2Part(**{**p, "place": tuple(p["place"]) if p["place"] else None}) for p in data["parts"]
    ]
    return data


def location_text(place: tuple[str, int, int] | list) -> str:
    rack, level, slot = place
    return f"{rack} {level}단 {slot}칸"


def history_start(today: date) -> date:
    """이력 시작일: 오늘이 속한 주 월요일에서 HISTORY_WEEKS주 전."""
    return today - timedelta(days=today.weekday(), weeks=HISTORY_WEEKS)


def _poisson(rng: random.Random, mean: float) -> int:
    limit, k, p = math.exp(-mean), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def _weekly_demand(part: V2Part, rng: random.Random) -> list[list[tuple[int, int]]]:
    """주마다 (주 안의 요일, 수량) 목록. 재고와 상관없는 수요라 시뮬레이션을 몇 번 돌려도 같다."""
    chance, cv = PATTERNS.get(part.pattern or "smooth", PATTERNS["smooth"])
    weekly = (part.monthly or 0) * 12 / 52
    phase = rng.random() * 2 * math.pi
    weeks: list[list[tuple[int, int]]] = []
    for w in range(HISTORY_WEEKS):
        events: list[tuple[int, int]] = []
        if weekly > 0 and rng.random() < chance:
            mean = weekly / chance * (1 + SEASON_AMPLITUDE * math.sin(phase + 2 * math.pi * w / 52))
            qty = _poisson(rng, mean) if mean < 3 else max(0, round(rng.gauss(mean, mean * cv)))
            if qty >= 4 and rng.random() < 0.5:
                first = rng.randint(1, qty - 1)
                events = [(rng.randrange(5), first), (rng.randrange(5), qty - first)]
            elif qty > 0:
                events = [(rng.randrange(5), qty)]
        weeks.append(sorted(events))
    return weeks


def _lead_days(part: V2Part, rng: random.Random) -> int:
    lt50 = part.lt50 or 7
    lt90 = max(part.lt90 or lt50, lt50)
    if rng.random() < 0.8:
        return max(1, lt50 + rng.choice((-1, 0, 0, 1)))
    return max(1, rng.randint(lt50 + 1, lt90 + 1))


def _price(part: V2Part, rng: random.Random, ratio: float, progress: float) -> int:
    drift = PRICE_DRIFT.get(part.category or "", 0.0)
    value = (part.unit_price or 0) * ratio * (1 - drift + drift * progress)
    value *= 1 + rng.gauss(0, 0.025)
    step = 10 if value >= 1000 else 1
    return max(1, round(value / step) * step)


def simulate(part: V2Part, scenario: str, today: date) -> SimResult:
    """52주 출고와 재주문점 발주·입고. 마지막 재고가 목업 재고와 같도록 시작 재고를 맞춘다.

    수요·납기·단가 난수는 시작 재고와 따로 미리 뽑아 두어, 시작 재고만 바꿔 다시 돌려도
    같은 이력이 된다.
    맞추고 남은 차이는 어제 정기 실사 조정 한 건으로 메운다.
    """
    start = history_start(today)
    if not part.monthly:
        return SimResult(opening=part.stock)
    rng = random.Random(f"{scenario}:v2:{part.key}")
    demand = _weekly_demand(part, rng)
    weekly = part.monthly * 12 / 52
    lt90 = part.lt90 or part.lt50 or 7
    reorder_point = math.ceil(weekly * (lt90 / 7 + 1.5))
    order_qty = max(part.moq, math.ceil(weekly * 6), 1)
    alt = ALT_SUPPLIERS.get(part.supplier or "")
    draws = [
        (rng.random(), _lead_days(part, rng), rng.random(), rng.gauss(0, 1))
        for _ in range(HISTORY_WEEKS * 2)
    ]

    def run(opening: int) -> SimResult:
        result = SimResult(opening=opening)
        stock, pending, n = opening, [], 0
        out_by_day: dict[date, int] = {}
        for w, events in enumerate(demand):
            for weekday, qty in events:
                day = start + timedelta(weeks=w, days=weekday)
                out_by_day[day] = out_by_day.get(day, 0) + qty
        day = start
        while day < today:
            for o in [o for o in pending if o.received_on == day]:
                stock += o.qty
                pending.remove(o)
            want = out_by_day.get(day, 0)
            used = min(want, stock)
            if used:
                stock -= used
                result.outs.append((day, used))
            on_order = sum(o.qty for o in pending)
            if stock + on_order <= reorder_point and not pending and n < len(draws):
                pick, lead, price_rng, _ = draws[n]
                n += 1
                use_alt = alt is not None and pick < ALT_ORDER_SHARE
                supplier = alt[0] if use_alt else part.supplier
                ratio = alt[1] if use_alt else 1.0
                lead += alt[2] if use_alt else 0
                progress = (day - start).days / (HISTORY_WEEKS * 7)
                order = SimOrder(
                    supplier=supplier or "",
                    qty=order_qty,
                    unit_price=_price(part, random.Random(price_rng), ratio, progress),
                    approved_on=day,
                    received_on=day + timedelta(days=1 + lead),
                )
                result.orders.append(order)
                pending.append(order)
            day += timedelta(days=1)
        result.adjust = part.stock - stock
        return result

    opening = reorder_point + order_qty
    best = run(opening)
    for _ in range(8):
        if best.adjust == 0:
            break
        opening = max(0, opening + best.adjust)
        trial = run(opening)
        if abs(trial.adjust) >= abs(best.adjust) and trial.opening != best.opening:
            break
        best = trial
    return best


def _at(day: date, hour: int = 10) -> datetime:
    return datetime.combine(day, time(hour), tzinfo=KST)


def extend_v2(session: Session, today: date) -> None:
    """demo_v1이 만든 회사에 demo_v2 데이터를 더한다. demo_v1과 같은 ID 규칙(demo_v1)을 쓴다."""
    data = load_data()

    def sid(kind: str, key: str) -> uuid.UUID:
        return demo_id(kind, key)

    company_id = sid("company", COMPANY_CODE)
    owner, manager = sid("user", "owner"), sid("user", "manager")
    workers = [sid("user", "worker"), sid("user", "worker2")]

    for key, name, dependency, lead, price, hs in EXTRA_CATEGORIES:
        session.add(
            Category(
                id=sid("category", key),
                company_id=company_id,
                name=name,
                import_dependency=dependency,
                lead_factors=lead,
                price_factors=price,
                hs_code=hs,
            )
        )
    for s in data["suppliers"]:
        session.add(
            Supplier(
                id=sid("supplier", s["key"]),
                company_id=company_id,
                name=s["name"],
                contact=s["contact"],
                default_lead_time_days=s["lead_days"],
            )
        )
    session.flush()

    parts: list[V2Part] = data["parts"]
    for p in parts:
        session.add(
            Part(
                id=sid("part", p.key),
                company_id=company_id,
                category_id=sid("category", p.category) if p.category else None,
                default_supplier_id=sid("supplier", p.supplier) if p.supplier else None,
                name=p.name,
                spec=extract_spec(p.name),
                unit=p.unit,
                location=location_text(p.place) if p.place else None,
            )
        )
    for key, place in data["v1_places"].items():
        session.get(Part, sid("part", key)).location = location_text(place)
    session.flush()

    for p in parts:
        if not (p.supplier and p.unit_price):
            continue
        session.add(
            SupplierPart(
                id=sid("supplier_part", f"{p.key}:{p.supplier}"),
                company_id=company_id,
                supplier_id=sid("supplier", p.supplier),
                part_id=sid("part", p.key),
                unit_price=p.unit_price,
                moq=p.moq,
                price_tiers=[],
                shipping_fee=3000 if p.unit_price < 50000 else 0,
            )
        )
        alt = ALT_SUPPLIERS.get(p.supplier)
        if alt:
            step = 10 if p.unit_price >= 1000 else 1
            session.add(
                SupplierPart(
                    id=sid("supplier_part", f"{p.key}:{alt[0]}"),
                    company_id=company_id,
                    supplier_id=sid("supplier", alt[0]),
                    part_id=sid("part", p.key),
                    unit_price=max(1, round(p.unit_price * alt[1] / step) * step),
                    moq=max(p.moq, 5 if p.unit_price >= 1000 else 100),
                    price_tiers=[],
                    shipping_fee=3000,
                )
            )

    linked = {(eq, part) for eq, *_, links in EQUIPMENT for part, _ in links}
    equipment_of: dict[str, list[str]] = {}
    for e in data["equipment"]:
        eq_id = sid("equipment", e["key"])
        if e["reuse"]:
            row = session.get(Equipment, eq_id)
            row.name = e["name"]
            row.loss_per_hour = e["loss"] or 0
            row.operating_hours = e["hours"] or 8
        else:
            session.add(
                Equipment(
                    id=eq_id,
                    company_id=company_id,
                    name=e["name"],
                    loss_per_hour=e["loss"] or 0,
                    loss_is_estimate=True,
                    operating_hours=e["hours"] or 8,
                )
            )
        session.flush()
        for part_key, qty in e["parts"]:
            equipment_of.setdefault(part_key, []).append(e["key"])
            if (e["key"], part_key) in linked:
                continue
            session.add(
                EquipmentPart(
                    id=sid("equipment_part", f"{e['key']}:{part_key}"),
                    company_id=company_id,
                    equipment_id=eq_id,
                    part_id=sid("part", part_key),
                    qty_per_maintenance=qty,
                )
            )
    for m in data["maintenance"]:
        day = today + timedelta(days=m["days"])
        session.add(
            Maintenance(
                id=sid("maintenance", f"v2:{m['equipment']}:{m['days']}"),
                company_id=company_id,
                equipment_id=sid("equipment", m["equipment"]),
                scheduled_date=day,
                # 완료된 정비는 필요 부품만 적고 출고는 남기지 않는다 (F-AUDIT-02 시연)
                required_parts=(
                    [{"part_id": str(sid("part", k)), "qty": q} for k, q in m["parts"]]
                    if m["completed"]
                    else None
                ),
                completed_at=_at(day, 15) if m["completed"] else None,
            )
        )

    session.execute(delete(TwinLayout).where(TwinLayout.company_id == company_id))
    places = [(k, tuple(v)) for k, v in data["v1_places"].items()]
    places += [(p.key, p.place) for p in parts if p.place]
    session.add(
        TwinLayout(
            company_id=company_id,
            layout={
                "size": TWIN_SIZE,
                "zones": [
                    {"id": i, "kind": k, "label": label, "x": x, "z": z, "width": w, "depth": d}
                    for i, k, label, x, z, w, d in TWIN_ZONES
                ],
                "racks": [
                    {
                        "id": rid,
                        "label": rid,
                        "levels": levels,
                        "slots": slots,
                        "x": x,
                        "z": z,
                        "rotation": 0,
                        "purpose": purpose,
                    }
                    for rid, levels, slots, x, z, purpose in data["racks"]
                ],
                "equipment": [
                    {
                        "equipment_id": str(sid("equipment", e["key"])),
                        "kind": e["kind"],
                        "x": e["x"],
                        "z": e["z"],
                    }
                    for e in data["equipment"]
                ],
                "placements": [
                    {"part_id": str(sid("part", key)), "rack_id": r, "level": lv, "slot": sl}
                    for key, (r, lv, sl) in places
                ],
            },
        )
    )
    session.flush()

    start = history_start(today)
    for p in parts:
        part_id = sid("part", p.key)
        sim = simulate(p, "demo_v2", today)
        rng = random.Random(f"demo_v2:authors:{p.key}")
        opened = start if p.monthly else today - timedelta(days=NEW_PART_DAYS_AGO)
        movements: list[Movement] = []
        if sim.opening:
            movements.append(
                Movement(
                    id=sid("movement", f"v2:{p.key}:opening"),
                    company_id=company_id,
                    part_id=part_id,
                    type="ADJUST",
                    qty=sim.opening,
                    occurred_at=_at(opened, 9),
                    reason="초기 재고 이관",
                )
            )
        for i, o in enumerate(sim.orders):
            po_id = sid("purchase_order", f"v2:{p.key}:{i}")
            received = o.received_on < today
            session.add(
                PurchaseOrder(
                    id=po_id,
                    company_id=company_id,
                    part_id=part_id,
                    supplier_id=sid("supplier", o.supplier),
                    qty=o.qty,
                    unit_price=o.unit_price,
                    status="received" if received else "ordered",
                    approved_at=_at(o.approved_on, 16),
                    approved_by=owner,
                    ordered_at=_at(o.approved_on + timedelta(days=1), 9),
                    ordered_by=manager,
                    received_qty=o.qty if received else 0,
                    received_at=_at(o.received_on, RECEIPT_HOUR) if received else None,
                )
            )
            if received:
                movements.append(
                    Movement(
                        id=sid("movement", f"v2:{p.key}:in:{i}"),
                        company_id=company_id,
                        part_id=part_id,
                        type="IN",
                        qty=o.qty,
                        occurred_at=_at(o.received_on, RECEIPT_HOUR),
                        author_id=rng.choice(workers),
                        po_id=po_id,
                        source_text=f"{p.name} {o.qty}{p.unit} 들어왔어요",
                    )
                )
        links = equipment_of.get(p.key, [])
        for i, (day, qty) in enumerate(sim.outs):
            equipment = rng.choice(links) if links and rng.random() < 0.7 else None
            movements.append(
                Movement(
                    id=sid("movement", f"v2:{p.key}:out:{i}"),
                    company_id=company_id,
                    part_id=part_id,
                    type="OUT",
                    qty=-qty,
                    occurred_at=_at(day, rng.choice((9, 10, 11, 14, 15, 16))),
                    author_id=rng.choice(workers),
                    equipment_id=sid("equipment", equipment) if equipment else None,
                    source_text=f"{p.name} {qty}{p.unit} 씀",
                )
            )
        if sim.adjust:
            movements.append(
                Movement(
                    id=sid("movement", f"v2:{p.key}:adjust"),
                    company_id=company_id,
                    part_id=part_id,
                    type="ADJUST",
                    qty=sim.adjust,
                    occurred_at=_at(today - timedelta(days=1), 18),
                    author_id=manager,
                    reason="정기 실사 조정",
                )
            )
        # 관계 없이 FK 열만 있어 발주를 먼저 넣어야 입고 원장이 발주를 가리킬 수 있다
        session.flush()
        session.add_all(movements)
    session.flush()
    _routine_counts(session, company_id, today, manager, workers)


def _routine_counts(
    session: Session,
    company_id: uuid.UUID,
    today: date,
    manager: uuid.UUID,
    workers: list[uuid.UUID],
) -> None:
    """지난 정기 실사 기록.

    실사는 닫힌 실사 기한 항목과 차이 없는 실사 요청으로 남는다(F-AUDIT-05·06).
    """
    for part_id, name in session.execute(
        select(Part.id, Part.name).where(Part.company_id == company_id).order_by(Part.name)
    ):
        rng = random.Random(f"demo_v2:count:{name}")
        if rng.random() >= COUNTED_SHARE:
            continue
        counted_at = _at(today - timedelta(days=rng.randint(*COUNT_DAYS_AGO)), 17)
        book = session.scalar(
            select(func.coalesce(func.sum(Movement.qty), 0)).where(
                Movement.part_id == part_id, Movement.occurred_at <= counted_at
            )
        )
        if book <= 0:
            continue
        flag_id = demo_id("audit_flag", f"v2:count:{part_id}")
        session.add(
            AuditFlag(
                id=flag_id,
                company_id=company_id,
                part_id=part_id,
                rule="COUNT_OVERDUE",
                level="low",
                status="closed",
                evidence={"last_counted_at": None, "days_since": 90, "movements_since": 0},
                related=[],
                keys=["COUNT_OVERDUE"],
                resolution="no_diff",
                created_at=counted_at - timedelta(days=1),
                updated_at=counted_at,
                closed_at=counted_at,
            )
        )
        session.flush()
        session.add(
            CountRequest(
                id=demo_id("count_request", f"v2:{part_id}"),
                company_id=company_id,
                audit_flag_id=flag_id,
                part_id=part_id,
                assignee_id=rng.choice(workers),
                requested_by=manager,
                status="closed",
                message=f"{name} 정기 실사를 부탁드려요. 칸에 있는 수량을 세어 주세요.",
                sent_at=counted_at - timedelta(hours=6),
                counted_qty=book,
                book_qty_before=book,
                diff=0,
                answered_at=counted_at,
                closed_at=counted_at,
            )
        )
    session.flush()


# 시드 뒤 예시 직원 요청 (부품, 요청자, 수량, 공급사, 단가, 문장).
# 공급사·단가가 비면 검토가 기본 공급사·등록 단가를 쓴다.
SAMPLE_REQUESTS: tuple[tuple[str, str, int, str | None, int | None, str], ...] = (
    ("insert-cnmg", "worker", 50, None, None, "인서트 CNMG 50개 시켜주세요"),
    ("washer-m8", "worker2", 1000, None, None, "평와셔 M8 1000개 넉넉하게 주문해 주세요"),
    ("hyd-packing", "worker2", 3, None, None, "프레스 패킹 세트 3개 시켜주세요"),
    ("endmill-10", "worker", 9, "f-tool", 58000, "엔드밀 10파이 9개 정우툴링에서 개당 5만8천원"),
    ("belt-b50-old", "worker", 4, None, None, "전동벨트 B-50 4개 필요해요"),
)

AFTER_SEED_JOBS = ("nightly", "weekly-merge", "missed-scan", "briefing")


def finish_demo_v2(engine: Engine, now: Callable[[], datetime] | None = None) -> dict[str, Any]:
    """시드를 커밋한 뒤 돌린다.

    새벽 배치 등으로 근거 지표·병합 후보·초안 검토를 만들고 예시 직원 요청을 검토한다.
    """
    summary: dict[str, Any] = {}
    for name in AFTER_SEED_JOBS:
        result = run_job(engine, name, "manual", now=now() if now else None)
        summary[name] = result.status
    company_id = demo_id("company", COMPANY_CODE)
    scope = sessionmaker(engine, expire_on_commit=False).begin
    ai = get_ai_client()
    created = []
    for part_key, user, qty, supplier, price, text in SAMPLE_REQUESTS:
        with scope() as db:
            set_tenant(db, company_id)
            review = create_review(
                db,
                company_id,
                entry="staff_request",
                order=OrderRequest(
                    qty=qty,
                    supplier_id=str(demo_id("supplier", supplier)) if supplier else None,
                    unit_price=price,
                ),
                part_id=demo_id("part", part_key),
                requested_by=demo_id("user", user),
                text=text,
            )
            created.append(review.id)
    for review_id in created:
        run_review(scope, ai, company_id, review_id)
    summary["sample_reviews"] = len(created)
    with scope() as db:
        set_tenant(db, company_id)
        summary["parts"] = db.scalar(select(func.count()).select_from(Part))
    return summary
