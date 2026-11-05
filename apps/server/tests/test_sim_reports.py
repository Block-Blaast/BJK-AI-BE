"""검증 리포트 목록 (F-SIM, W-09, #260)."""

import uuid

from bjk_server.auth import set_tenant
from bjk_server.db.models import Company, SimReport
from sqlalchemy.orm import Session

from .conftest import auth_header


def test_manager_sees_sample_reports_newest_first(client, demo_db):
    demo_db.reseed()
    res = client.get("/api/v1/sim-reports", headers=auth_header("manager"))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["next_cursor"] is None
    assert [i["title"] for i in body["items"]] == [
        "[시연용] 현장 방식 대비 정책 재생 (결품·재고 금액)",
        "[시연용] 검토 기준값 탐지율 평가 (합성 데이터 18개월)",
    ]
    assert {i["source"] for i in body["items"]} == {"sample"}
    assert {i["pdf_url"] for i in body["items"]} == {None}


def test_cursor_pages_reports(client, demo_db):
    demo_db.reseed()
    first = client.get("/api/v1/sim-reports?limit=1", headers=auth_header("owner")).json()
    assert len(first["items"]) == 1 and first["next_cursor"]
    second = client.get(
        f"/api/v1/sim-reports?limit=1&cursor={first['next_cursor']}",
        headers=auth_header("owner"),
    ).json()
    assert second["next_cursor"] is None
    assert second["items"][0]["id"] != first["items"][0]["id"]


def test_worker_cannot_list_reports(client, demo_db):
    demo_db.reseed()
    res = client.get("/api/v1/sim-reports", headers=auth_header("worker"))
    assert (res.status_code, res.json()["code"]) == (403, "FORBIDDEN_ROLE")


def test_other_company_reports_are_hidden(client, demo_db):
    demo_db.reseed()
    other = uuid.uuid4()
    with Session(demo_db.admin) as s, s.begin():
        s.add(Company(id=other, name="다른 회사", code="OTHER1"))
        s.flush()
        set_tenant(s, other)
        s.add(SimReport(company_id=other, title="다른 회사 리포트", source="harness"))
    items = client.get("/api/v1/sim-reports", headers=auth_header("manager")).json()["items"]
    assert "다른 회사 리포트" not in [i["title"] for i in items]
