import pytest
from bjk_server.config import get_settings
from bjk_server.db.models import Movement
from bjk_server.main import create_app
from bjk_server.seed.demo import demo_id
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .conftest import auth_header

URL = "/api/v1/dev/seed/reset"


def _movement_count(db) -> int:
    with Session(db.admin) as s:
        return s.scalar(select(func.count()).select_from(Movement))


def test_owner_resets_to_seed_state(client, demo_db):
    seeded = _movement_count(demo_db)
    with Session(demo_db.admin) as s, s.begin():
        s.add(
            Movement(
                company_id=demo_id("company", "HS7F3K"),
                part_id=demo_id("part", "6205"),
                type="OUT",
                qty=-1,
            )
        )
    assert _movement_count(demo_db) == seeded + 1

    res = client.post(URL, json={"scenario": "demo_v1"}, headers=auth_header("owner"))
    assert res.status_code == 200
    assert res.json()["company_code"] == "HS7F3K"
    assert _movement_count(demo_db) > 0
    # 오늘 날짜 기준으로 다시 만들므로 수량 합계로 같은 시연 상태인지 본다.
    with Session(demo_db.admin) as s:
        stock = s.scalar(
            select(func.sum(Movement.qty)).where(Movement.part_id == demo_id("part", "6205"))
        )
    assert stock == 3


@pytest.mark.parametrize("user", ["manager", "worker"])
def test_non_owner_is_forbidden(client, user):
    res = client.post(URL, json={}, headers=auth_header(user))
    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN_ROLE"


def test_missing_token_is_401(client):
    assert client.post(URL, json={}).status_code == 401


def test_unknown_scenario_is_400(client):
    res = client.post(URL, json={"scenario": "demo_v9"}, headers=auth_header("owner"))
    assert res.status_code == 400
    assert res.json()["code"] == "VALIDATION_ERROR"


def test_route_absent_outside_dev(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JWT_SECRET", "p" * 40)
    get_settings.cache_clear()
    try:
        res = TestClient(create_app()).post(URL, json={})
        assert res.status_code == 404
        assert res.json()["code"] == "NOT_FOUND"
    finally:
        get_settings.cache_clear()
