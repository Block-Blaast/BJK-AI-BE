import uuid

from bjk_server.db.models import Company, Movement, Part
from bjk_server.seed.demo import demo_id
from sqlalchemy import select
from sqlalchemy.orm import Session

from .conftest import auth_header

P20 = demo_id("part", "p20")


def _get(client, part_id, user="worker", **params):
    return client.get(
        f"/api/v1/parts/{part_id}/movements", params=params, headers=auth_header(user)
    )


def test_lists_movements_latest_first_with_source(client, demo_db):
    demo_db.reseed()
    res = _get(client, P20, limit=100)
    assert res.status_code == 200, res.text
    items = res.json()["items"]
    with Session(demo_db.admin) as s:
        rows = s.scalars(
            select(Movement)
            .where(Movement.part_id == P20)
            .order_by(Movement.occurred_at.desc(), Movement.id.desc())
        ).all()
    assert [i["id"] for i in items] == [str(m.id) for m in rows]
    assert sum(i["qty"] for i in items) == 1040

    out = next(i for i in items if i["type"] == "OUT")
    assert out["author"] == "이현장"
    assert out["source_text"].startswith("오링 P-20")
    assert out["equipment_id"] == str(demo_id("equipment", "eq3"))
    opening = items[-1]
    assert (opening["type"], opening["author"], opening["reason"]) == (
        "ADJUST",
        None,
        "초기 재고 이관",
    )
    assert opening["corrects"] is None


def test_cursor_pages_through_history(client, demo_db):
    demo_db.reseed()
    everything = [i["id"] for i in _get(client, P20, limit=100).json()["items"]]
    ids, cursor = [], None
    while True:
        body = _get(client, P20, limit=3, **({"cursor": cursor} if cursor else {})).json()
        ids += [i["id"] for i in body["items"]]
        if not (cursor := body["next_cursor"]):
            break
    assert ids == everything


def test_unknown_or_other_company_part_is_404(client, demo_db):
    assert _get(client, uuid.uuid4()).status_code == 404
    with Session(demo_db.admin) as s, s.begin():
        other = Company(name="다른 회사", code=uuid.uuid4().hex[:8])
        s.add(other)
        s.flush()
        part = Part(company_id=other.id, name="다른 부품", unit="개")
        s.add(part)
        s.flush()
        other_part = part.id
    try:
        res = _get(client, other_part)
        assert res.status_code == 404
        assert res.json()["code"] == "NOT_FOUND"
    finally:
        demo_db.reseed()
