import uuid
from datetime import UTC, datetime

import pytest
from bjk_server.db.models import Movement, Part, PartAlias
from bjk_server.jobs import registry  # noqa: F401
from bjk_server.jobs.runner import run_job
from bjk_server.seed.demo import demo_id
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .conftest import auth_header, watch_stock_events

NOW = datetime(2026, 11, 9, 18, 30, tzinfo=UTC)  # 2026-11-10(월) 03:30 KST
M820 = demo_id("part", "m820")
HEX = uuid.UUID("00000000-0000-4000-8000-0000000000e1")
URL = "/api/v1/merge-candidates"


@pytest.fixture
def hex_bolt(demo_db):
    """시드의 육각볼트 M8-20과 같은 규격으로 따로 등록한 헥사볼트 M8x20(재고 800, 별칭 둘)."""
    demo_db.reseed()
    with Session(demo_db.admin) as s, s.begin():
        bolt = s.get(Part, M820)
        s.add(
            Part(
                id=HEX,
                company_id=bolt.company_id,
                category_id=bolt.category_id,
                name="헥사볼트 M8x20",
                spec={"thread": "M8", "length_mm": 20},
                unit="개",
            )
        )
        s.flush()
        s.add(
            Movement(
                company_id=bolt.company_id,
                part_id=HEX,
                type="ADJUST",
                qty=800,
                occurred_at=NOW,
                reason="엑셀 이관",
            )
        )
        s.add(PartAlias(company_id=bolt.company_id, part_id=HEX, text="헥사", confirmed_count=2))
        s.add(PartAlias(company_id=bolt.company_id, part_id=M820, text="m8", confirmed_count=1))
        s.add(PartAlias(company_id=bolt.company_id, part_id=HEX, text="m8", confirmed_count=3))
    assert run_job(demo_db.app, "weekly-merge", "manual", now=NOW).status == "ok"
    return HEX


def _candidates(client, **params):
    res = client.get(URL, params=params, headers=auth_header("manager"))
    assert res.status_code == 200, res.text
    return res.json()["items"]


def _decide(client, cid, user="manager", **body):
    return client.post(f"{URL}/{cid}/decision", json=body, headers=auth_header(user))


def _stock(client, part_id):
    res = client.get(f"/api/v1/parts/{part_id}", headers=auth_header("manager"))
    return res.json()["stock"]["S"]


def test_weekly_merge_finds_same_spec_pair_once(client, demo_db, hex_bolt):
    [item] = _candidates(client)
    assert item["reason"] == "spec_exact+name_similar"
    assert {item["part_a"]["id"], item["part_b"]["id"]} == {str(M820), str(HEX)}
    hex_out = next(p for p in (item["part_a"], item["part_b"]) if p["id"] == str(HEX))
    assert (hex_out["stock"], hex_out["last_counted_at"]) == (800, None)
    assert run_job(demo_db.app, "weekly-merge", "manual", now=NOW).summary["created"] == 0
    assert _candidates(client, status="merged") == []


def test_merge_sums_stock_moves_aliases_and_keeps_ledger(client, demo_db, hex_bolt):
    [item] = _candidates(client)
    before = _stock(client, M820)
    with Session(demo_db.admin) as s:
        rows = s.scalar(select(func.count()).select_from(Movement))
    events = watch_stock_events(demo_db)
    res = _decide(client, item["id"], action="merge", representative_part_id=str(M820))
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "merged"
    assert _stock(client, M820) == before + 800
    assert events() == [{"part_id": str(M820), "stock": before + 800}]
    with Session(demo_db.admin) as s:
        assert s.get(Part, HEX).merged_into == M820
        assert s.scalar(select(func.count()).select_from(Movement)) == rows
        aliases = {
            a.text: a.confirmed_count
            for a in s.scalars(select(PartAlias).where(PartAlias.part_id.in_([M820, HEX])))
        }
        assert {k: aliases[k] for k in ("헥사", "m8")} == {"헥사": 2, "m8": 4}
        assert s.scalar(select(func.count()).where(PartAlias.part_id == HEX)) == 0
    again = _decide(client, item["id"], action="different")
    assert again.status_code == 409
    assert again.json()["detail"] == {"status": "merged"}
    # 병합된 부품은 다음 주 후보에 다시 나오지 않는다.
    assert run_job(demo_db.app, "weekly-merge", "manual", now=NOW).summary["created"] == 0


def test_different_and_request_count(client, demo_db, hex_bolt):
    [item] = _candidates(client)
    res = _decide(client, item["id"], action="request_count")
    assert res.json()["status"] == "count_requested"
    assert _candidates(client)[0]["status"] == "count_requested"
    res = _decide(client, item["id"], action="different")
    assert res.json()["status"] == "different"
    assert _candidates(client) == []
    assert run_job(demo_db.app, "weekly-merge", "manual", now=NOW).summary["created"] == 0
    with Session(demo_db.admin) as s:
        assert s.get(Part, HEX).merged_into is None


def test_decision_validation_and_permissions(client, hex_bolt):
    [item] = _candidates(client)
    bad = _decide(client, item["id"], action="merge", representative_part_id=str(uuid.uuid4()))
    assert bad.status_code == 400
    assert bad.json()["detail"] == {"field": "representative_part_id"}
    assert _decide(client, item["id"], user="worker", action="different").status_code == 403
    assert client.get(URL, headers=auth_header("worker")).status_code == 403
    assert _decide(client, uuid.uuid4(), action="different").status_code == 404
