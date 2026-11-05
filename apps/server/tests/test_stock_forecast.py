"""재고 추이 예측선 (#258, 화면 W-03·W-05)."""

import uuid
from datetime import date, timedelta

from bjk_review import ReviewSnapshot as SnapshotValues
from bjk_server.db.models import PartMetrics, ReviewSnapshot
from bjk_server.domain.forecast import PROJECTION_DAYS, forecast_days, project_stock
from bjk_server.jobs.runner import run_job
from bjk_server.reviews.pdf import stock_projection
from bjk_server.seed.demo import demo_id
from sqlalchemy import select
from sqlalchemy.orm import Session

from .conftest import auth_header
from .test_review_run import NIGHTLY_AT, _create, _run, fresh  # noqa: F401

P6205 = demo_id("part", "6205")


def test_project_stock_uses_monthly_use_and_lead_day():
    with_order, without = project_stock(10, 30, 5, 3)
    assert len(without) == PROJECTION_DAYS + 1
    assert without[:3] == [10, 9, 8]
    assert with_order[2] == without[2]
    assert with_order[3] == without[3] + 5
    days = forecast_days(date(2026, 11, 4), 10, 30, 5, 3)
    assert (days[0].date, days[-1].date) == (date(2026, 11, 4), date(2026, 12, 30))


def test_review_forecast_matches_pdf_projection(client, fresh):  # noqa: F811
    review_id = _create(fresh)
    _run(fresh, review_id)
    res = client.get(f"/api/v1/reviews/{review_id}/forecast", headers=auth_header("manager"))
    assert res.status_code == 200, res.text
    body = res.json()
    with Session(fresh.admin) as s:
        values = s.scalar(
            select(ReviewSnapshot.values).where(ReviewSnapshot.review_id == review_id)
        )
    snapshot = SnapshotValues.model_validate(values)
    proposal = client.get(f"/api/v1/reviews/{review_id}", headers=auth_header("manager")).json()[
        "proposal"
    ]
    assert body["order_qty"] == proposal["qty"]  # 수정안 수량, 그 공급사 LT90
    assert body["lead_days"] == snapshot.offer(proposal["supplier"]["id"]).lt90
    with_order, without = stock_projection(snapshot, body["order_qty"], body["lead_days"])
    assert [d["with_order"] for d in body["days"]] == with_order
    assert [d["without_order"] for d in body["days"]] == without
    assert body["days"][0]["date"] == snapshot.as_of.isoformat()
    worker = client.get(f"/api/v1/reviews/{review_id}/forecast", headers=auth_header("worker"))
    assert worker.json() == body  # 본인 요청은 작업자도 본다


def test_review_forecast_errors(client, fresh):  # noqa: F811
    reviewing = _create(fresh)
    res = client.get(f"/api/v1/reviews/{reviewing}/forecast", headers=auth_header("manager"))
    assert (res.status_code, res.json()["code"]) == (409, "REVIEW_NOT_DECIDABLE")
    other = client.get(f"/api/v1/reviews/{uuid.uuid4()}/forecast", headers=auth_header("manager"))
    assert other.status_code == 404
    _run(fresh, reviewing)
    worker2 = client.get(f"/api/v1/reviews/{reviewing}/forecast", headers=auth_header("worker2"))
    assert worker2.status_code == 404


def test_part_forecast_from_latest_metrics(client, demo_db):
    demo_db.reseed()
    before = client.get(f"/api/v1/parts/{P6205}/forecast", headers=auth_header("worker")).json()
    assert (before["computed_at"], before["days"]) == (None, [])
    assert run_job(demo_db.app, "nightly", "manual", now=NIGHTLY_AT).status == "ok"
    body = client.get(f"/api/v1/parts/{P6205}/forecast", headers=auth_header("worker")).json()
    with Session(demo_db.admin) as s:
        m = s.scalar(select(PartMetrics).where(PartMetrics.part_id == P6205))
    assert (body["order_qty"], body["lead_days"], body["reorder_point"]) == (
        m.recommended_qty,
        m.lt90,
        m.reorder_point,
    )
    assert body["start_stock"] == m.stock + m.hidden_confirmed
    assert len(body["days"]) == PROJECTION_DAYS + 1
    first, lead = body["days"][0], body["days"][m.lt90]
    assert first["without_order"] == body["start_stock"]
    assert lead["with_order"] - lead["without_order"] == m.recommended_qty
    assert date.fromisoformat(body["days"][1]["date"]) - date.fromisoformat(
        first["date"]
    ) == timedelta(days=1)


def test_unknown_part_forecast_is_404(client, demo_db):
    res = client.get(f"/api/v1/parts/{uuid.uuid4()}/forecast", headers=auth_header("worker"))
    assert res.status_code == 404
