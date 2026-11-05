"""시연 시드 데이터 (demo_v1).

API 명세서 예시(한서정밀, 볼베어링 6205ZZ·6204ZZ, V벨트 A-42)를 기준으로 만든다.
ID는 이름에서 uuid5로 만들고 이력은 고정 난수로 만들어, 같은 날 다시 실행하면 같은 상태가 된다.
테스트·시연 전용 값이며 운영 데이터로 쓰지 않는다.
"""

import random
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from bjk_server.clock import KST
from bjk_server.db.models import (
    Base,
    CalendarEvent,
    Category,
    Company,
    CompanySettings,
    Equipment,
    EquipmentPart,
    Maintenance,
    Movement,
    Part,
    PartAlias,
    PurchaseOrder,
    SimReport,
    Supplier,
    SupplierPart,
    TwinLayout,
    User,
)
from bjk_server.defaults import DEFAULT_CATEGORIES, default_settings
from bjk_server.security import hash_secret

SCENARIOS = ("demo_v1",)
HISTORY_WEEKS = 12
_NAMESPACE = uuid.UUID("6f1c2d1e-5b0a-4c8e-9a51-0b6a1f3c2d10")

COMPANY_NAME = "한서정밀"
COMPANY_CODE = "HS7F3K"


@dataclass(frozen=True)
class DemoUser:
    key: str
    name: str
    role: str
    email: str | None = None
    password: str | None = None
    pin: str | None = None


# 시연 계정. 비밀번호·PIN은 시연 전용 값이다.
USERS = (
    DemoUser("owner", "김사장", "owner", "owner@hanseo.kr", "demo-owner-1234"),
    DemoUser("manager", "최관리", "manager", "manager@hanseo.kr", "demo-manager-1234", "2468"),
    DemoUser("worker", "이현장", "worker", pin="1234"),
    DemoUser("worker2", "박정비", "worker", pin="5678"),
)


@dataclass(frozen=True)
class DemoPart:
    key: str
    name: str
    category: str
    unit: str
    stock: int
    weekly_out: float  # 주간 평균 출고량
    out_chance: float  # 주마다 출고가 있을 확률 (간헐 수요 표현)
    spec: dict = field(default_factory=dict)
    pack_qty: int | None = None
    location: str | None = None
    equipment: str | None = None


CATEGORIES = DEFAULT_CATEGORIES

PARTS = (
    DemoPart(
        "6205",
        "볼베어링 6205ZZ",
        "bearing",
        "개",
        3,
        0.3,
        0.25,
        {"bearing_no": "6205", "shield": "ZZ"},
        location="A선반 2칸",
        equipment="eq3",
    ),
    DemoPart(
        "6204",
        "볼베어링 6204ZZ",
        "bearing",
        "개",
        12,
        1.5,
        0.6,
        {"bearing_no": "6204", "shield": "ZZ"},
        location="A선반 2칸",
        equipment="eq1",
    ),
    DemoPart(
        "a42",
        "V벨트 A-42",
        "belt",
        "개",
        2,
        1.2,
        0.7,
        {"type": "A", "length": 42},
        location="B선반 1칸",
        equipment="eq2",
    ),
    DemoPart(
        "m820",
        "육각볼트 M8-20",
        "bolt",
        "개",
        40,
        70,
        0.9,
        {"thread": "M8", "length_mm": 20},
        pack_qty=100,
        location="A선반 1칸",
    ),
    DemoPart(
        "p20",
        "오링 P-20",
        "bolt",
        "개",
        1040,
        25,
        0.8,
        {"size": "P-20"},
        pack_qty=100,
        location="C선반 3칸",
        equipment="eq3",
    ),
    DemoPart(
        "oil",
        "수용성 절삭유 20L",
        "oil",
        "통",
        4,
        0.8,
        0.7,
        {"volume_l": 20},
        location="창고",
    ),
)

SUPPLIERS = (
    ("a", "공급사 A", "010-0000-0001", 7),
    ("b", "공급사 B", "010-0000-0002", 5),
)

# (부품, 공급사, 단가, MOQ, 단가 구간, 배송비)
SUPPLIER_PARTS = (
    ("6205", "a", 18000, 10, [{"min_qty": 20, "unit_price": 16500}], 4000),
    ("6204", "a", 21000, 1, [], 4000),
    ("6204", "b", 14800, 10, [], 3000),
    ("a42", "a", 18000, 1, [], 3000),
    ("a42", "b", 15000, 5, [], 3000),
    ("m820", "a", 120, 100, [], 3000),
    ("p20", "b", 90, 100, [], 3000),
    ("oil", "a", 48000, 1, [], 0),
)
# 입고 완료 발주 이력 (납기 표본, F-ANAL 납기·F-LEDGER-04). 공급사·부품마다 이만큼 만든다.
ORDERS_PER_DEFAULT_SUPPLIER = 4
ORDERS_PER_OTHER_SUPPLIER = 2
# 기본 납기 대비 실제 납기 차이(일). 고정 난수로 고른다.
LEAD_JITTER_DAYS = (-1, 0, 0, 1, 2, 3)
# 최근 구매 단가를 명세 예시에 맞추는 부품: 기본 공급사 발주 단가(오래된 순).
# V벨트 A-42는 API 명세서 REV-02 예시(p_mean 13,000원, σ 1,200, n 4)가 나오게 한다.
ORDER_PRICES = {"a42": (11530, 13000, 14470, 13000)}
DEFAULT_SUPPLIER = {"6205": "a", "6204": "a", "a42": "a", "m820": "a", "p20": "b", "oil": "a"}

# (설비, 이름, 시간당 손실, 가동 시간, [(부품, 정비 1회당 수량)])
EQUIPMENT = (
    ("eq1", "1호기", 30000, 16, [("6204", 2)]),
    ("eq2", "2호기", 20000, 8, [("a42", 2)]),
    ("eq3", "3호기", 50000, 16, [("6205", 4), ("p20", 100)]),
)

# (설비, 오늘부터 며칠 뒤)
MAINTENANCE = (("eq3", 16), ("eq2", 30))
# 완료됐지만 필요 부품 출고 기록이 없는 정비 (장부 검증 F-AUDIT-02 시연).
# (설비, 오늘부터 며칠 전, 완료 시각, [(부품, 필요 수량)])
COMPLETED_MAINTENANCE = (("eq3", 3, 15, [("p20", 100)]),)

ALIASES = (("베어링 작은 거", "6205", 3),)

# 검증 리포트 더미 (제목, 오늘부터 며칠 전). 검증 하네스(F-SIM)가 없어 W-09 화면 연결용으로만
# 넣는다(#260). 결과 수치는 넣지 않는다(F-SIM: 리포트에는 실제 실행한 값만).
SIM_REPORTS = (
    ("[시연용] 검토 기준값 탐지율 평가 (합성 데이터 18개월)", 7),
    ("[시연용] 현장 방식 대비 정책 재생 (결품·재고 금액)", 1),
)

# 3D 창고 더미 배치 (W-11, #281). 단위 m, 바닥 중심이 원점. 선반은 (id, 단, 칸, x, z, 용도),
# 설비는 (설비, 모양, x, z), 부품 칸은 (부품, 선반, 단, 칸). 실제 창고 배치를 받기 전 시연용이다.
TWIN_SIZE = {"width": 22, "depth": 18}
TWIN_ZONES = (
    ("zone-a", "storage", "A  베어링", -6.5, -3, 5, 6),
    ("zone-b", "storage", "B  벨트·볼트", 0, -3, 6, 6),
    ("zone-c", "storage", "C  씰·유류", 6.5, -3, 5, 6),
    ("zone-machines", "machines", "설비", 0, 4.5, 18, 5),
    ("zone-dock", "dock", "입고 도크", 0, -8, 6, 2),
)
TWIN_RACKS = (
    ("A-01", 4, 4, -6.5, -3, "베어링"),
    ("B-01", 4, 4, -1.5, -3, "벨트"),
    ("B-02", 4, 4, 1.5, -3, "볼트·너트"),
    ("C-01", 3, 4, 5, -3, "씰·오링"),
    ("C-02", 3, 4, 8, -3, "유류"),
)
TWIN_EQUIPMENT = (("eq1", "lathe", -5, 4.5), ("eq2", "mill", 0, 4.5), ("eq3", "press", 5, 4.5))
TWIN_PLACEMENTS = (
    ("6205", "A-01", 2, 1),
    ("6204", "A-01", 2, 2),
    ("a42", "B-01", 1, 1),
    ("m820", "B-02", 1, 1),
    ("p20", "C-01", 1, 1),
    ("oil", "C-02", 1, 1),
)

# 연휴 캘린더 (이름, 시작, 종료, 범위). 2027년 춘절·설날 연휴.
HOLIDAYS = (
    ("춘절", date(2027, 2, 5), date(2027, 2, 13), "CN"),
    ("설날 연휴", date(2027, 2, 6), date(2027, 2, 9), "KR"),
)


def demo_id(kind: str, key: str, scenario: str = "demo_v1") -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, f"{scenario}:{kind}:{key}")


def _at(day: date, hour: int = 10) -> datetime:
    return datetime.combine(day, time(hour), tzinfo=KST)


def _history(part: DemoPart, scenario: str, today: date) -> list[tuple[date, int]]:
    """과거 HISTORY_WEEKS주 동안의 (날짜, 출고 수량). 고정 난수로 같은 결과를 낸다."""
    rng = random.Random(f"{scenario}:{part.key}")
    events = []
    for week in range(HISTORY_WEEKS, 0, -1):
        if rng.random() >= part.out_chance:
            continue
        qty = max(1, round(rng.gauss(part.weekly_out / part.out_chance, part.weekly_out * 0.3)))
        day = today - timedelta(weeks=week) + timedelta(days=rng.randrange(5))
        events.append((day, qty))
    return events


@dataclass(frozen=True)
class DemoOrder:
    key: str
    supplier: str
    qty: int
    unit_price: int
    ordered_on: date
    received_on: date


def _orders(part: DemoPart, scenario: str, start: date) -> list[DemoOrder]:
    """초기 재고 이관(이력 시작) 전에 입고가 끝난 과거 발주. 납기 표본으로만 쓴다.

    이관 전 기록이라 원장 입고 이벤트는 없다. 이관 재고가 그 결과를 이미 담고 있다.
    입고일은 이력 시작 전 4주 간격, 주문일 = 입고일 - (공급사 기본 납기 + 차이).
    """
    rng = random.Random(f"{scenario}:orders:{part.key}")
    lead_days = {key: days for key, _, _, days in SUPPLIERS}
    orders: list[DemoOrder] = []
    for part_key, supplier, price, moq, _, _ in SUPPLIER_PARTS:
        if part_key != part.key:
            continue
        default = DEFAULT_SUPPLIER[part.key] == supplier
        prices = ORDER_PRICES.get(part.key)
        if prices and not default:
            # 단가 예시는 기본 공급사 이력만으로 맞춘다
            continue
        count = ORDERS_PER_DEFAULT_SUPPLIER if default else ORDERS_PER_OTHER_SUPPLIER
        for i in range(count):
            received = start - timedelta(weeks=4 * (i + 1), days=rng.randrange(7))
            lead = lead_days[supplier] + rng.choice(LEAD_JITTER_DAYS)
            orders.append(
                DemoOrder(
                    key=f"{part.key}:{supplier}:{i}",
                    supplier=supplier,
                    qty=max(moq, part.pack_qty or 1),
                    unit_price=prices[count - 1 - i] if prices else price,
                    ordered_on=received - timedelta(days=lead),
                    received_on=received,
                )
            )
    return orders


def _tables() -> list[str]:
    return [t.name for t in reversed(Base.metadata.sorted_tables)]


def reset_all(session: Session) -> None:
    """앱 테이블을 모두 비운다. TRUNCATE는 원장의 행 단위 삭제 차단 트리거를 거치지 않는다."""
    session.execute(text(f"TRUNCATE {', '.join(_tables())} CASCADE"))


def seed_demo(session: Session, scenario: str = "demo_v1", today: date | None = None) -> None:
    """소유자 계정 세션에서 실행한다. 기존 데이터를 지우고 시연 상태로 만든다."""
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario: {scenario}")
    today = today or datetime.now(KST).date()

    def sid(kind: str, key: str) -> uuid.UUID:
        return demo_id(kind, key, scenario)

    reset_all(session)
    company_id = sid("company", COMPANY_CODE)
    session.add(Company(id=company_id, name=COMPANY_NAME, code=COMPANY_CODE))
    session.flush()
    settings = default_settings()
    session.add(CompanySettings(company_id=company_id, **settings))

    for u in USERS:
        session.add(
            User(
                id=sid("user", u.key),
                company_id=company_id,
                name=u.name,
                role=u.role,
                email=u.email,
                password_hash=hash_secret(u.password) if u.password else None,
                pin_hash=hash_secret(u.pin) if u.pin else None,
            )
        )
    for key, name, dependency, lead, price, hs in CATEGORIES:
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
    for key, name, contact, lead_days in SUPPLIERS:
        session.add(
            Supplier(
                id=sid("supplier", key),
                company_id=company_id,
                name=name,
                contact=contact,
                default_lead_time_days=lead_days,
            )
        )
    session.flush()

    for p in PARTS:
        session.add(
            Part(
                id=sid("part", p.key),
                company_id=company_id,
                category_id=sid("category", p.category),
                default_supplier_id=sid("supplier", DEFAULT_SUPPLIER[p.key]),
                name=p.name,
                spec=p.spec,
                unit=p.unit,
                pack_qty=p.pack_qty,
                location=p.location,
            )
        )
    session.flush()

    for part_key, supplier_key, price, moq, tiers, shipping in SUPPLIER_PARTS:
        session.add(
            SupplierPart(
                id=sid("supplier_part", f"{part_key}:{supplier_key}"),
                company_id=company_id,
                supplier_id=sid("supplier", supplier_key),
                part_id=sid("part", part_key),
                unit_price=price,
                moq=moq,
                price_tiers=tiers,
                shipping_fee=shipping,
            )
        )
    for key, name, loss, hours, parts in EQUIPMENT:
        session.add(
            Equipment(
                id=sid("equipment", key),
                company_id=company_id,
                name=name,
                loss_per_hour=loss,
                loss_is_estimate=True,
                operating_hours=hours,
            )
        )
        session.flush()
        for part_key, qty in parts:
            session.add(
                EquipmentPart(
                    id=sid("equipment_part", f"{key}:{part_key}"),
                    company_id=company_id,
                    equipment_id=sid("equipment", key),
                    part_id=sid("part", part_key),
                    qty_per_maintenance=qty,
                )
            )
    for key, days in MAINTENANCE:
        session.add(
            Maintenance(
                id=sid("maintenance", f"{key}:{days}"),
                company_id=company_id,
                equipment_id=sid("equipment", key),
                scheduled_date=today + timedelta(days=days),
            )
        )
    for key, days_ago, hour, required in COMPLETED_MAINTENANCE:
        day = today - timedelta(days=days_ago)
        session.add(
            Maintenance(
                id=sid("maintenance", f"{key}:-{days_ago}"),
                company_id=company_id,
                equipment_id=sid("equipment", key),
                scheduled_date=day,
                required_parts=[
                    {"part_id": str(sid("part", part_key)), "qty": qty}
                    for part_key, qty in required
                ],
                completed_at=_at(day, hour),
            )
        )
    for name, start_day, end_day, scope in HOLIDAYS:
        session.add(
            CalendarEvent(
                id=sid("calendar", name),
                company_id=company_id,
                name=name,
                start_date=start_day,
                end_date=end_day,
                scope=scope,
            )
        )
    for title, days_ago in SIM_REPORTS:
        session.add(
            SimReport(
                id=sid("sim_report", title),
                company_id=company_id,
                title=title,
                source="sample",
                created_at=_at(today - timedelta(days=days_ago)),
            )
        )
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
                    for rid, levels, slots, x, z, purpose in TWIN_RACKS
                ],
                "equipment": [
                    {"equipment_id": str(sid("equipment", key)), "kind": kind, "x": x, "z": z}
                    for key, kind, x, z in TWIN_EQUIPMENT
                ],
                "placements": [
                    {"part_id": str(sid("part", key)), "rack_id": rid, "level": lv, "slot": sl}
                    for key, rid, lv, sl in TWIN_PLACEMENTS
                ],
            },
        )
    )
    for alias, part_key, count in ALIASES:
        session.add(
            PartAlias(
                id=sid("alias", alias),
                company_id=company_id,
                part_id=sid("part", part_key),
                text=alias,
                confirmed_count=count,
            )
        )
    session.flush()

    worker_id = sid("user", "worker")
    start = today - timedelta(weeks=HISTORY_WEEKS + 1)
    for p in PARTS:
        part_id = sid("part", p.key)
        outs = _history(p, scenario, today)
        # 시작 재고는 현재 재고에서 거꾸로 맞춘다: 시작 + 입고 - 출고 = 현재.
        # 이력 중 재고가 0 미만이 되지 않도록 시작 재고가 보충 입고 전 출고를 덮게 한다.
        refill_on = start + timedelta(weeks=HISTORY_WEEKS // 2)
        used = sum(q for _, q in outs)
        pack = p.pack_qty or 1
        opening, refill = p.stock + used, 0
        if used > p.stock:
            before_refill = sum(q for day, q in outs if day <= refill_on)
            opening = max(pack, pack * -(-before_refill // pack))
            refill = max(0, p.stock + used - opening)
            opening = p.stock + used - refill
        for o in _orders(p, scenario, start):
            session.add(
                PurchaseOrder(
                    id=sid("purchase_order", o.key),
                    company_id=company_id,
                    part_id=part_id,
                    supplier_id=sid("supplier", o.supplier),
                    qty=o.qty,
                    unit_price=o.unit_price,
                    status="received",
                    approved_at=_at(o.ordered_on - timedelta(days=1), 16),
                    approved_by=sid("user", "owner"),
                    ordered_at=_at(o.ordered_on, 9),
                    ordered_by=sid("user", "manager"),
                    received_qty=o.qty,
                    received_at=_at(o.received_on, 11),
                )
            )
        movements = []
        if opening:
            movements.append(
                Movement(
                    id=sid("movement", f"{p.key}:opening"),
                    company_id=company_id,
                    part_id=part_id,
                    type="ADJUST",
                    qty=opening,
                    occurred_at=_at(start, 9),
                    reason="초기 재고 이관",
                )
            )
        if refill:
            movements.append(
                Movement(
                    id=sid("movement", f"{p.key}:refill"),
                    company_id=company_id,
                    part_id=part_id,
                    type="IN",
                    qty=refill,
                    occurred_at=_at(refill_on, 14),
                    author_id=worker_id,
                    source_text=f"{p.name} {refill}{p.unit} 입고",
                )
            )
        for i, (day, qty) in enumerate(outs):
            movements.append(
                Movement(
                    id=sid("movement", f"{p.key}:{i}"),
                    company_id=company_id,
                    part_id=part_id,
                    type="OUT",
                    qty=-qty,
                    occurred_at=_at(day),
                    author_id=worker_id,
                    equipment_id=sid("equipment", p.equipment) if p.equipment else None,
                    source_text=f"{p.name} {qty}{p.unit} 사용",
                )
            )
        session.add_all(movements)
    session.flush()
