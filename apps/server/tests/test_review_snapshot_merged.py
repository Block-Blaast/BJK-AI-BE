"""검토 스냅샷의 병합 부품 재고 (#209, F-LEDGER-02, F-MATCH-03)."""

import uuid

from bjk_server.db.models import Movement, Part
from sqlalchemy.orm import Session

from .test_review_run import A42, COMPANY, WORKER, fresh  # noqa: F401
from .test_review_snapshot_orders import NOW, _snapshot


def _part(db, source: Part, **overrides) -> uuid.UUID:
    with Session(db.admin) as s, s.begin():
        part = Part(
            id=uuid.uuid4(),
            company_id=COMPANY,
            name=overrides.pop("name", f"{source.name} 다른 이름"),
            unit=source.unit,
            category_id=source.category_id,
            spec=source.spec,
            **overrides,
        )
        s.add(part)
        return part.id


def _move(db, part_id, qty, type_="ADJUST") -> None:
    with Session(db.admin) as s, s.begin():
        s.add(
            Movement(
                company_id=COMPANY,
                part_id=part_id,
                type=type_,
                qty=qty,
                author_id=WORKER,
                occurred_at=NOW,
                reason="test" if type_ == "ADJUST" else None,
            )
        )


def _a42(db) -> Part:
    with Session(db.admin) as s:
        return s.get(Part, A42)


def test_merged_part_stock_and_usage_count_for_representative(fresh):  # noqa: F811
    base = _snapshot(fresh).stock
    child = _part(fresh, _a42(fresh), merged_into=A42)
    _move(fresh, child, 5)
    _move(fresh, child, -1, "OUT")
    snapshot = _snapshot(fresh)
    assert snapshot.stock == base + 4
    assert snapshot.has_usage_history is True


def test_hidden_twin_includes_its_merged_parts(fresh):  # noqa: F811
    a42 = _a42(fresh)
    twin = _part(fresh, a42, name="브이벨트 A42")
    _move(fresh, twin, 3)
    child = _part(fresh, a42, name="V-belt A42", merged_into=twin)
    _move(fresh, child, 7)
    hidden = {h.part_id: h.qty for h in _snapshot(fresh).hidden}
    assert hidden[str(twin)] == 10
    assert str(child) not in hidden
