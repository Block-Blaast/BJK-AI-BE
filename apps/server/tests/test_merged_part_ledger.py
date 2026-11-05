"""병합된 부품의 원장·발주를 대표 부품으로 보는 경로 (#209 후속, F-LEDGER-02·04).

병합해도 원장과 발주 행은 흡수된 부품에 그대로 남는다. 재고·사용 이력·열린 발주를 읽는 곳은
대표 부품으로 합산해야 한다.
"""

import uuid
from datetime import timedelta

from bjk_server.auth import set_tenant
from bjk_server.chat.intents.po_preview import preview_po_match
from bjk_server.db.models import AuditFlag, Movement, Part, PartMetrics, PurchaseOrder
from bjk_server.inventory import stock_of
from bjk_server.purchasing.receipt import match_receipt
from sqlalchemy import select
from sqlalchemy.orm import Session

from .test_nightly import COMPANY, NOW, demo_id, nightly  # noqa: F401

M820 = demo_id("part", "m820")
SUP_A = demo_id("supplier", "a")
OWNER = demo_id("user", "owner")


def _absorbed(db, qty: int = 0, out: int = 0) -> uuid.UUID:
    """M820과 같은 규격 부품을 만들어 재고를 넣고 M820으로 병합된 상태로 둔다."""
    with Session(db.admin) as s, s.begin():
        bolt = s.get(Part, M820)
        pid = uuid.uuid4()
        s.add(
            Part(
                id=pid,
                company_id=COMPANY,
                category_id=bolt.category_id,
                name="헥사볼트 M8x20",
                spec=dict(bolt.spec),
                unit="개",
                merged_into=M820,
            )
        )
        s.flush()
        if qty:
            s.add(
                Movement(
                    company_id=COMPANY,
                    part_id=pid,
                    type="ADJUST",
                    qty=qty,
                    occurred_at=NOW - timedelta(days=30),
                    reason="엑셀 이관",
                )
            )
        if out:
            s.add(
                Movement(
                    company_id=COMPANY,
                    part_id=pid,
                    type="OUT",
                    qty=-out,
                    occurred_at=NOW - timedelta(days=3),
                )
            )
    return pid


def _metrics(db) -> PartMetrics:
    with Session(db.admin) as s:
        return s.scalar(
            select(PartMetrics)
            .where(PartMetrics.part_id == M820)
            .order_by(PartMetrics.computed_on.desc())
        )


def test_nightly_stock_includes_merged_part(demo_db, nightly):  # noqa: F811
    _absorbed(demo_db, qty=800)
    nightly()
    with Session(demo_db.admin) as s:
        expected = stock_of(s, M820)
    metrics = _metrics(demo_db)
    assert metrics.stock == expected
    # 병합된 재고 800개가 있으니 새로 살 필요가 없다
    assert metrics.recommended_qty == 0


def test_audit_reads_merged_ledger_before_flagging_negative_stock(demo_db, nightly):  # noqa: F811
    _absorbed(demo_db, qty=800)
    with Session(demo_db.admin) as s, s.begin():
        own = int(sum(s.scalars(select(Movement.qty).where(Movement.part_id == M820)).all()))
        # 대표 부품 원장만 보면 음수, 병합된 재고까지 보면 700개 남음
        s.add(
            Movement(
                company_id=COMPANY,
                part_id=M820,
                type="OUT",
                qty=-(own + 100),
                occurred_at=NOW - timedelta(days=1),
            )
        )
    nightly()
    with Session(demo_db.admin) as s:
        rules = s.scalars(select(AuditFlag.rule).where(AuditFlag.part_id == M820)).all()
    assert "NEGATIVE_STOCK" not in rules


def test_receipt_on_representative_matches_absorbed_part_order(demo_db, nightly):  # noqa: F811
    absorbed = _absorbed(demo_db)
    with Session(demo_db.admin) as s, s.begin():
        po = PurchaseOrder(
            company_id=COMPANY,
            part_id=absorbed,
            supplier_id=SUP_A,
            qty=50,
            unit_price=50,
            status="ordered",
            approved_at=NOW - timedelta(days=8),
            approved_by=OWNER,
            ordered_at=NOW - timedelta(days=7),
            ordered_by=OWNER,
        )
        s.add(po)
        s.flush()
        po_id = po.id
    with Session(demo_db.app) as s, s.begin():
        set_tenant(s, COMPANY)
        assert preview_po_match(s, M820, 50) == "complete"
        result = match_receipt(s, s.get(Part, M820), 50, OWNER, NOW)
    assert (result.po_match, result.po_id) == ("complete", po_id)
    with Session(demo_db.admin) as s:
        assert s.get(PurchaseOrder, po_id).status == "received"
