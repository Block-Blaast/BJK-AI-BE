import uuid
from datetime import UTC, datetime

import pytest
from bjk_server.db.models import Company, Movement, Part
from bjk_server.jobs import registry  # noqa: F401
from bjk_server.jobs.runner import run_job
from bjk_server.seed.demo import PARTS, demo_id
from sqlalchemy.orm import Session

from .conftest import auth_header
from .test_nightly import add_hidden_twin

NIGHTLY_AT = datetime(2026, 11, 3, 18, 0, tzinfo=UTC)  # 2026-11-04 03:00 KST


def _url(key: str) -> str:
    return f"/api/v1/parts/{demo_id('part', key)}"


@pytest.fixture
def fresh(demo_db):
    demo_db.reseed()
    demo_db.clear_orders()
    yield demo_db
    demo_db.reseed()


def test_detail_before_nightly(client, fresh):
    res = client.get(_url("6205"), headers=auth_header("worker"))
    assert res.status_code == 200
    body = res.json()
    seeded = next(p for p in PARTS if p.key == "6205")
    assert body["name"] == "볼베어링 6205ZZ"
    assert body["spec"] == seeded.spec
    assert body["category"] == {
        "id": str(demo_id("category", "bearing")),
        "name": "베어링",
        "import_dependency": "high",
    }
    assert body["stock"] == {
        "S": seeded.stock,
        "incoming": [],
        "hidden": {"H_c": 0, "H_u": 0, "parts": []},
        "ledger_status": "normal",
        "last_counted_at": None,
    }
    assert body["metrics"] is None
    assert body["supplier_metrics"] == [
        {
            "supplier_id": str(demo_id("supplier", "a")),
            "name": "공급사 A",
            "LT50": None,
            "LT90": None,
            "samples": None,
            "unit_price": 18000,
            "moq": 10,
        }
    ]
    assert body["aliases"] == [{"text": "베어링 작은 거", "confirmed_count": 3, "ambiguous": False}]


def test_detail_after_nightly_shows_latest_metrics(client, fresh):
    result = run_job(fresh.app, "nightly", "manual", now=NIGHTLY_AT)
    assert result.status == "ok", result.error
    body = client.get(_url("6205"), headers=auth_header("worker")).json()
    m = body["metrics"]
    assert m["R"] == 10  # MOQ 10으로 올림
    assert m["t_out"] == "2026-11-20"
    assert m["F"][0]["qty"] == 4
    assert m["default_supplier"]["name"] == "공급사 A"
    assert m["default_supplier"]["LT90"] == 10
    assert m["loss"]["L"] == 50_000 * 16 * m["default_supplier"]["LT50"]
    assert m["external_level"] == "caution"
    assert m["computed_at"] is not None
    supplier = body["supplier_metrics"][0]
    assert supplier["LT90"] == m["default_supplier"]["LT90"]
    assert supplier["samples"] is not None


def test_detail_after_nightly_splits_hidden_stock(client, fresh):
    add_hidden_twin(fresh, 800, counted_days_ago=14)
    result = run_job(fresh.app, "nightly", "manual", now=NIGHTLY_AT)
    assert result.status == "ok", result.error
    body = client.get(_url("6205"), headers=auth_header("worker")).json()
    assert {k: body["stock"]["hidden"][k] for k in ("H_c", "H_u")} == {"H_c": 800, "H_u": 0}
    assert body["metrics"]["R"] == 0


def test_two_suppliers_are_listed_by_name(client, fresh):
    body = client.get(_url("6204"), headers=auth_header("worker")).json()
    assert [(s["name"], s["unit_price"]) for s in body["supplier_metrics"]] == [
        ("공급사 A", 21000),
        ("공급사 B", 14800),
    ]


def test_stock_follows_ledger(client, fresh):
    with Session(fresh.admin) as s, s.begin():
        s.add(
            Movement(
                company_id=demo_id("company", "HS7F3K"),
                part_id=demo_id("part", "6205"),
                type="OUT",
                qty=-1,
            )
        )
    seeded = next(p for p in PARTS if p.key == "6205")
    body = client.get(_url("6205"), headers=auth_header("worker")).json()
    assert body["stock"]["S"] == seeded.stock - 1


def test_unknown_and_merged_parts_are_404(client, fresh):
    res = client.get(f"/api/v1/parts/{uuid.uuid4()}", headers=auth_header("worker"))
    assert res.status_code == 404
    assert res.json()["code"] == "NOT_FOUND"
    with Session(fresh.admin) as s, s.begin():
        s.get(Part, demo_id("part", "m820")).merged_into = demo_id("part", "p20")
    assert client.get(_url("m820"), headers=auth_header("worker")).status_code == 404


def test_other_company_part_is_404(client, fresh):
    other_company = uuid.uuid4()
    other_part = uuid.uuid4()
    with Session(fresh.admin) as s, s.begin():
        s.add(Company(id=other_company, name="다른회사", code="OTHER1"))
        s.flush()
        s.add(Part(id=other_part, company_id=other_company, name="남의 부품", unit="개"))
    res = client.get(f"/api/v1/parts/{other_part}", headers=auth_header("owner"))
    assert res.status_code == 404


def test_requires_token(client):
    assert client.get(_url("6205")).status_code == 401
