import uuid

import pytest
from bjk_server.db.models import Part
from bjk_server.security import create_access_token
from bjk_server.seed.demo import PARTS, demo_id
from sqlalchemy.orm import Session

from .conftest import auth_header

URL = "/api/v1/parts"


def _get(client, user="worker", **params):
    return client.get(URL, params=params, headers=auth_header(user))


def test_lists_all_parts_by_name_with_event_sum_stock(client):
    res = _get(client)
    assert res.status_code == 200
    items = res.json()["items"]
    assert [i["name"] for i in items] == sorted(p.name for p in PARTS)
    stock = {i["name"]: i["stock"] for i in items}
    assert stock == {p.name: p.stock for p in PARTS}
    bearing = next(i for i in items if i["name"] == "볼베어링 6205ZZ")
    assert bearing["category"] == "베어링"
    assert bearing["unit"] == "개"


def test_metrics_are_null_before_nightly(client):
    item = _get(client).json()["items"][0]
    for key in ("abc", "demand_class", "t_out", "p_out", "risk_level", "computed_at"):
        assert item[key] is None
    assert item["ledger_status"] == "normal"


@pytest.mark.parametrize(
    ("q", "expected"),
    [
        ("6205", ["볼베어링 6205ZZ"]),
        ("베어링 작은", ["볼베어링 6205ZZ"]),  # 별칭
        ("m8", ["육각볼트 M8-20"]),  # 규격 값, 대소문자 무시
        ("bearing_no", []),  # 규격 키는 검색하지 않음
        ("%", []),  # LIKE 와일드카드는 글자로 취급
    ],
)
def test_search_by_name_alias_and_spec(client, q, expected):
    assert [i["name"] for i in _get(client, q=q).json()["items"]] == expected


def test_filter_by_category(client):
    res = _get(client, category_id=str(demo_id("category", "bearing")))
    assert [i["name"] for i in res.json()["items"]] == ["볼베어링 6204ZZ", "볼베어링 6205ZZ"]


def test_metric_filters_return_nothing_before_nightly(client):
    assert _get(client, abc="A").json()["items"] == []
    assert _get(client, ledger_status="suspect").json()["items"] == []
    assert len(_get(client, ledger_status="normal").json()["items"]) == len(PARTS)


def test_cursor_pages_through_all(client):
    names, cursor = [], None
    while True:
        params = {"limit": 4} | ({"cursor": cursor} if cursor else {})
        body = _get(client, **params).json()
        names += [i["name"] for i in body["items"]]
        cursor = body["next_cursor"]
        if not cursor:
            break
    assert names == sorted(p.name for p in PARTS)


def test_merged_parts_are_hidden(client, demo_db):
    with Session(demo_db.admin) as s, s.begin():
        s.get(Part, demo_id("part", "m820")).merged_into = demo_id("part", "p20")
    try:
        assert "육각볼트 M8-20" not in [i["name"] for i in _get(client).json()["items"]]
    finally:
        demo_db.reseed()


def test_other_company_sees_nothing(client):
    token = create_access_token(uuid.uuid4(), uuid.uuid4(), "owner")
    res = client.get(URL, headers={"Authorization": f"Bearer {token}"})
    assert res.json() == {"items": [], "next_cursor": None}


def test_requires_login(client):
    assert client.get(URL).status_code == 401


def test_invalid_filter_value_is_400(client):
    assert _get(client, abc="Z").status_code == 400
