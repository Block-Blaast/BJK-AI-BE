"""대시보드 요약 (API 명세서 DSH-02)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from bjk_server.api import dashboard
from bjk_server.db.models import (
    AuditFlag,
    Company,
    Movement,
    Part,
    PurchaseOrder,
    Review,
    Supplier,
    SupplierPart,
)
from bjk_server.jobs.runner import run_job
from bjk_server.seed.demo import COMPANY_CODE, demo_id
from sqlalchemy.orm import Session

from .conftest import auth_header

URL = "/api/v1/dashboard/summary"
COMPANY = demo_id("company", COMPANY_CODE)
# 2026-11-05 10:00 KST
NOW = datetime(2026, 11, 5, 1, 0, tzinfo=UTC)


@pytest.fixture
def summary(client, demo_db, monkeypatch):
    demo_db.reseed()
    monkeypatch.setattr(dashboard.clock, "utcnow", lambda: NOW)

    def get(user="manager"):
        return client.get(URL, headers=auth_header(user))

    return get


def _review(status, flags=(), created_at=NOW, decided_at=None):
    return Review(
        company_id=COMPANY,
        entry="missed_draft",
        status=status,
        flags=list(flags),
        request={},
        created_at=created_at,
        decided_at=decided_at,
        decided_by=demo_id("user", "owner") if decided_at else None,
    )


def test_worker_is_forbidden(summary):
    assert summary("worker").status_code == 403


def test_risk_top5_follows_nightly_priority(summary, demo_db):
    assert run_job(demo_db.app, "nightly", "manual", now=NOW).status == "ok"
    body = summary().json()
    risks = body["risk_top5"]
    assert 0 < len(risks) <= 5
    priorities = [r["priority"] for r in risks]
    assert priorities == sorted(priorities, reverse=True)
    assert body["computed_at"].endswith("+09:00")
    assert body["external"]["level"] in {"normal", "caution", "high"}


def test_counts_reviews_flags_and_today(summary, demo_db):
    yesterday = NOW - timedelta(days=1)
    with Session(demo_db.admin) as s, s.begin():
        s.add_all(
            [
                _review("reviewed", ["urgent"]),
                _review("held", created_at=yesterday),
                _review("reviewing"),
                _review("approved", created_at=yesterday, decided_at=NOW),
            ]
        )
    body = summary().json()
    assert body["pending_reviews"] == {"count": 2, "urgent": 1}
    assert body["today"]["reviews_created"] == 2
    assert body["today"]["decisions"] == 1
    assert body["awaiting_order"] == 0


def test_tied_up_stock_counts_idle_parts_only(summary, demo_db):
    idle, used = uuid.uuid4(), uuid.uuid4()
    long_ago = NOW - timedelta(days=200)
    with Session(demo_db.admin) as s, s.begin():
        for part_id, name in ((idle, "안 쓰는 부품"), (used, "쓰는 부품")):
            s.add(
                Part(
                    id=part_id,
                    company_id=COMPANY,
                    name=name,
                    unit="개",
                    default_supplier_id=demo_id("supplier", "a"),
                )
            )
        s.flush()
        for part_id in (idle, used):
            s.add(
                SupplierPart(
                    company_id=COMPANY,
                    supplier_id=demo_id("supplier", "a"),
                    part_id=part_id,
                    unit_price=1_000,
                )
            )
            s.add(
                Movement(
                    company_id=COMPANY, part_id=part_id, type="IN", qty=10, occurred_at=long_ago
                )
            )
        s.add(
            Movement(
                company_id=COMPANY,
                part_id=used,
                type="OUT",
                qty=-1,
                occurred_at=NOW - timedelta(days=10),
            )
        )
    before = summary().json()["tied_up_stock_amount"]
    with Session(demo_db.admin) as s, s.begin():
        s.add(
            SupplierPart(
                company_id=COMPANY,
                supplier_id=demo_id("supplier", "b"),
                part_id=idle,
                unit_price=500,
            )
        )
    # 기본 공급사 단가(1,000원)를 쓴다
    assert summary().json()["tied_up_stock_amount"] == before
    # 시드 부품은 모두 최근 출고가 있어 0원, 안 쓰는 부품 10개 × 1,000원만 남는다
    assert before == 10_000


def test_tied_up_stock_counts_merged_part_outs_as_use(summary, demo_db):
    """병합된 부품에 남은 최근 출고도 대표 부품을 쓴 것으로 본다(F-LEDGER-02)."""
    rep, absorbed = uuid.uuid4(), uuid.uuid4()
    long_ago = NOW - timedelta(days=200)
    with Session(demo_db.admin) as s, s.begin():
        s.add(
            Part(
                id=rep,
                company_id=COMPANY,
                name="볼트 대표",
                unit="개",
                default_supplier_id=demo_id("supplier", "a"),
            )
        )
        s.flush()
        s.add(Part(id=absorbed, company_id=COMPANY, name="볼트 병합", unit="개", merged_into=rep))
        s.add(
            SupplierPart(
                company_id=COMPANY,
                supplier_id=demo_id("supplier", "a"),
                part_id=rep,
                unit_price=1_000,
            )
        )
        s.flush()
        for part_id, qty, at in (
            (rep, 10, long_ago),
            (absorbed, 5, long_ago),
            (absorbed, -1, NOW - timedelta(days=10)),
        ):
            s.add(
                Movement(
                    company_id=COMPANY,
                    part_id=part_id,
                    type="IN" if qty > 0 else "OUT",
                    qty=qty,
                    occurred_at=at,
                )
            )
    assert summary().json()["tied_up_stock_amount"] == 0


def test_today_movements_counted_from_kst_midnight(summary, demo_db):
    base = summary().json()["today"]["movements"]
    part = demo_id("part", "6205")
    with Session(demo_db.admin) as s, s.begin():
        # 2026-11-05 00:30 KST: 오늘, 2026-11-04 23:30 KST: 어제
        for at in (
            datetime(2026, 11, 4, 15, 30, tzinfo=UTC),
            datetime(2026, 11, 4, 14, 30, tzinfo=UTC),
        ):
            s.add(Movement(company_id=COMPANY, part_id=part, type="IN", qty=1, occurred_at=at))
    assert summary().json()["today"]["movements"] == base + 1


def _order(company_id, part_id, supplier_id, status, **kw) -> PurchaseOrder:
    return PurchaseOrder(
        company_id=company_id,
        part_id=part_id,
        supplier_id=supplier_id,
        qty=10,
        unit_price=1000,
        status=status,
        approved_at=NOW - timedelta(days=1),
        **kw,
    )


def test_awaiting_order_counts_approved_orders_only(summary, demo_db):
    part, supplier, owner = (
        demo_id("part", "6205"),
        demo_id("supplier", "a"),
        demo_id("user", "owner"),
    )
    with Session(demo_db.admin) as s, s.begin():
        s.add_all(
            [
                _order(COMPANY, part, supplier, "approved"),
                _order(COMPANY, part, supplier, "approved"),
                _order(COMPANY, part, supplier, "ordered", ordered_at=NOW, ordered_by=owner),
                _order(COMPANY, part, supplier, "cancelled", cancelled_at=NOW),
            ]
        )
    assert summary().json()["awaiting_order"] == 2


def test_owner_allowed_and_other_company_excluded(summary, demo_db):
    before = summary("owner")
    assert before.status_code == 200
    other = uuid.uuid4()
    with Session(demo_db.admin) as s, s.begin():
        s.add(Company(id=other, name="다른회사", code="OTH001"))
        s.flush()
        supplier = Supplier(id=uuid.uuid4(), company_id=other, name="다른 공급사")
        part = Part(id=uuid.uuid4(), company_id=other, name="다른 부품", unit="개")
        s.add_all([supplier, part])
        s.flush()
        s.add_all(
            [
                _order(other, part.id, supplier.id, "approved"),
                Review(company_id=other, entry="missed_draft", status="reviewed", request={}),
                AuditFlag(
                    company_id=other,
                    part_id=part.id,
                    rule="NEGATIVE_STOCK",
                    level="high",
                    status="open",
                    evidence={},
                    keys=[],
                ),
                Movement(
                    company_id=other,
                    part_id=part.id,
                    type="ADJUST",
                    qty=5,
                    occurred_at=NOW,
                    reason="test",
                ),
            ]
        )
    after = summary("owner").json()
    keys = ("awaiting_order", "pending_reviews", "audit_flags", "today", "tied_up_stock_amount")
    assert {k: after[k] for k in keys} == {k: before.json()[k] for k in keys}
