"""검토 스냅샷의 병합 부품 재고 (#209 후속, F-LEDGER-02·F-MATCH-03)."""

import uuid

from bjk_review import OrderRequest
from bjk_server.auth import set_tenant
from bjk_server.db.models import Movement, Part
from bjk_server.defaults import default_settings
from bjk_server.reviews.snapshot import collect_snapshot
from bjk_server.seed.demo import demo_id
from sqlalchemy.orm import Session

from .test_review_run import COMPANY, NOW, fresh  # noqa: F401

M820 = demo_id("part", "m820")


def _part(s, name, merged_into=None, qty=0, out=False):
    bolt = s.get(Part, M820)
    pid = uuid.uuid4()
    s.add(
        Part(
            id=pid,
            company_id=COMPANY,
            category_id=bolt.category_id,
            name=name,
            spec=dict(bolt.spec),
            unit="개",
            merged_into=merged_into,
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
                occurred_at=NOW,
                reason="엑셀 이관",
            )
        )
    if out:
        s.add(Movement(company_id=COMPANY, part_id=pid, type="OUT", qty=-1, occurred_at=NOW))
    return pid


def _snapshot(db, part_id):
    with Session(db.app) as s, s.begin():
        set_tenant(s, COMPANY)
        return collect_snapshot(
            s, str(part_id), OrderRequest(qty=10), now=NOW, settings=default_settings()
        )


def test_stock_includes_merged_parts(fresh):  # noqa: F811
    with Session(fresh.admin) as s, s.begin():
        rep = _part(s, "볼트 대표", qty=40)
        _part(s, "헥사볼트 M8x20", merged_into=rep, qty=800, out=True)
    snap = _snapshot(fresh, rep)
    assert snap.stock == 40 + 800 - 1
    assert snap.has_usage_history is True


def test_hidden_twin_counts_parts_merged_into_it(fresh):  # noqa: F811
    with Session(fresh.admin) as s, s.begin():
        twin = _part(s, "볼트 다른 등록", qty=100)
        _part(s, "볼트 병합된 쪽", merged_into=twin, qty=50)
    hidden = {h.part_id: h.qty for h in _snapshot(fresh, M820).hidden}
    assert hidden[str(twin)] == 150
    assert len(hidden) == 1
