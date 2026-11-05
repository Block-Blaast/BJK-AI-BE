"""검토 목록 (API 명세서 REV-01)."""

from datetime import timedelta

import pytest
from bjk_server.seed.demo import demo_id
from sqlalchemy.orm import Session

from .conftest import auth_header
from .review_rows import COMPUTED_AT, add_review

URL = "/api/v1/reviews"


@pytest.fixture
def reviews(demo_db):
    """긴급·손실 작음, 일반·손실 큼, worker2 요청, 시스템 초안(보류)."""
    demo_db.reseed()
    with Session(demo_db.admin) as s, s.begin():
        urgent = add_review(s)
        urgent.flags, urgent.loss = ["urgent"], 100
        big = add_review(s, created_at=COMPUTED_AT + timedelta(minutes=1))
        big.loss = 9_000_000
        other = add_review(s, requested_by=demo_id("user", "worker2"))
        other.loss = 5_000
        draft = add_review(s, entry="stock_draft", status="held")
        draft.verdict = "hold"
        return {"urgent": urgent.id, "big": big.id, "other": other.id, "draft": draft.id}


def _ids(client, query="", user="manager"):
    res = client.get(URL + query, headers=auth_header(user))
    assert res.status_code == 200, res.text
    return [i["id"] for i in res.json()["items"]]


def test_urgent_first_then_loss(client, reviews):
    ids = _ids(client)
    assert ids[0] == str(reviews["urgent"])
    assert ids[1] == str(reviews["big"])
    assert ids.index(str(reviews["other"])) < ids.index(str(reviews["draft"]))


def test_item_shape(client, reviews):
    item = client.get(URL, headers=auth_header("manager")).json()["items"][0]
    assert item["part"] == "V벨트 A-42" and item["entry"] == "staff_request"
    assert item["original_total"] == 540000 and item["saving"] == 540000
    assert item["created_at"] == "2026-11-04T03:00:00+09:00"


def test_worker_sees_own_requests_only(client, reviews):
    ids = set(_ids(client, user="worker"))
    assert ids == {str(reviews["urgent"]), str(reviews["big"])}
    assert set(_ids(client, user="worker2")) == {str(reviews["other"])}


def test_filters(client, reviews):
    assert _ids(client, "?urgent=true") == [str(reviews["urgent"])]
    assert str(reviews["urgent"]) not in _ids(client, "?urgent=false")
    assert _ids(client, "?entry=stock_draft") == [str(reviews["draft"])]
    assert _ids(client, "?status=held&verdict=hold") == [str(reviews["draft"])]
    assert _ids(client, "?mine=true") == []
    assert set(_ids(client, "?mine=true", user="worker2")) == {str(reviews["other"])}


@pytest.mark.parametrize("query", ["?status=done", "?verdict=maybe", "?entry=x", "?limit=0"])
def test_invalid_filter_is_400(client, reviews, query):
    res = client.get(URL + query, headers=auth_header("manager"))
    assert res.status_code == 400
    assert res.json()["code"] == "VALIDATION_ERROR"


def test_cursor_pages_keep_order(client, reviews):
    full = _ids(client)
    first = client.get(URL + "?limit=2", headers=auth_header("manager")).json()
    second = client.get(
        URL + f"?limit=2&cursor={first['next_cursor']}", headers=auth_header("manager")
    ).json()
    assert [i["id"] for i in first["items"] + second["items"]] == full
    assert second["next_cursor"] is None
