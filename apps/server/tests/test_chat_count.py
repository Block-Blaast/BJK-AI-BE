from bjk_server.chat.interpreter import Interpretation
from bjk_server.db.models import AuditFlag, CountRequest, Movement
from bjk_server.seed.demo import demo_id
from sqlalchemy import select
from sqlalchemy.orm import Session

from .chat_fakes import PARSED
from .conftest import auth_header
from .test_count_requests import _request, flags  # noqa: F401

P20 = demo_id("part", "p20")

PARSED.update(
    {
        "세어보니 940개": Interpretation("COUNT", None, 940),
        "세어보니 1040개": Interpretation("COUNT", None, 1040),
        "오링 세어보니 940개": Interpretation("COUNT", "오링 P-20", 940),
        "다 셌어요": Interpretation("COUNT"),
    }
)


def _p20(client, flags):  # noqa: F811
    return _request(client, flags["오링 P-20"]).json()["count_request_id"]


def test_chat_count_answers_request_like_aud03(chat, flags, client, demo_db):  # noqa: F811
    request_id = _p20(client, flags)
    body = chat("세어보니 940개").json()
    assert body["intent"] == "COUNT"
    assert body["reply"] == "장부보다 100개 적어요. 이유를 골라 주세요."
    assert body["cards"] == []
    assert body["count_request_id"] == request_id
    with Session(demo_db.admin) as s:
        request = s.get(CountRequest, request_id)
        assert (request.status, request.diff) == ("answered", -100)
        movement = s.get(Movement, request.adjust_movement_id)
        assert (movement.type, movement.qty, movement.reason) == ("ADJUST", -100, "실사조정")
    reason = client.patch(
        f"/api/v1/count-requests/{request_id}",
        json={"reason": "lost"},
        headers=auth_header("worker"),
    )
    assert reason.status_code == 200, reason.text


def test_chat_count_without_diff_closes_flag(chat, flags, client, demo_db):  # noqa: F811
    request_id = _p20(client, flags)
    assert chat("세어보니 1040개").json()["reply"] == "장부와 같아요. 이상 없음으로 처리했어요."
    with Session(demo_db.admin) as s:
        assert s.get(CountRequest, request_id).status == "closed"
        flag = s.scalar(select(AuditFlag).where(AuditFlag.part_id == P20))
        assert (flag.status, flag.resolution) == ("closed", "no_diff")


def test_chat_count_without_request_or_qty_records_nothing(chat, flags, client, demo_db):  # noqa: F811
    body = chat("세어보니 940개").json()
    assert body["reply"] == "답할 실사 요청이 없어요."
    assert body["count_request_id"] is None
    request_id = _p20(client, flags)
    assert chat("다 셌어요").json()["reply"] == "센 수량을 숫자로 알려 주세요."
    assert chat("세어보니 940개", user="manager").json()["reply"] == "답할 실사 요청이 없어요."
    with Session(demo_db.admin) as s:
        assert s.get(CountRequest, request_id).status == "sent"


def test_chat_count_asks_part_when_several_requests(chat, flags, client):  # noqa: F811
    request_id = _p20(client, flags)
    other = next(name for name in flags if name != "오링 P-20")
    assert _request(client, flags[other]).status_code == 201
    reply = chat("세어보니 940개").json()["reply"]
    assert reply.startswith("어떤 부품을 세셨나요?")
    assert "오링 P-20" in reply and other in reply
    body = chat("오링 세어보니 940개").json()
    assert body["count_request_id"] == request_id
    assert body["reply"] == "장부보다 100개 적어요. 이유를 골라 주세요."
