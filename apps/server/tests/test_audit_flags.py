from datetime import UTC, datetime, timedelta

import pytest
from bjk_server import clock
from bjk_server.db.models import AuditFlag
from bjk_server.jobs import registry  # noqa: F401
from bjk_server.jobs.runner import run_job
from bjk_server.seed.demo import PARTS, demo_id
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .conftest import auth_header

NOW = datetime(2026, 11, 3, 18, 0, tzinfo=UTC)  # 2026-11-04 03:00 KST
URL = "/api/v1/audit-flags"
P20 = demo_id("part", "p20")
MAINTENANCE = demo_id("maintenance", "eq3:-3")


@pytest.fixture
def nightly(demo_db):
    demo_db.reseed()

    def run(now=NOW):
        result = run_job(demo_db.app, "nightly", "manual", now=now)
        assert result.status == "ok", result.error
        return result.summary

    return run


def _flags(client, user="manager", **params):
    res = client.get(URL, params=params, headers=auth_header(user))
    assert res.status_code == 200, res.text
    return res.json()["items"]


def _open_count(demo_db) -> int:
    with Session(demo_db.admin) as s:
        stmt = select(func.count()).select_from(AuditFlag).where(AuditFlag.status != "closed")
        return s.scalar(stmt)


def test_nightly_flags_maintenance_without_linked_out(nightly, client):
    assert nightly()["audit_flags_created"] == len(PARTS)
    first = _flags(client)[0]
    assert first["part"] == {"id": str(P20), "name": "오링 P-20"}
    assert (first["rule"], first["level"], first["status"]) == (
        "MAINTENANCE_OUT_MISMATCH",
        "high",
        "open",
    )
    assert first["evidence"] == {
        "maintenance_id": str(MAINTENANCE),
        "completed_at": "2026-11-01T15:00:00+09:00",
        "required_qty": 100,
        "linked_out_qty": 0,
    }
    # 같은 부품의 실사 경과도 열린 항목 하나에 묶인다.
    assert [r["rule"] for r in first["related"]] == ["COUNT_OVERDUE"]


def test_rerun_does_not_duplicate_open_flags(nightly, demo_db):
    nightly()
    assert nightly()["audit_flags_created"] == 0
    assert _open_count(demo_db) == len(PARTS)


def test_list_sorted_by_level_and_filtered(nightly, client):
    nightly()
    items = _flags(client)
    assert [i["level"] for i in items] == ["high"] + ["low"] * (len(PARTS) - 1)
    assert [i["part"]["name"] for i in _flags(client, level="high")] == ["오링 P-20"]
    assert len(_flags(client, rule="COUNT_OVERDUE")) == len(PARTS) - 1
    assert _flags(client, status="closed") == []
    pages, cursor = [], None
    while True:
        res = client.get(
            URL,
            params={"limit": 2} | ({"cursor": cursor} if cursor else {}),
            headers=auth_header("manager"),
        ).json()
        pages += [i["id"] for i in res["items"]]
        if not (cursor := res["next_cursor"]):
            break
    assert pages == [i["id"] for i in items]


def test_worker_cannot_list(client):
    res = client.get(URL, headers=auth_header("worker"))
    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN_ROLE"


def test_parts_list_marks_open_flags_as_suspect(nightly, client, demo_db):
    nightly()
    with Session(demo_db.admin) as s, s.begin():
        s.execute(
            update(AuditFlag)
            .where(AuditFlag.part_id != P20)
            .values(status="closed", closed_at=NOW, resolution="no_diff")
        )
    res = client.get(
        "/api/v1/parts", params={"ledger_status": "suspect"}, headers=auth_header("worker")
    )
    items = res.json()["items"]
    assert [(i["name"], i["ledger_status"]) for i in items] == [("오링 P-20", "suspect")]
    normal = client.get(
        "/api/v1/parts", params={"ledger_status": "normal"}, headers=auth_header("worker")
    ).json()["items"]
    assert len(normal) == len(PARTS) - 1


def test_closed_rule_flags_are_suppressed_then_return(nightly, demo_db):
    nightly()
    with Session(demo_db.admin) as s, s.begin():
        s.execute(update(AuditFlag).values(status="closed", closed_at=NOW, resolution="no_diff"))
    # 다음 날: 실사 경과는 30일 억제, 이미 다룬 정비 사건은 다시 뜨지 않음
    assert nightly(NOW + timedelta(days=1))["audit_flags_created"] == 0
    assert nightly(NOW + timedelta(days=31))["audit_flags_created"] == len(PARTS)
    with Session(demo_db.admin) as s:
        rules = s.scalars(select(AuditFlag.rule).where(AuditFlag.status == "open")).all()
    assert set(rules) == {"COUNT_OVERDUE"}


@pytest.fixture
def form_out(client, demo_db, monkeypatch):
    demo_db.reseed()
    monkeypatch.setattr(clock, "utcnow", lambda: NOW)
    counter = iter(range(1000))

    def post(qty, part="6205"):
        body = {
            "client_message_id": f"neg-{next(counter)}",
            "type": "OUT",
            "part_id": str(demo_id("part", part)),
            "qty": qty,
        }
        res = client.post("/api/v1/chat/entries", json=body, headers=auth_header("worker"))
        assert res.status_code == 200, res.text
        return res.json()

    return post


def test_record_below_zero_creates_flag_immediately(form_out, client, demo_db):
    assert form_out(2)["triggered"]["audit_flag_id"] is None  # 3 → 1
    crossed = form_out(3)  # 1 → -2
    assert crossed["stock_after"] == -2
    flag_id = crossed["triggered"]["audit_flag_id"]
    assert flag_id is not None
    # 이미 음수인 상태의 추가 출고는 새로 띄우지 않는다.
    assert form_out(1)["triggered"]["audit_flag_id"] is None

    item = next(i for i in _flags(client) if i["id"] == flag_id)
    assert (item["rule"], item["level"], item["part"]["name"]) == (
        "NEGATIVE_STOCK",
        "high",
        "볼베어링 6205ZZ",
    )
    assert item["evidence"]["movement_id"] == crossed["movement"]["id"]

    # 새벽 배치는 같은 원장 행을 다시 의심 항목으로 만들지 않고 같은 항목에 묶는다.
    run_job(demo_db.app, "nightly", "manual", now=NOW + timedelta(minutes=1))
    with Session(demo_db.admin) as s:
        flags = s.scalars(
            select(AuditFlag).where(AuditFlag.part_id == demo_id("part", "6205"))
        ).all()
    assert len(flags) == 1
    assert flags[0].rule == "NEGATIVE_STOCK"
    assert [r["rule"] for r in flags[0].related] == ["COUNT_OVERDUE"]
