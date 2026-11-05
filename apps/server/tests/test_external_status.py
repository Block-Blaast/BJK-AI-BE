from datetime import date

import pytest
from bjk_server.db.models import Supplier
from bjk_server.seed.demo import demo_id
from sqlalchemy import update
from sqlalchemy.orm import Session

from .conftest import auth_header
from .test_external_shock import NOW, computed  # noqa: F401

URL = "/api/v1/external/status"


def _status(client, user="manager"):
    res = client.get(URL, headers=auth_header(user))
    assert res.status_code == 200, res.text
    return res.json()


def test_status_shows_indicators_and_category_risks(client, computed):  # noqa: F811
    body = _status(client)
    codes = {i["code"]: i for i in body["indicators"]}
    assert set(codes) == {"FREIGHT", "USDKRW"}
    freight = codes["FREIGHT"]
    assert (freight["name"], freight["series"]) == ("컨테이너 운임지수", "lead")
    assert freight["as_of"] <= "2026-11-04"
    categories = {c["name"]: c for c in body["categories"]}
    assert set(categories) == {"베어링", "V벨트·전동벨트", "볼트·너트", "절삭유·윤활유"}
    assert categories["베어링"]["r_lead"] == freight["r"]
    assert categories["베어링"]["r_price"] == codes["USDKRW"]["r"]
    assert categories["볼트·너트"] == {
        **categories["볼트·너트"],
        "r_lead": 0.0,
        "r_price": 0.0,
        "level": "normal",
    }
    assert body["stale"] is False
    assert body["upcoming_holidays"] == []


def test_status_follows_external_shock(client, computed):  # noqa: F811
    client.post(
        "/api/v1/dev/scenarios/external-shock", json={"enabled": True}, headers=auth_header("owner")
    )
    body = _status(client)
    freight = next(i for i in body["indicators"] if i["code"] == "FREIGHT")
    assert (freight["r"], freight["level"]) == (3.0, "high")
    bearing = next(c for c in body["categories"] if c["name"] == "베어링")
    assert (bearing["r_lead"], bearing["level"]) == (3.0, "high")


def test_status_lists_upcoming_supplier_holidays(client, demo_db, computed):  # noqa: F811
    with Session(demo_db.admin) as s, s.begin():
        s.execute(
            update(Supplier)
            .where(Supplier.id == demo_id("supplier", "a"))
            .values(holidays=[date(2026, 11, 1), date(2026, 11, 10), date(2027, 6, 1)])
        )
    assert _status(client)["upcoming_holidays"] == [
        {"name": "공급사 A 휴무", "start": "2026-11-10", "end": "2026-11-10", "scope": "supplier"}
    ]


def test_stale_without_indicators(client, demo_db):
    demo_db.reseed()
    body = _status(client)
    assert (body["indicators"], body["updated_at"], body["stale"]) == ([], None, True)


@pytest.mark.parametrize("user", ["worker"])
def test_worker_cannot_view(client, user):
    assert client.get(URL, headers=auth_header(user)).status_code == 403
