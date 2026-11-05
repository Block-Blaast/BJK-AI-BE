"""검토 결과 알림 (기능명세서 F-NOTI-01·04)."""

from bjk_server.db.models import Notification
from bjk_server.seed.demo import demo_id
from sqlalchemy import select
from sqlalchemy.orm import Session

from .test_review_run import NOW, _create, _run, fresh  # noqa: F401

P6205 = demo_id("part", "6205")
OWNER = demo_id("user", "owner")
MANAGER = demo_id("user", "manager")
WORKER = demo_id("user", "worker")


def _notices(db) -> list[Notification]:
    with Session(db.admin) as s:
        return list(s.scalars(select(Notification).order_by(Notification.user_id)))


def _plain(db, **kw):
    """긴급이 아닌 검토(볼베어링 6205ZZ 5개는 적정, 표시 없음)."""
    return _create(db, part_id=P6205, qty=5, supplier_id=None, unit_price=None, **kw)


def test_staff_request_notifies_owner_and_manager(fresh):  # noqa: F811
    review_id = _plain(fresh)
    assert _run(fresh, review_id) == "reviewed"
    rows = _notices(fresh)
    assert {r.user_id for r in rows} == {OWNER, MANAGER}
    assert {r.kind for r in rows} == {"review_completed"}
    row = rows[0]
    assert row.title == "볼베어링 6205ZZ 발주 요청 검토가 끝났어요. 판정: 적정"
    assert (row.target_type, row.target_id) == ("review", review_id)
    assert row.channels == ["push", "in_app"]
    assert row.sent_at == NOW


def test_urgent_staff_request_sends_only_urgent(fresh):  # noqa: F811
    review_id = _create(fresh)  # V벨트 A-42 30개: 긴급
    _run(fresh, review_id)
    rows = _notices(fresh)
    assert {r.kind for r in rows} == {"review_urgent"}
    assert {r.user_id for r in rows} == {OWNER, MANAGER}
    assert rows[0].title.startswith("긴급: V벨트 A-42 발주 마감 ")


def test_requester_is_not_notified_of_own_request(fresh):  # noqa: F811
    review_id = _plain(fresh, requested_by=MANAGER)
    _run(fresh, review_id)
    assert [r.user_id for r in _notices(fresh)] == [OWNER]


def test_urgent_stock_draft_notifies_but_plain_draft_waits_for_briefing(fresh):  # noqa: F811
    plain = _plain(fresh, entry="stock_draft")
    _run(fresh, plain)
    assert _notices(fresh) == []
    urgent = _create(fresh, entry="stock_draft", qty=10, supplier_id=None, unit_price=None)
    _run(fresh, urgent)
    rows = _notices(fresh)
    assert {r.kind for r in rows} == {"review_urgent"}
    assert {r.target_id for r in rows} == {urgent}


def test_missed_draft_is_left_to_briefing(fresh):  # noqa: F811
    review_id = _create(fresh, entry="missed_draft", qty=10, supplier_id=None, unit_price=None)
    _run(fresh, review_id)
    assert _notices(fresh) == []


def test_held_request_notifies_requester_in_chat(fresh):  # noqa: F811
    review_id = _create(fresh, part_id=None)
    assert _run(fresh, review_id) == "held"
    rows = _notices(fresh)
    assert [(r.user_id, r.kind, r.channels) for r in rows] == [
        (WORKER, "decision_result", ["chat"])
    ]
    assert rows[0].title == "요청한 부품 발주 요청이 보류됐어요. 내 요청에서 내용을 보완해 주세요."
