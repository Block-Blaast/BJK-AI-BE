from datetime import date

import pytest
from alembic import command
from bjk_server.db.models import Category, Company, Movement, Part, User
from bjk_server.security import verify_secret
from bjk_server.seed.demo import PARTS, USERS, demo_id, seed_demo
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from .conftest import _base_url, alembic_config, temp_database

TODAY = date(2026, 11, 4)


@pytest.fixture(scope="module")
def seed_engine():
    with temp_database(_base_url()) as url:
        command.upgrade(alembic_config(url), "head")
        engine = create_engine(url)
        yield engine
        engine.dispose()


def _seed(engine, today=TODAY):
    with Session(engine) as s, s.begin():
        seed_demo(s, today=today)


def _snapshot(engine):
    with Session(engine) as s:
        return {
            "movements": s.execute(
                select(
                    Movement.id, Movement.part_id, Movement.type, Movement.qty, Movement.occurred_at
                ).order_by(Movement.id)
            ).all(),
            "parts": s.scalars(select(Part.id).order_by(Part.id)).all(),
        }


def test_seed_creates_demo_company(seed_engine):
    _seed(seed_engine)
    with Session(seed_engine) as s:
        company = s.scalar(select(Company))
        assert (company.name, company.code) == ("한서정밀", "HS7F3K")
        assert s.scalar(select(func.count()).select_from(User)) == len(USERS)
        names = set(s.scalars(select(Category.name)))
        assert {"베어링", "V벨트·전동벨트", "볼트·너트", "절삭유·윤활유"} <= names


def test_event_sum_matches_target_stock(seed_engine):
    _seed(seed_engine)
    with Session(seed_engine) as s:
        for p in PARTS:
            stock = s.scalar(
                select(func.sum(Movement.qty)).where(Movement.part_id == demo_id("part", p.key))
            )
            assert stock == p.stock, p.name


def test_history_covers_at_least_8_weeks(seed_engine):
    _seed(seed_engine)
    with Session(seed_engine) as s:
        first = s.scalar(select(func.min(Movement.occurred_at)).where(Movement.type == "OUT"))
        assert (TODAY - first.date()).days >= 8 * 7


def test_demo_accounts_can_be_verified(seed_engine):
    _seed(seed_engine)
    with Session(seed_engine) as s:
        for u in USERS:
            user = s.get(User, demo_id("user", u.key))
            if u.password:
                assert verify_secret(user.password_hash, u.password)
            if u.pin:
                assert verify_secret(user.pin_hash, u.pin)


def test_rerun_reproduces_same_state(seed_engine):
    _seed(seed_engine)
    first = _snapshot(seed_engine)
    _seed(seed_engine)
    assert _snapshot(seed_engine) == first


def test_unknown_scenario_is_rejected(seed_engine):
    with Session(seed_engine) as s, pytest.raises(ValueError):
        seed_demo(s, scenario="nope")
