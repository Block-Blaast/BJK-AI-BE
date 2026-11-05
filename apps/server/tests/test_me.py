import uuid

from bjk_server.security import create_access_token
from bjk_server.seed.demo import COMPANY_CODE, demo_id

from .conftest import auth_header

URL = "/api/v1/me"


def test_me_returns_user_and_company(client):
    res = client.get(URL, headers=auth_header("worker"))
    assert res.status_code == 200
    assert res.json() == {
        "id": str(demo_id("user", "worker")),
        "name": "이현장",
        "role": "worker",
        "company": {
            "id": str(demo_id("company", COMPANY_CODE)),
            "name": "한서정밀",
            "code": COMPANY_CODE,
        },
    }


def test_me_without_token_is_401(client):
    res = client.get(URL)
    assert res.status_code == 401
    assert res.json()["code"] == "UNAUTHORIZED"


def test_token_of_other_company_user_is_401(client):
    # RLS로 다른 회사 사용자는 보이지 않는다.
    token = create_access_token(demo_id("user", "owner"), uuid.uuid4(), "owner")
    res = client.get(URL, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401
