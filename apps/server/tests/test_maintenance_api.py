import uuid
from datetime import UTC, datetime

import pytest
from bjk_server.db.models import Maintenance, PartMetrics
from bjk_server.jobs import registry  # noqa: F401
from bjk_server.jobs.runner import run_job
from bjk_server.seed.demo import demo_id
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .conftest import auth_header

URL = "/api/v1/maintenance"
EQ1 = demo_id("equipment", "eq1")
UPCOMING = demo_id("maintenance", "eq3:16")  # 2026-11-20
DONE = demo_id("maintenance", "eq3:-3")  # 2026-11-01 완료
NIGHTLY = datetime(2026, 11, 3, 18, 0, tzinfo=UTC)


@pytest.fixture
def fresh(demo_db):
    demo_db.reseed()


def _call(client, method, path="", user="manager", **kwargs):
    return client.request(method, f"{URL}{path}", headers=auth_header(user), **kwargs)


def test_lists_by_date_with_effective_parts(client, fresh):
    items = _call(client, "GET").json()["items"]
    assert [(m["equipment"]["name"], m["scheduled_date"]) for m in items] == [
        ("3호기", "2026-11-01"),
        ("3호기", "2026-11-20"),
        ("2호기", "2026-12-04"),
    ]
    done, upcoming = items[0], items[1]
    assert (done["parts_source"], [p["qty"] for p in done["parts"]]) == ("schedule", [100])
    assert done["completed_at"] is not None
    assert upcoming["parts_source"] == "equipment"
    assert [(p["name"], p["qty"]) for p in upcoming["parts"]] == [
        ("볼베어링 6205ZZ", 4),
        ("오링 P-20", 100),
    ]


def test_filters(client, fresh):
    def names(**params):
        res = _call(client, "GET", params=params)
        return [m["scheduled_date"] for m in res.json()["items"]]

    assert names(completed="false") == ["2026-11-20", "2026-12-04"]
    assert names(**{"from": "2026-11-02", "to": "2026-11-30"}) == ["2026-11-20"]
    assert names(equipment_id=str(demo_id("equipment", "eq2"))) == ["2026-12-04"]


def test_created_schedule_feeds_nightly_f(client, demo_db, fresh):
    part = demo_id("part", "6204")
    res = _call(
        client,
        "POST",
        json={
            "equipment_id": str(EQ1),
            "scheduled_date": "2026-11-10",
            "required_parts": [{"part_id": str(part), "qty": 3}],
        },
    )
    assert res.status_code == 201, res.text
    assert res.json()["parts_source"] == "schedule"
    assert run_job(demo_db.app, "nightly", "manual", now=NIGHTLY).status == "ok"
    with Session(demo_db.admin) as s:
        f_items = s.scalar(select(PartMetrics.f_items).where(PartMetrics.part_id == part))
    assert [(f["date"], f["qty"]) for f in f_items] == [("2026-11-10", 3)]


def test_update_and_reset_required_parts(client, fresh):
    part = str(demo_id("part", "6205"))
    res = _call(
        client,
        "PATCH",
        f"/{UPCOMING}",
        json={"scheduled_date": "2026-11-21", "required_parts": [{"part_id": part, "qty": 2}]},
    ).json()
    assert (res["scheduled_date"], res["parts_source"]) == ("2026-11-21", "schedule")
    reset = _call(client, "PATCH", f"/{UPCOMING}", json={"required_parts": None}).json()
    assert (reset["parts_source"], reset["required_parts"]) == ("equipment", None)


def test_completed_schedule_is_locked(client, fresh):
    res = _call(client, "PATCH", f"/{DONE}", json={"scheduled_date": "2026-11-02"})
    assert res.status_code == 409
    assert res.json()["detail"]["status"] == "completed"
    assert _call(client, "DELETE", f"/{DONE}").status_code == 409


def test_delete_only_unlinked_schedule(client, demo_db, fresh):
    with Session(demo_db.admin) as s, s.begin():
        s.execute(
            update(Maintenance)
            .where(Maintenance.id == UPCOMING)
            .values(scheduled_date=datetime.now(UTC).date())
        )
    body = {
        "client_message_id": "mt-link",
        "type": "OUT",
        "part_id": str(demo_id("part", "p20")),
        "qty": 1,
        "equipment_id": str(demo_id("equipment", "eq3")),
    }
    out = client.post("/api/v1/chat/entries", json=body, headers=auth_header("worker")).json()
    assert out["movement"]["maintenance_id"] == str(UPCOMING)
    assert _call(client, "DELETE", f"/{UPCOMING}").json()["detail"] == {"status": "linked"}
    other = demo_id("maintenance", "eq2:30")
    assert _call(client, "DELETE", f"/{other}").status_code == 204
    assert _call(client, "GET", f"/{other}").status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"equipment_id": str(EQ1)},
        {
            "equipment_id": str(EQ1),
            "scheduled_date": "2026-11-10",
            "required_parts": [{"part_id": str(demo_id("part", "6204")), "qty": 0}],
        },
    ],
    ids=["no-date", "zero-qty"],
)
def test_invalid_schedule_is_400(client, fresh, body):
    assert _call(client, "POST", json=body).status_code == 400


def test_unknown_equipment_is_404_and_worker_403(client, fresh):
    body = {"equipment_id": str(uuid.uuid4()), "scheduled_date": "2026-11-10"}
    assert _call(client, "POST", json=body).status_code == 404
    assert _call(client, "GET", user="worker").status_code == 403
