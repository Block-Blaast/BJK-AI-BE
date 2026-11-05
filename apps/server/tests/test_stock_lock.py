"""재고를 바꾸는 경로의 부품 행 잠금 (#69)."""

import pytest
from bjk_server.inventory import lock_part_stock
from bjk_server.seed.demo import demo_id
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

COMPANY = demo_id("company", "HS7F3K")
PART = demo_id("part", "6205")
OTHER_PART = demo_id("part", "p20")


def _try_lock(engine, part_id) -> bool:
    with Session(engine) as s, s.begin():
        s.execute(text("SET LOCAL lock_timeout = '200ms'"))
        return lock_part_stock(s, COMPANY, part_id)


def test_same_part_waits_other_part_proceeds(demo_db):
    with Session(demo_db.admin) as holder, holder.begin():
        assert lock_part_stock(holder, COMPANY, PART)
        with pytest.raises(OperationalError, match="lock timeout"):
            _try_lock(demo_db.admin, PART)
        assert _try_lock(demo_db.admin, OTHER_PART)
    assert _try_lock(demo_db.admin, PART)


def test_other_company_part_is_not_locked(demo_db):
    with Session(demo_db.admin) as s, s.begin():
        assert not lock_part_stock(s, demo_id("company", "nope"), PART)
