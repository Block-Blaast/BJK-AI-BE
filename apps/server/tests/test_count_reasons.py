import pytest
from bjk_server import clock
from bjk_server.db.models import AuditFlag, CountRequest
from sqlalchemy.orm import Session

from .conftest import auth_header
from .test_count_answers import _answer, _p20_request
from .test_count_requests import NOW, flags  # noqa: F401


def _reason(client, request_id, body, user="worker"):
    return client.patch(
        f"/api/v1/count-requests/{request_id}", json=body, headers=auth_header(user)
    )


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch):
    monkeypatch.setattr(clock, "utcnow", lambda: NOW)


def test_reason_closes_request_and_flag(client, flags, demo_db):  # noqa: F811
    request_id = _p20_request(client, flags)
    _answer(client, request_id, 940)
    res = _reason(
        client, request_id, {"reason": "missing_record", "note": "정비 때 쓰고 기록 안 함"}
    )
    assert res.status_code == 200, res.text
    assert res.json() == {
        "count_request_id": request_id,
        "status": "closed",
        "audit_flag_status": "closed",
    }
    with Session(demo_db.admin) as s:
        request = s.get(CountRequest, request_id)
        assert (request.reason, request.note) == ("missing_record", "정비 때 쓰고 기록 안 함")
        flag = s.get(AuditFlag, request.audit_flag_id)
        assert (flag.status, flag.resolution) == ("closed", "adjusted")
        assert flag.closed_at is not None


@pytest.mark.parametrize("counted", [None, 1040], ids=["before-answer", "no-diff"])
def test_reason_requires_answer_with_diff(client, flags, counted):  # noqa: F811
    request_id = _p20_request(client, flags)
    if counted is not None:
        _answer(client, request_id, counted)
    res = _reason(client, request_id, {"reason": "lost"})
    assert res.status_code == 409
    assert res.json()["detail"]["status"] == ("sent" if counted is None else "closed")


def test_reason_must_be_known_code(client, flags):  # noqa: F811
    request_id = _p20_request(client, flags)
    _answer(client, request_id, 940)
    assert _reason(client, request_id, {"reason": "unknown"}).status_code == 400


def test_other_worker_cannot_give_reason(client, flags):  # noqa: F811
    request_id = _p20_request(client, flags)
    _answer(client, request_id, 940)
    assert _reason(client, request_id, {"reason": "lost"}, user="worker2").status_code == 404
