"""회사별 LLM 일일 토큰 상한 (API 명세서 1-5)."""

import uuid
from datetime import UTC, datetime

from bjk_contracts import FallbackReason
from bjk_server import ratelimit
from bjk_server.ai import quota
from bjk_server.ai.client import AiClient, AiUnavailable, get_ai_client
from bjk_server.ai.quota import over_daily_quota, tokens_today
from bjk_server.db.models import CompanySettings, LlmCall
from bjk_server.seed.demo import COMPANY_CODE, demo_id
from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from .ai_fakes import FakeAi, parsed
from .conftest import auth_header

COMPANY = demo_id("company", COMPANY_CODE)
# 2026-11-05 09:00 KST
NOW = datetime(2026, 11, 5, 0, 0, tzinfo=UTC)


def _call(company_id, tokens, at):
    return LlmCall(
        id=uuid.uuid4(),
        company_id=company_id,
        purpose="chat_parse",
        model="test-model",
        input_tokens=tokens,
        output_tokens=0,
        latency_ms=10,
        attempts=1,
        success=True,
        created_at=at,
    )


def _set_limit(s, limit):
    s.execute(
        update(CompanySettings)
        .where(CompanySettings.company_id == COMPANY)
        .values(system=CompanySettings.system.op("||")({"llm_daily_tokens": limit}))
    )


def test_over_quota_skips_ai_request():
    ai = FakeAi(chat={"볼트 3개 씀": parsed("OUT", part_text="볼트", qty=3)})
    client = AiClient(ai.client()._http, over_quota=lambda company_id: True)
    try:
        client.parse_chat(COMPANY, "볼트 3개 씀")
    except AiUnavailable as exc:
        assert exc.reason == FallbackReason.QUOTA_EXCEEDED
    else:
        raise AssertionError("상한 초과인데 ai를 불렀다")
    assert ai.requests == []


def test_under_quota_calls_ai():
    ai = FakeAi(chat={"볼트 3개 씀": parsed("OUT", part_text="볼트", qty=3)})
    client = AiClient(ai.client()._http, over_quota=lambda company_id: False)
    assert client.parse_chat(COMPANY, "볼트 3개 씀").intent == "OUT"
    assert ai.paths() == ["/v1/chat/parse"]


def test_tokens_today_counts_kst_day_and_own_company(demo_db):
    demo_db.reseed()
    other = uuid.uuid4()
    with Session(demo_db.admin) as s, s.begin():
        s.add_all(
            [
                # 2026-11-05 00:30 KST: 오늘
                _call(COMPANY, 300, datetime(2026, 11, 4, 15, 30, tzinfo=UTC)),
                # 2026-11-04 23:30 KST: 어제
                _call(COMPANY, 5_000, datetime(2026, 11, 4, 14, 30, tzinfo=UTC)),
            ]
        )
        assert tokens_today(s, COMPANY, NOW) == 300
        assert tokens_today(s, other, NOW) == 0
        _set_limit(s, 300)
        assert over_daily_quota(s, COMPANY, NOW)
        _set_limit(s, 301)
        assert not over_daily_quota(s, COMPANY, NOW)


def test_chat_falls_back_to_form_when_over_quota(client, demo_db, monkeypatch):
    demo_db.reseed()
    monkeypatch.setattr(ratelimit, "utcnow", lambda: NOW)
    ai = FakeAi(chat={"3호기 베어링 두 개 씀": parsed("OUT", part_text="베어링", qty=2)})
    client.app.dependency_overrides[get_ai_client] = lambda: AiClient(
        ai.client()._http, over_quota=lambda company_id: True
    )
    body = {"client_message_id": "quota-1", "text": "3호기 베어링 두 개 씀"}
    res = client.post("/api/v1/chat/messages", json=body, headers=auth_header("worker"))
    assert res.status_code == 200
    data = res.json()
    assert data["cards"][0]["type"] == "form"
    assert data["ai"]["fallback"] is True and data["ai"]["reason"] == "quota_exceeded"
    assert ai.requests == []


def test_check_daily_quota_reads_with_app_account(demo_db, monkeypatch):
    demo_db.reseed()
    monkeypatch.setattr(quota, "get_sessionmaker", lambda: sessionmaker(demo_db.app))
    monkeypatch.setattr(quota, "utcnow", lambda: NOW)
    with Session(demo_db.admin) as s, s.begin():
        s.add(_call(COMPANY, 50, NOW))
        _set_limit(s, 50)
    assert quota.check_daily_quota(COMPANY)
    assert not quota.check_daily_quota(uuid.uuid4())
