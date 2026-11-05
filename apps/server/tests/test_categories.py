import uuid

import pytest
from bjk_server.jobs import registry  # noqa: F401
from bjk_server.jobs.runner import run_job
from bjk_server.seed.demo import demo_id

from .conftest import auth_header

URL = "/api/v1/categories"


@pytest.fixture
def fresh(demo_db):
    demo_db.reseed()


def test_lists_seed_categories_by_name(client, fresh):
    res = client.get(URL, headers=auth_header("manager"))
    assert res.status_code == 200, res.text
    items = res.json()["items"]
    assert [c["name"] for c in items] == ["V벨트·전동벨트", "베어링", "볼트·너트", "절삭유·윤활유"]
    bearing = next(c for c in items if c["name"] == "베어링")
    assert bearing == {
        "id": str(demo_id("category", "bearing")),
        "name": "베어링",
        "import_dependency": "high",
        "lead_factors": ["FREIGHT", "HOLIDAY_CN"],
        "price_factors": ["USDKRW"],
        "hs_code": "8482",
    }


def test_create_and_update_category(client, fresh):
    res = client.post(
        URL,
        json={
            "name": " 체인 ",
            "import_dependency": "medium",
            "lead_factors": ["FREIGHT", "FREIGHT"],
            "price_factors": ["USDKRW"],
        },
        headers=auth_header("manager"),
    )
    assert res.status_code == 201, res.text
    created = res.json()
    assert (created["name"], created["lead_factors"], created["hs_code"]) == (
        "체인",
        ["FREIGHT"],
        None,
    )

    patched = client.patch(
        f"{URL}/{created['id']}",
        json={"import_dependency": "low", "hs_code": "7315"},
        headers=auth_header("manager"),
    ).json()
    assert (patched["import_dependency"], patched["hs_code"], patched["name"]) == (
        "low",
        "7315",
        "체인",
    )


def test_duplicate_name_is_409(client, fresh):
    res = client.post(URL, json={"name": "베어링"}, headers=auth_header("manager"))
    assert res.status_code == 409
    assert res.json()["code"] == "NAME_TAKEN"
    bolt = demo_id("category", "bolt")
    res = client.patch(f"{URL}/{bolt}", json={"name": "베어링"}, headers=auth_header("manager"))
    assert res.status_code == 409
    # 자기 이름 그대로는 허용
    res = client.patch(f"{URL}/{bolt}", json={"name": "볼트·너트"}, headers=auth_header("manager"))
    assert res.status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        {"name": "x", "lead_factors": ["UNKNOWN"]},
        {"name": "x", "import_dependency": "none"},
        {"name": ""},
        {"name": "   "},
    ],
)
def test_invalid_category_is_400(client, fresh, body):
    assert client.post(URL, json=body, headers=auth_header("manager")).status_code == 400


def test_update_rejects_null_required_and_unknown_id(client, fresh):
    bolt = demo_id("category", "bolt")
    res = client.patch(f"{URL}/{bolt}", json={"name": None}, headers=auth_header("manager"))
    assert res.status_code == 400
    res = client.patch(
        f"{URL}/{uuid.uuid4()}", json={"hs_code": "1"}, headers=auth_header("manager")
    )
    assert res.status_code == 404


def test_worker_cannot_manage_categories(client, fresh):
    assert client.get(URL, headers=auth_header("worker")).status_code == 403
    assert client.post(URL, json={"name": "x"}, headers=auth_header("worker")).status_code == 403


def test_category_factors_feed_nightly_risk(client, demo_db, fresh):
    bolt = demo_id("category", "bolt")
    client.patch(
        f"{URL}/{bolt}",
        json={"import_dependency": "high", "lead_factors": ["FREIGHT"]},
        headers=auth_header("manager"),
    )
    assert run_job(demo_db.app, "nightly", "manual").status == "ok"
    status = client.get("/api/v1/external/status", headers=auth_header("manager")).json()
    freight = next(i for i in status["indicators"] if i["code"] == "FREIGHT")
    bolt_risk = next(c for c in status["categories"] if c["name"] == "볼트·너트")
    assert bolt_risk["r_lead"] == freight["r"]
