from datetime import timedelta

import pytest
from bjk_server import clock
from bjk_server.db.models import AuditFlag, CountRequest, Movement
from bjk_server.jobs.runner import run_job
from bjk_server.seed.demo import demo_id
from sqlalchemy import select
from sqlalchemy.orm import Session

from .conftest import auth_header, watch_stock_events
from .test_count_requests import NIGHTLY, NOW, _request, flags  # noqa: F401

P20 = demo_id("part", "p20")


def _answer(client, request_id, qty, user="worker"):
    return client.post(
        f"/api/v1/count-requests/{request_id}/answer",
        json={"counted_qty": qty},
        headers=auth_header(user),
    )


def _p20_request(client, flags):  # noqa: F811
    return _request(client, flags["오링 P-20"]).json()["count_request_id"]


def _stock(client, name):
    items = client.get("/api/v1/parts", params={"q": name}, headers=auth_header("worker"))
    return items.json()["items"][0]["stock"]


def test_answer_reveals_diff_and_adjusts_ledger(client, flags, demo_db):  # noqa: F811
    request_id = _p20_request(client, flags)
    events = watch_stock_events(demo_db)
    res = _answer(client, request_id, 940)
    assert res.status_code == 200, res.text
    assert events() == [{"part_id": str(P20), "stock": 940}]
    body = res.json()
    assert {k: body[k] for k in ("book_qty_before", "counted_qty", "diff", "reason_required")} == {
        "book_qty_before": 1040,
        "counted_qty": 940,
        "diff": -100,
        "reason_required": True,
    }
    assert body["reply"] == "장부보다 100개 적어요. 이유를 골라 주세요."
    assert _stock(client, "오링 P-20") == 940
    with Session(demo_db.admin) as s:
        movement = s.get(Movement, body["adjust_movement_id"])
        assert (movement.type, movement.qty, movement.reason) == ("ADJUST", -100, "실사조정")
        assert movement.author_id == demo_id("user", "worker")
        assert s.get(CountRequest, request_id).status == "answered"
        flag = s.scalar(select(AuditFlag).where(AuditFlag.part_id == P20))
        assert flag.status == "count_requested"  # 사유를 받을 때까지 열어 둔다

    again = _answer(client, request_id, 940)
    assert again.status_code == 409
    assert again.json()["detail"] == {"status": "answered"}


def test_no_diff_closes_flag_and_suppresses_rules(client, flags, demo_db):  # noqa: F811
    request_id = _p20_request(client, flags)
    events = watch_stock_events(demo_db)
    body = _answer(client, request_id, 1040).json()
    assert body["diff"] == 0
    assert events() == []
    assert body["reason_required"] is False
    assert body["adjust_movement_id"] is None
    assert body["reply"] == "장부와 같아요. 이상 없음으로 처리했어요."
    closed = client.get(
        "/api/v1/audit-flags", params={"status": "closed"}, headers=auth_header("manager")
    ).json()["items"]
    assert [f["part"]["name"] for f in closed] == ["오링 P-20"]

    # 다음 날 새벽: 같은 정비 사건도, 실사 경과도 다시 뜨지 않는다.
    assert run_job(demo_db.app, "nightly", "manual", now=NIGHTLY + timedelta(days=1)).status == "ok"
    with Session(demo_db.admin) as s:
        open_p20 = s.scalars(
            select(AuditFlag).where(AuditFlag.part_id == P20, AuditFlag.status != "closed")
        ).all()
    assert open_p20 == []


def test_count_resets_overdue_rule(client, flags, demo_db):  # noqa: F811
    _answer(client, _p20_request(client, flags), 1040)
    # 억제 기간(30일)이 지나도 마지막 실사가 31일 전이라 실사 경과에 걸리지 않는다.
    assert (
        run_job(demo_db.app, "nightly", "manual", now=NIGHTLY + timedelta(days=31)).status == "ok"
    )
    with Session(demo_db.admin) as s:
        rules = s.scalars(
            select(AuditFlag.rule).where(AuditFlag.part_id == P20, AuditFlag.status != "closed")
        ).all()
    assert rules == []


def test_only_assignee_can_answer(client, flags):  # noqa: F811
    request_id = _p20_request(client, flags)
    res = _answer(client, request_id, 940, user="worker2")
    assert res.status_code == 404


def test_scheduled_request_opens_at_scheduled_time(client, flags, monkeypatch):  # noqa: F811
    names = ["볼베어링 6205ZZ", "볼베어링 6204ZZ", "오링 P-20"]
    third = [_request(client, flags[n]).json() for n in names][-1]
    assert third["status"] == "scheduled"
    assert _answer(client, third["count_request_id"], 1040).status_code == 404
    monkeypatch.setattr(clock, "utcnow", lambda: NOW + timedelta(days=1))
    assert _answer(client, third["count_request_id"], 1040).status_code == 200


def test_negative_count_is_rejected(client, flags):  # noqa: F811
    assert _answer(client, _p20_request(client, flags), -1).status_code == 400


@pytest.fixture(autouse=True)
def _reset_clock(monkeypatch):
    monkeypatch.setattr(clock, "utcnow", lambda: NOW)
