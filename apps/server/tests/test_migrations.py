import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError

from .conftest import alembic_config

TABLES = {
    "companies",
    "users",
    "company_settings",
    "categories",
    "parts",
    "part_aliases",
    "suppliers",
    "supplier_parts",
    "equipment",
    "equipment_parts",
    "maintenance",
    "movements",
    "idempotency_keys",
}


def test_upgrade_creates_all_tables_and_downgrade_removes_them(empty_db_url):
    config = alembic_config(empty_db_url)
    engine = create_engine(empty_db_url)

    command.upgrade(config, "head")
    assert TABLES <= set(inspect(engine).get_table_names())

    command.downgrade(config, "base")
    assert not TABLES & set(inspect(engine).get_table_names())
    engine.dispose()


@pytest.fixture
def movement_id(migrated_db_url):
    engine = create_engine(migrated_db_url)
    with engine.begin() as conn:
        company = conn.execute(
            text(
                "INSERT INTO companies (name, code) "
                "VALUES ('t', substr(md5(random()::text), 1, 8)) RETURNING id"
            )
        ).scalar_one()
        part = conn.execute(
            text("INSERT INTO parts (company_id, name, unit) VALUES (:c, 'p', '개') RETURNING id"),
            {"c": company},
        ).scalar_one()
        movement = conn.execute(
            text(
                "INSERT INTO movements (company_id, part_id, type, qty) "
                "VALUES (:c, :p, 'IN', 3) RETURNING id"
            ),
            {"c": company, "p": part},
        ).scalar_one()
    yield engine, movement
    engine.dispose()


@pytest.mark.parametrize(
    "statement",
    ["UPDATE movements SET qty = 5 WHERE id = :id", "DELETE FROM movements WHERE id = :id"],
)
def test_movements_reject_update_and_delete(movement_id, statement):
    engine, movement = movement_id
    with pytest.raises(DBAPIError, match="append-only"), engine.begin() as conn:
        conn.execute(text(statement), {"id": movement})


def test_movements_reject_wrong_qty_sign(movement_id):
    engine, _ = movement_id
    with pytest.raises(DBAPIError, match="ck_movements_qty_sign"), engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO movements (company_id, part_id, type, qty) "
                "SELECT company_id, part_id, 'OUT', 2 FROM movements LIMIT 1"
            )
        )


def test_test_database_uses_production_collation(empty_db_url):
    from .conftest import TEST_DB_LOCALE

    engine = create_engine(empty_db_url)
    with engine.connect() as conn:
        # PostgreSQL 16부터 lc_collate 설정이 없어 pg_database에서 읽는다.
        collate = conn.scalar(
            text("SELECT datcollate FROM pg_database WHERE datname = current_database()")
        )
        assert collate == TEST_DB_LOCALE
    engine.dispose()
