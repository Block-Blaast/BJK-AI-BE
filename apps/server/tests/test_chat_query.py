from datetime import UTC, datetime

from bjk_server.clock import KST
from bjk_server.db.models import PartMetrics
from bjk_server.jobs import registry  # noqa: F401
from bjk_server.jobs.runner import run_job
from bjk_server.seed.demo import demo_id
from sqlalchemy import select
from sqlalchemy.orm import Session

NIGHTLY = datetime(2026, 11, 3, 18, 0, tzinfo=UTC)  # 2026-11-04 03:00 KST


def _t_out(demo_db, key):
    with Session(demo_db.admin) as s:
        return s.scalar(
            select(PartMetrics.t_out).where(PartMetrics.part_id == demo_id("part", key))
        )


def test_query_before_nightly_says_estimate_comes_later(chat):
    reply = chat("6205 몇 개 있어?").json()["reply"]
    assert reply.startswith("볼베어링 6205ZZ 현재 재고 3개예요.")
    assert "소진 예상일은 새벽 계산 뒤에 알려 드려요." in reply


def test_query_after_nightly_includes_stockout_date_and_times(chat, demo_db):
    assert run_job(demo_db.app, "nightly", "manual", now=NIGHTLY).status == "ok"
    replies = {key: chat(f"{key} 몇 개 있어?").json()["reply"] for key in ("6205", "6204")}
    for key, reply in replies.items():
        t_out = _t_out(demo_db, key)
        if t_out is None:
            assert "앞으로 8주 안에는 다 쓰지 않을 것으로 보여요." in reply
        else:
            assert f"소진 예상일은 {t_out:%m/%d}이에요." in reply
        assert f"예상 계산 {NIGHTLY.astimezone(KST):%m/%d %H:%M}" in reply
    assert {_t_out(demo_db, k) is None for k in replies} == {True, False}
