from datetime import timedelta

import pytest
from bjk_server.db.models import Review
from bjk_server.seed.demo import demo_id
from sqlalchemy.orm import Session

from .conftest import auth_header
from .review_rows import COMPUTED_AT, add_review

URL = "/api/v1/reviews"


@pytest.fixture
def rows(demo_db):
    """긴급·손실·생성 시각이 다른 검토 4건. 이름 → id."""
    demo_db.reseed()
    with Session(demo_db.admin) as s, s.begin():
        specs = {
            "big_loss": dict(loss=900_000, flags=["caution"]),
            "urgent_small": dict(loss=10_000, flags=["urgent"]),
            "urgent_big": dict(loss=500_000, flags=["urgent", "alternative"]),
            "draft": dict(loss=900_000, flags=[], entry="stock_draft"),
        }
        ids = {}
        for i, (name, spec) in enumerate(specs.items()):
            entry = spec.pop("entry", "staff_request")
            review = add_review(s, entry=entry, created_at=COMPUTED_AT + timedelta(minutes=i))
            for key, value in spec.items():
                setattr(review, key, value)
            ids[name] = str(review.id)
        other = add_review(s, requested_by=demo_id("user", "worker2"), status="closed")
        other.loss = 0
        ids["other_worker"] = str(other.id)
    yield ids
    demo_db.reseed()


def _ids(client, user="manager", **params) -> list[str]:
    res = client.get(URL, params=params, headers=auth_header(user))
    assert res.status_code == 200, res.text
    return [item["id"] for item in res.json()["items"]]


def test_urgent_first_then_loss_then_latest(client, rows):
    # draft와 big_loss는 손실이 같아 나중에 만든 draft가 앞
    assert _ids(client) == [
        rows["urgent_big"],
        rows["urgent_small"],
        rows["draft"],
        rows["big_loss"],
        rows["other_worker"],
    ]


def test_item_shape(client, rows):
    res = client.get(URL, headers=auth_header("manager")).json()
    item = res["items"][0]
    assert set(item) == {
        "id",
        "entry",
        "part_id",
        "part",
        "status",
        "verdict",
        "flags",
        "qty",
        "original_total",
        "saving",
        "decision",
        "created_at",
    }
    assert item["part"] == "V벨트 A-42"
    assert item["part_id"] == str(demo_id("part", "a42"))
    assert item["qty"] == 30 and item["decision"] is None
    assert item["original_total"] == 540000
    assert item["created_at"].endswith("+09:00")
    assert res["next_cursor"] is None


def test_worker_sees_only_own_requests(client, rows):
    ids = _ids(client, user="worker")
    assert rows["other_worker"] not in ids
    assert rows["draft"] not in ids  # 시스템 초안은 요청자가 없다
    assert set(ids) == {rows["urgent_big"], rows["urgent_small"], rows["big_loss"]}


def test_mine_filter_for_manager(client, rows):
    assert _ids(client, mine="true") == []
    assert set(_ids(client, user="worker2", mine="true")) == {rows["other_worker"]}


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"urgent": "true"}, ["urgent_big", "urgent_small"]),
        ({"urgent": "false"}, ["draft", "big_loss", "other_worker"]),
        ({"entry": "stock_draft"}, ["draft"]),
        ({"status": "closed"}, ["other_worker"]),
        ({"verdict": "hold"}, []),
    ],
)
def test_filters(client, rows, params, expected):
    assert _ids(client, **params) == [rows[name] for name in expected]


def test_cursor_walks_all_pages_in_order(client, rows):
    seen, cursor = [], None
    while True:
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        body = client.get(URL, params=params, headers=auth_header("manager")).json()
        seen += [item["id"] for item in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert seen == _ids(client)


@pytest.mark.parametrize(
    "params",
    [{"status": "done"}, {"verdict": "bad"}, {"entry": "x"}, {"urgent": "maybe"}, {"cursor": "!"}],
)
def test_invalid_filter_is_400(client, rows, params):
    res = client.get(URL, params=params, headers=auth_header("manager"))
    assert res.status_code == 400


def test_item_carries_decision(client, demo_db, rows):
    """결정된 검토는 목록 항목에 행동·사유·결정 시각을 담는다 (#297)."""
    with Session(demo_db.admin) as s, s.begin():
        review = s.get(Review, rows["other_worker"])
        review.decision = {"action": "reject", "reason": "이번 달 예산 초과"}
        review.decided_by = demo_id("user", "owner")
        review.decided_at = COMPUTED_AT + timedelta(hours=2)
    items = client.get(URL, params={"mine": "true"}, headers=auth_header("worker2")).json()["items"]
    assert items[0]["decision"] == {
        "action": "reject",
        "reason": "이번 달 예산 초과",
        "decided_at": "2026-11-04T05:00:00+09:00",
    }
