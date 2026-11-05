import uuid

import pytest

from .conftest import auth_header
from .test_review_run import _create, _run, fresh  # noqa: F401


def _ask(client, review_id, question, user="manager"):
    return client.post(
        f"/api/v1/reviews/{review_id}/questions",
        json={"question": question},
        headers=auth_header(user),
    )


def _reviewed(db) -> uuid.UUID:
    review_id = _create(db)
    assert _run(db, review_id) == "reviewed"
    return review_id


def test_qty_question_answers_from_snapshot(client, fresh):  # noqa: F811
    res = _ask(client, _reviewed(fresh), "왜 10개야?")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["topic"] == "qty"
    assert body["source"] == "template"
    assert "10개" in body["answer"]
    assert {"R", "S", "D95"} <= set(body["evidence_refs"])


@pytest.mark.parametrize(
    ("question", "topic"),
    [("공급사는 왜 A야?", "supplier"), ("얼마나 급해?", "urgency"), ("안 사면 어떻게 돼?", "risk")],
)
def test_topics_are_classified(client, fresh, question, topic):  # noqa: F811
    body = _ask(client, _reviewed(fresh), question).json()
    assert body["topic"] == topic
    assert body["answer"]


def test_unknown_question_has_no_evidence(client, fresh):  # noqa: F811
    body = _ask(client, _reviewed(fresh), "점심 뭐 먹지?").json()
    assert body == {
        "topic": None,
        "answer": "근거 데이터에 없습니다.",
        "source": "template",
        "evidence_refs": [],
    }


def test_held_review_has_no_evidence(client, fresh):  # noqa: F811
    review_id = _create(fresh, part_id=None)
    _run(fresh, review_id)
    body = _ask(client, review_id, "왜 10개야?").json()
    assert body["answer"] == "근거 데이터에 없습니다."


def test_reviewing_review_is_409(client, fresh):  # noqa: F811
    res = _ask(client, _create(fresh), "왜 10개야?")
    assert res.status_code == 409
    assert res.json()["detail"] == {"status": "reviewing"}


def test_worker_is_403_and_unknown_is_404(client, fresh):  # noqa: F811
    assert _ask(client, _reviewed(fresh), "왜?", user="worker").status_code == 403
    assert _ask(client, uuid.uuid4(), "왜?").status_code == 404


def test_empty_question_is_400(client, fresh):  # noqa: F811
    assert _ask(client, _reviewed(fresh), "").status_code == 400
