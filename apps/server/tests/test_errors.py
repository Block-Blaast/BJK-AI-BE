from typing import Annotated

import pytest
from bjk_server.errors import ApiError, ErrorCode
from bjk_server.main import create_app
from bjk_server.pagination import PageParams, page_params
from fastapi import Depends, Query
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    app = create_app()

    @app.get("/_test/conflict")
    def conflict():
        raise ApiError(
            ErrorCode.REVIEW_NOT_DECIDABLE,
            "검토가 끝난 건만 결정할 수 있습니다.",
            {"status": "held"},
        )

    @app.get("/_test/rate")
    def rate():
        raise ApiError(
            ErrorCode.RATE_LIMITED, "잠시 후 다시 시도하세요.", headers={"Retry-After": "30"}
        )

    @app.get("/_test/number")
    def number(n: Annotated[int, Query()]):
        return {"n": n}

    @app.get("/_test/page")
    def page(params: Annotated[PageParams, Depends(page_params)]):
        return {"cursor": params.cursor, "limit": params.limit}

    return TestClient(app)


def test_api_error_uses_common_body(client):
    res = client.get("/_test/conflict")
    assert res.status_code == 409
    assert res.json() == {
        "code": "REVIEW_NOT_DECIDABLE",
        "message": "검토가 끝난 건만 결정할 수 있습니다.",
        "detail": {"status": "held"},
    }


def test_api_error_keeps_headers(client):
    res = client.get("/_test/rate")
    assert res.status_code == 429
    assert res.headers["Retry-After"] == "30"


def test_validation_error_is_400(client):
    res = client.get("/_test/number", params={"n": "abc"})
    assert res.status_code == 400
    body = res.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["detail"]["errors"][0]["loc"] == ["query", "n"]


def test_unknown_route_is_not_found(client):
    res = client.get("/api/v1/nothing")
    assert res.status_code == 404
    assert res.json()["code"] == "NOT_FOUND"


def test_page_params_default_and_max(client):
    assert client.get("/_test/page").json() == {"cursor": None, "limit": 20}
    assert client.get("/_test/page", params={"limit": 100}).json()["limit"] == 100
    res = client.get("/_test/page", params={"limit": 101})
    assert res.status_code == 400
    assert res.json()["code"] == "VALIDATION_ERROR"


def test_every_error_code_has_status():
    from bjk_server.errors import STATUS

    assert set(STATUS) == set(ErrorCode)
