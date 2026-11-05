import pytest
from alembic import command
from bjk_server.db.models import EMBEDDING_DIM, Part, PartAlias
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

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
    "part_imports",
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


EMBEDDING_TABLES = ("parts", "part_aliases")


@pytest.fixture
def part_row(migrated_db_url):
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
    yield engine, company, part
    engine.dispose()


def test_embedding_columns_are_vector_1024_with_model_name(part_row):
    engine, _, _ = part_row
    with engine.connect() as conn:
        for table in EMBEDDING_TABLES:
            columns = dict(
                conn.execute(
                    text(
                        "SELECT attname, format_type(atttypid, atttypmod) FROM pg_attribute "
                        "WHERE attrelid = CAST(:t AS regclass) AND attname LIKE 'embedding%'"
                    ),
                    {"t": table},
                ).all()
            )
            assert columns == {
                "embedding": "vector(1024)",
                "embedding_model": "character varying(100)",
            }


def test_orm_stores_embedding_and_compares_by_cosine(part_row):
    engine, company, part_id = part_row
    vector = [1.0] + [0.0] * (EMBEDDING_DIM - 1)
    with Session(engine) as session, session.begin():
        part = session.get(Part, part_id)
        part.embedding, part.embedding_model = vector, "m1"
        session.add(
            PartAlias(
                company_id=company,
                part_id=part_id,
                text="a",
                embedding=vector,
                embedding_model="m1",
            )
        )

    with Session(engine) as session:
        part = session.get(Part, part_id)
        assert part.embedding == vector
        assert part.embedding_model == "m1"
        distance = session.scalar(
            select(PartAlias.embedding.cosine_distance(vector)).where(PartAlias.part_id == part_id)
        )
        assert distance == pytest.approx(0.0)


@pytest.mark.parametrize("table", EMBEDDING_TABLES)
@pytest.mark.parametrize(
    ("dimension", "model", "error"),
    [
        (2, "m1", "expected 1024 dimensions"),
        (EMBEDDING_DIM, None, "embedding_model"),
        (None, "m1", "embedding_model"),
    ],
)
def test_embedding_rejects_wrong_dimension_or_unpaired_model(
    part_row, table, dimension, model, error
):
    engine, company, part = part_row
    vector = None if dimension is None else str([0.1] * dimension)
    columns = {
        "parts": "company_id, name, unit",
        "part_aliases": "company_id, part_id, text",
    }[table]
    values = {"parts": ":c, 'p', '개'", "part_aliases": ":c, :p, 'a'"}[table]
    with pytest.raises(DBAPIError, match=error), engine.begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO {table} ({columns}, embedding, embedding_model) "
                f"VALUES ({values}, CAST(:v AS vector), :m)"
            ),
            {"c": company, "p": part, "v": vector, "m": model},
        )


def test_downgrade_0011_removes_embedding_columns(empty_db_url):
    config = alembic_config(empty_db_url)
    engine = create_engine(empty_db_url)
    command.upgrade(config, "head")

    command.downgrade(config, "0011")
    for table in EMBEDDING_TABLES:
        columns = {column["name"] for column in inspect(engine).get_columns(table)}
        assert not {"embedding", "embedding_model"} & columns
    with engine.connect() as conn:
        assert not conn.scalar(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'"))
    engine.dispose()


def _embedding_state(conn, part) -> tuple[str, str | None]:
    column = conn.scalar(
        text(
            "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
            "WHERE attrelid = 'parts'::regclass AND attname = 'embedding'"
        )
    )
    return column, conn.scalar(text("SELECT embedding_model FROM parts WHERE id = :p"), {"p": part})


def _part_with_embedding(conn, dimension: int):
    company = conn.execute(
        text("INSERT INTO companies (name, code) VALUES ('t', 'c0019') RETURNING id")
    ).scalar_one()
    return conn.execute(
        text(
            "INSERT INTO parts (company_id, name, unit, embedding, embedding_model) "
            "VALUES (:c, 'p', '개', CAST(:v AS vector), 'm1') RETURNING id"
        ),
        {"c": company, "v": str([0.1] * dimension)},
    ).scalar_one()


def test_0019_keeps_embeddings_already_1024(empty_db_url):
    # main 배포 DB: 0012(1024)까지 적용되고 벡터가 있는 상태에서 head로 올린다.
    config = alembic_config(empty_db_url)
    engine = create_engine(empty_db_url)
    command.upgrade(config, "0018")
    with engine.begin() as conn:
        part = _part_with_embedding(conn, 1024)

    command.upgrade(config, "head")
    with engine.connect() as conn:
        assert _embedding_state(conn, part) == ("vector(1024)", "m1")
    engine.dispose()


def test_0019_resizes_old_1536_columns(empty_db_url):
    # 이전 0012(1536)로 만든 로컬 DB: 벡터를 비우고 1024로 바꾼다.
    config = alembic_config(empty_db_url)
    engine = create_engine(empty_db_url)
    command.upgrade(config, "0018")
    with engine.begin() as conn:
        for table in EMBEDDING_TABLES:
            conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN embedding TYPE vector(1536)"))
        part = _part_with_embedding(conn, 1536)

    command.upgrade(config, "head")
    with engine.connect() as conn:
        assert _embedding_state(conn, part) == ("vector(1024)", None)
        alias_column = conn.scalar(
            text(
                "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                "WHERE attrelid = 'part_aliases'::regclass AND attname = 'embedding'"
            )
        )
        assert alias_column == "vector(1024)"
    engine.dispose()
