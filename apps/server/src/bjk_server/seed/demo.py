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
    Category,
    Company,
    CompanySettings,
    Equipment,
    EquipmentPart,
    Maintenance,
    Movement,
    Part,
    PartAlias,
    Supplier,
    SupplierPart,
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
DEFAULT_SUPPLIER = {"6205": "a", "6204": "a", "a42": "a", "m820": "a", "p20": "b", "oil": "a"}

# (설비, 이름, 시간당 손실, 가동 시간, [(부품, 정비 1회당 수량)])
EQUIPMENT = (
    ("eq1", "1호기", 30000, 16, [("6204", 2)]),
    ("eq2", "2호기", 20000, 8, [("a42", 2)]),
    ("eq3", "3호기", 50000, 16, [("6205", 4), ("p20", 100)]),
)

# (설비, 오늘부터 며칠 뒤)
MAINTENANCE = (("eq3", 16), ("eq2", 30))

ALIASES = (("베어링 작은 거", "6205", 3),)


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
        # 시작 재고는 현재 재고에서 거꾸로 맞춘다: 시작 + 입고 - 출고 = 현재
        used = sum(q for _, q in outs)
        refill = 0
        if used > p.stock:
            refill = (p.pack_qty or 1) * -(-(used - p.stock) // (p.pack_qty or 1))
        opening = p.stock + used - refill
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
                    occurred_at=_at(start + timedelta(weeks=HISTORY_WEEKS // 2), 14),
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
