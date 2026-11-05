import uuid
from datetime import UTC, date, datetime

import pytest
from bjk_server import clock
from bjk_server.clock import KST
from bjk_server.db.models import Maintenance
from bjk_server.domain.ledger import MaintenanceSlot, pick_maintenance
from bjk_server.seed.demo import demo_id
from sqlalchemy import update
from sqlalchemy.orm import Session

from .conftest import auth_header

A, B = uuid.uuid4(), uuid.uuid4()
MAINTENANCE = demo_id("maintenance", "eq3:16")  # 시드: 3호기 2026-11-20 정비 (DEMO_TODAY + 16일)


def _at(day, hour=10):
    return datetime(2026, 11, day, hour, tzinfo=KST)


@pytest.mark.parametrize(
    ("occurred_day", "expected"),
    [(19, A), (20, A), (21, A), (18, None), (22, None)],
)
def test_schedule_window_is_plus_minus_one_day(occurred_day, expected):
    slots = [MaintenanceSlot(A, date(2026, 11, 20), None)]
    assert pick_maintenance(_at(occurred_day), date(2026, 11, occurred_day), slots) == expected


def test_within_48_hours_after_completion():
    slots = [MaintenanceSlot(A, date(2026, 11, 10), _at(20, 15))]
    assert pick_maintenance(_at(22, 14), date(2026, 11, 22), slots) == A  # 47시간 뒤
    assert pick_maintenance(_at(22, 16), date(2026, 11, 22), slots) is None  # 49시간 뒤
    assert pick_maintenance(_at(20, 14), date(2026, 11, 20), slots) is None  # 완료 전


def test_closest_maintenance_wins():
    slots = [
        MaintenanceSlot(A, date(2026, 11, 19), None),
        MaintenanceSlot(B, date(2026, 11, 20), None),
    ]
    assert pick_maintenance(_at(20), date(2026, 11, 20), slots) == B


@pytest.fixture
def form_out(client, demo_db, monkeypatch):
    demo_db.reseed()
    counter = iter(range(1000))

    def post(when, equipment="eq3"):
        monkeypatch.setattr(clock, "utcnow", lambda: when.astimezone(UTC))
        body = {
            "client_message_id": f"link-{next(counter)}",
            "type": "OUT",
            "part_id": str(demo_id("part", "p20")),
            "qty": 1,
            "equipment_id": str(demo_id("equipment", equipment)) if equipment else None,
        }
        return client.post("/api/v1/chat/entries", json=body, headers=auth_header("worker"))

    return post


def test_out_near_schedule_links_maintenance(form_out):
    res = form_out(_at(19))
    assert res.json()["movement"]["maintenance_id"] == str(MAINTENANCE)


@pytest.mark.parametrize(
    ("when", "equipment"),
    [(_at(17), "eq3"), (_at(19), "eq2"), (_at(19), None)],
    ids=["outside-window", "other-equipment", "no-equipment"],
)
def test_out_not_linked(form_out, when, equipment):
    assert form_out(when, equipment).json()["movement"]["maintenance_id"] is None


def test_out_after_completion_links(form_out, demo_db):
    with Session(demo_db.admin) as s, s.begin():
        s.execute(
            update(Maintenance)
            .where(Maintenance.id == MAINTENANCE)
            .values(scheduled_date=date(2026, 11, 10), completed_at=_at(20, 15))
        )
    assert form_out(_at(22, 14)).json()["movement"]["maintenance_id"] == str(MAINTENANCE)
    assert form_out(_at(22, 16)).json()["movement"]["maintenance_id"] is None
