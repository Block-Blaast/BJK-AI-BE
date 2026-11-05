"""3D 창고 배치·예측 (W-11, #281)."""

from datetime import date, timedelta

import pytest
from bjk_server import clock
from bjk_server.domain.twin import BinInput, project_bin, project_equipment
from bjk_server.seed.demo import demo_id

from .conftest import auth_header
from .test_review_run import NOW, _create, _run, fresh  # noqa: F401

BASE = date(2026, 11, 4)


def _bin(**kw):
    values = dict(
        stock=10, daily=1.0, cv=0.25, lt90=7, reorder_point=5, arrivals=[], maintenance=[]
    )
    return BinInput(**{**values, **kw})


def test_path_consumes_daily_and_marks_status():
    path = project_bin(_bin(), BASE, horizon=12)
    assert path.qty[:4] == [10, 9, 8, 7]
    assert path.status[0] in ("normal", "risk")
    assert path.status[5] in ("low", "risk")
    assert path.status[10] == "out" and path.qty[12] == 0
    assert all(0.01 <= p <= 0.99 for p in path.p_out)
    assert path.p_out[9] > path.p_out[0]


def test_arrivals_and_maintenance_move_stock_on_their_day():
    path = project_bin(
        _bin(
            daily=0.0,
            arrivals=[(BASE + timedelta(days=2), 5)],
            maintenance=[(BASE + timedelta(days=3), 4)],
        ),
        BASE,
        horizon=4,
    )
    assert path.qty == [10, 10, 15, 11, 11]


def test_part_without_use_never_runs_out():
    path = project_bin(_bin(stock=0, daily=0.0, reorder_point=None), BASE, horizon=3)
    assert path.status == ["normal"] * 4
    assert path.p_out == [0.0] * 4


def test_equipment_goes_down_when_a_part_runs_out():
    bins = {"a": project_bin(_bin(stock=1), BASE, horizon=3)}
    days = project_equipment(["a", "missing"], bins, {"a": 5}, 100_000, horizon=3)
    assert days[0].status in ("normal", "warn")
    assert days[1].status == "down"
    assert days[1].loss == 500_000 and days[1].causes == ["a"]
    assert project_equipment(["a"], bins, {}, 0, horizon=3)[1].loss is None


@pytest.fixture
def at(monkeypatch):
    monkeypatch.setattr(clock, "utcnow", lambda: NOW)


def test_layout_has_racks_equipment_and_placed_parts(client, fresh, at):  # noqa: F811
    res = client.get("/api/v1/twin/layout", headers=auth_header("manager"))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["size"] == {"width": 22, "depth": 18}
    assert [r["id"] for r in body["racks"]] == ["A-01", "B-01", "B-02", "C-01", "C-02"]
    names = {e["name"]: e for e in body["equipment"]}
    assert set(names) == {"1호기", "2호기", "3호기"}
    assert set(names["3호기"]["part_ids"]) == {
        str(demo_id("part", "6205")),
        str(demo_id("part", "p20")),
    }
    assert len(body["placements"]) == 6
    assert {"part_id", "rack_id", "level", "slot"} == set(body["placements"][0])


def test_worker_cannot_see_twin(client, fresh, at):  # noqa: F811
    for path in ("/api/v1/twin/layout", "/api/v1/twin/projection"):
        assert client.get(path, headers=auth_header("worker")).status_code == 403


def test_projection_covers_every_part_for_eight_weeks(client, fresh, at):  # noqa: F811
    res = client.get("/api/v1/twin/projection", headers=auth_header("manager"))
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["base_date"], body["horizon_days"], body["is_mock"]) == ("2026-11-04", 56, False)
    assert body["computed_at"] is not None
    assert len(body["bins"]) == 6
    assert all(len(b["qty"]) == len(b["status"]) == len(b["p_out"]) == 57 for b in body["bins"])
    bearing = next(b for b in body["bins"] if b["part_id"] == str(demo_id("part", "6205")))
    assert bearing["maintenance"][0]["equipment"] == "3호기"
    assert len(body["equipment"]) == 3
    assert all(len(e["status"]) == 57 for e in body["equipment"])
    assert all(a["kind"] == "ordered" for a in body["arrivals"])
    # 같은 데이터면 같은 예측
    again = client.get("/api/v1/twin/projection", headers=auth_header("manager")).json()
    assert again == body


def test_with_orders_adds_pending_review_proposal(client, fresh, at):  # noqa: F811
    review_id = _create(fresh)  # V벨트 A-42 30개 → 수정안 10개
    _run(fresh, review_id)
    plain = client.get("/api/v1/twin/projection", headers=auth_header("manager")).json()
    ordered = client.get(
        "/api/v1/twin/projection?with_orders=true", headers=auth_header("manager")
    ).json()
    proposals = [a for a in ordered["arrivals"] if a["kind"] == "proposal"]
    assert [p["review_id"] for p in proposals] == [str(review_id)]
    assert proposals[0]["qty"] > 0
    assert not [a for a in plain["arrivals"] if a["kind"] == "proposal"]
    a42 = str(demo_id("part", "a42"))
    after = {b["part_id"]: b["qty"][-1] for b in ordered["bins"]}
    before = {b["part_id"]: b["qty"][-1] for b in plain["bins"]}
    assert after[a42] >= before[a42]
