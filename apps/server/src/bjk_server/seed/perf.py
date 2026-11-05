"""부품 N종 성능 측정 (기능명세서 17장: 배치 1,000종 5분, 채팅 응답 3초).

`python -m bjk_server.seed.perf --parts 1000`

시연 시드(demo_v1) 위에 합성 부품과 52주 출고 이력을 더한 뒤, 새벽 배치와 채팅 매칭 시간을 잰다.
개발 DB를 초기화하므로 APP_ENV=dev에서만 실행한다. 측정 전용 데이터이며 운영 데이터로 쓰지 않는다.
"""

import argparse
import random
import statistics
import sys
import time
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import create_engine, insert
from sqlalchemy.orm import Session

from bjk_server import clock
from bjk_server.auth import set_tenant
from bjk_server.chat.interpreter import Interpretation
from bjk_server.chat.service import handle_message
from bjk_server.clock import KST
from bjk_server.config import get_settings
from bjk_server.db.models import Movement, Part, PartAlias, SupplierPart
from bjk_server.jobs import registry  # noqa: F401 - 작업 등록
from bjk_server.jobs.runner import run_job
from bjk_server.security import TokenClaims
from bjk_server.seed.demo import CATEGORIES, COMPANY_CODE, PARTS, SUPPLIERS, demo_id, seed_demo

HISTORY_WEEKS = 52
# (주마다 출고가 있을 확률, 주간 평균 출고량) — smooth·intermittent·lumpy 섞기
PROFILES = ((0.9, 20), (0.4, 3), (0.2, 15), (0.7, 6))


def seed_perf(session: Session, parts: int, today: date) -> list[str]:
    """시연 시드에 합성 부품을 더해 부품을 parts종으로 맞춘다. 합성 부품 이름 목록을 돌려준다."""
    seed_demo(session, today=today)
    rng = random.Random(f"perf:{parts}")
    company_id = demo_id("company", COMPANY_CODE)
    worker_id = demo_id("user", "worker")
    start = today - timedelta(weeks=HISTORY_WEEKS)
    names, part_rows, alias_rows, supplier_rows, movement_rows = [], [], [], [], []
    for i in range(parts - len(PARTS)):
        part_id = uuid.uuid4()
        category = CATEGORIES[i % len(CATEGORIES)][0]
        name = f"합성부품 {i:04d}"
        names.append(name)
        part_rows.append(
            {
                "id": part_id,
                "company_id": company_id,
                "category_id": demo_id("category", category),
                "default_supplier_id": demo_id("supplier", "a"),
                "name": name,
                "spec": {"code": f"S{i:04d}"},
                "unit": "개",
            }
        )
        alias_rows.append(
            {"company_id": company_id, "part_id": part_id, "text": f"부품{i}", "confirmed_count": 1}
        )
        for supplier, _, _, _ in SUPPLIERS:
            supplier_rows.append(
                {
                    "company_id": company_id,
                    "supplier_id": demo_id("supplier", supplier),
                    "part_id": part_id,
                    "unit_price": rng.randrange(100, 50000),
                    "moq": rng.choice((1, 10, 100)),
                }
            )
        chance, weekly = PROFILES[i % len(PROFILES)]
        outs = []
        for week in range(HISTORY_WEEKS, 0, -1):
            if rng.random() < chance:
                qty = max(1, round(rng.gauss(weekly / chance, weekly * 0.3)))
                day = today - timedelta(weeks=week) + timedelta(days=rng.randrange(5))
                outs.append((day, qty))
        opening = sum(q for _, q in outs) + rng.randrange(0, 50)
        movement_rows.append(
            {
                "company_id": company_id,
                "part_id": part_id,
                "type": "ADJUST",
                "qty": opening,
                "occurred_at": datetime.combine(start, datetime.min.time(), tzinfo=KST),
                "reason": "초기 재고 이관",
            }
        )
        for day, qty in outs:
            movement_rows.append(
                {
                    "company_id": company_id,
                    "part_id": part_id,
                    "type": "OUT",
                    "qty": -qty,
                    "occurred_at": datetime.combine(day, datetime.min.time(), tzinfo=KST)
                    + timedelta(hours=10),
                    "author_id": worker_id,
                    "source_text": f"{name} {qty}개 사용",
                }
            )
    for model, rows in (
        (Part, part_rows),
        (PartAlias, alias_rows),
        (SupplierPart, supplier_rows),
        (Movement, movement_rows),
    ):
        if rows:
            session.execute(insert(model), rows)
    return names


class _Parsed:
    """해석 결과를 고정해 LLM 없이 매칭·카드 생성 시간만 잰다."""

    def __init__(self, part_text: str) -> None:
        self.result = Interpretation("OUT", part_text, 2)

    def interpret(self, text: str) -> Interpretation:
        return self.result


def measure_chat(app_engine, names: list[str], runs: int) -> list[float]:
    """채팅 메시지 처리(해석 결과 고정 → 매칭 → 확인 카드) 시간(초). 기록은 롤백한다."""
    user = TokenClaims(
        user_id=demo_id("user", "worker"),
        company_id=demo_id("company", COMPANY_CODE),
        role="worker",
        type="access",
        jti="perf",
    )
    texts = [names[i * len(names) // runs] for i in range(runs)] if names else ["6205"] * runs
    elapsed = []
    for i, part_text in enumerate(texts):
        with Session(app_engine) as session:
            set_tenant(session, user.company_id)
            started = time.perf_counter()
            handle_message(session, user, f"perf-{i}", f"{part_text} 2개 씀", _Parsed(part_text))
            session.flush()
            elapsed.append(time.perf_counter() - started)
            session.rollback()
    return elapsed


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m bjk_server.seed.perf")
    parser.add_argument("--parts", type=int, default=1000)
    parser.add_argument("--chat-runs", type=int, default=20)
    args = parser.parse_args()

    settings = get_settings()
    if not settings.is_dev:
        print("APP_ENV=dev에서만 실행할 수 있습니다.", file=sys.stderr)
        return 1
    admin = create_engine(settings.admin_database_url or settings.database_url)
    app = create_engine(settings.database_url)
    now = clock.utcnow()
    today = now.astimezone(KST).date()

    started = time.perf_counter()
    with Session(admin) as session, session.begin():
        names = seed_perf(session, args.parts, today)
    seeded = time.perf_counter() - started

    started = time.perf_counter()
    result = run_job(app, "nightly", "manual", now=now)
    nightly = time.perf_counter() - started
    chat = measure_chat(app, names, args.chat_runs)

    print(f"parts: {args.parts}, seed: {seeded:.1f}s")
    print(f"nightly: {result.status} {nightly:.1f}s {result.summary}")
    print(
        f"chat ({len(chat)} runs): median {statistics.median(chat) * 1000:.0f}ms, "
        f"max {max(chat) * 1000:.0f}ms"
    )
    admin.dispose()
    app.dispose()
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
