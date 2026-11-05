"""시연 핵심 흐름: 채팅 발주 요청 → 검토 → 재검토·보완 → 결정 → 발주 → 주문 완료 → 입고 대조.

새 기능 없이 이미 있는 API만 이어 불러 흐름이 끝까지 이어지는지 확인한다(F-CHAT-04, F-REVIEW,
F-APPROVAL, F-LEDGER-04). 검토는 커밋 직후 같은 스레드에서 돌리고(ai 없음 → 양식 의견서),
결정·주문·입고 시각은 고정한다.
"""

import uuid
from datetime import timedelta

import pytest
from bjk_review import OrderRequest
from bjk_server import clock
from bjk_server.auth import set_tenant
from bjk_server.chat.interpreter import Interpretation
from bjk_server.db.models import PurchaseOrder
from bjk_server.jobs.runner import run_job
from bjk_server.reviews.service import create_review, run_review
from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from .chat_fakes import NOW, PARSED
from .conftest import auth_header
from .test_chat_purchase_request import A42, SUPPLIER_A, reviews  # noqa: F401
from .test_review_run import COMPANY, NIGHTLY_AT, WORKER

PARSED.update(
    {
        "V벨트 A-42 30개 시켜주세요, 저번 데서요": Interpretation(
            "PURCHASE_REQUEST", "V벨트 A-42", 30, supplier_text="저번 데"
        ),
        "V벨트 A-42 12개 들어옴": Interpretation("IN", "V벨트 A-42", 12),
    }
)


@pytest.fixture
def flow(chat, client, demo_db, reviews, monkeypatch):  # noqa: F811
    """시드 → 새벽 계산 → 열린 발주 없음. 시각은 set_now로 옮긴다."""
    assert run_job(demo_db.app, "nightly", "manual", now=NIGHTLY_AT).status == "ok"
    with Session(demo_db.admin) as s, s.begin():
        s.execute(delete(PurchaseOrder))

    def set_now(when):
        monkeypatch.setattr(clock, "utcnow", lambda: when)

    set_now(NOW)
    return set_now


def _get(client, path, user="manager"):
    res = client.get(f"/api/v1{path}", headers=auth_header(user))
    assert res.status_code == 200, res.text
    return res.json()


def _post(client, path, body, user="manager", status=200, **headers):
    res = client.post(f"/api/v1{path}", json=body, headers=auth_header(user) | headers)
    assert res.status_code == status, res.text
    return res.json()


def test_purchase_request_to_receipt(client, chat, flow):
    # 1. 작업자 채팅 발주 요청 → 확인 카드 → 검토 생성·실행
    body = chat("V벨트 A-42 30개 시켜주세요, 저번 데서요").json()
    [card] = body["cards"]
    assert (card["type"], card["part_id"], card["qty"]) == ("confirm", str(A42), 30)
    requested = _post(client, f"/chat/entries/{card['entry_id']}/confirm", {}, user="worker")
    review_id = requested["review_id"]

    # 2. 관리자 검토 상세: 수정 권고와 수정안·의견서
    review = _get(client, f"/reviews/{review_id}")
    assert (review["status"], review["verdict"]) == ("reviewed", "revise")
    assert review["proposal"]["qty"] < 30
    assert review["opinion"]["text"]
    assert review_id in [r["id"] for r in _get(client, "/reviews")["items"]]

    # 3. 재검토: 직접 수정 값 미리 보기
    edited = {"qty": 12, "supplier_id": str(SUPPLIER_A), "unit_price": 18000}
    preview = _post(client, f"/reviews/{review_id}/recheck", edited)

    # 4. 결정: 직접 수정 승인 → 승인됨 발주
    decided = _post(
        client,
        f"/reviews/{review_id}/decision",
        {"action": "approve_edited", "edited": edited, "recheck_hash": preview["recheck_hash"]},
        status=201,
        **{"Idempotency-Key": f"flow-{uuid.uuid4()}"},
    )
    order = decided["purchase_order"]
    assert (decided["status"], order["status"], order["qty"]) == ("approved", "approved", 12)
    assert _get(client, f"/reviews/{review_id}")["status"] == "approved"

    # 5. 발주 목록·상세(문자 문구) → 주문 완료 표시
    listed = _get(client, "/purchase-orders?status=approved")["items"]
    assert [o["id"] for o in listed] == [order["id"]]
    detail = _get(client, f"/purchase-orders/{order['id']}")
    assert detail["order_message"].startswith("안녕하세요. V벨트 A-42 12")
    ordered = _post(client, f"/purchase-orders/{order['id']}/mark-ordered", {})
    assert ordered["status"] == "ordered"

    # 6. 5일 뒤 입고 채팅 → 확인 카드 미리 보기 → 확정 시 발주 대조
    flow(NOW + timedelta(days=5))
    [card] = chat("V벨트 A-42 12개 들어옴").json()["cards"]
    assert card["po_match"] == "complete"
    received = _post(client, f"/chat/entries/{card['entry_id']}/confirm", {}, user="worker")
    assert (received["po_match"], received["actual_lead_time_days"]) == ("complete", 5)
    assert received["movement"]["po_id"] == order["id"]
    final = _get(client, f"/purchase-orders/{order['id']}")
    assert (final["status"], final["received_qty"], final["actual_lead_time_days"]) == (
        "received",
        12,
        5,
    )


def test_held_review_is_clarified_then_decided(client, demo_db, flow):
    """보류(부품 미확정) → 보완(부품 지정) → 재실행 → 발주 불필요 수용."""
    scope = sessionmaker(demo_db.app, expire_on_commit=False).begin
    with scope() as s:
        set_tenant(s, COMPANY)
        order = OrderRequest(qty=30, supplier_id=str(SUPPLIER_A), unit_price=18000)
        review_id = create_review(
            s, COMPANY, entry="staff_request", order=order, part_id=None, requested_by=WORKER
        ).id
    assert run_review(scope, None, COMPANY, review_id) == "held"
    _post(client, f"/reviews/{review_id}/clarify", {"part_id": str(A42)}, status=202)
    assert _get(client, f"/reviews/{review_id}")["status"] == "reviewed"
    closed = _post(
        client,
        f"/reviews/{review_id}/decision",
        {"action": "accept_no_order"},
        **{"Idempotency-Key": f"flow-{uuid.uuid4()}"},
    )
    assert (closed["status"], closed["purchase_order"]) == ("closed", None)


def _has_pango() -> bool:
    """결재용 PDF는 시스템 pango가 있어야 만든다(macOS `make` 환경에서는 없음)."""
    try:
        import weasyprint  # noqa: F401
    except OSError:
        return False
    return True


def _order_and_receive(client, chat, flow, order_id, qty):
    """주문 완료 표시 → 5일 뒤 입고 채팅 확정 → 입고완료."""
    detail = _get(client, f"/purchase-orders/{order_id}")
    assert detail["order_message"].startswith(f"안녕하세요. V벨트 A-42 {qty}")
    _post(client, f"/purchase-orders/{order_id}/mark-ordered", {})
    flow(NOW + timedelta(days=5))
    PARSED[f"V벨트 A-42 {qty}개 들어옴"] = Interpretation("IN", "V벨트 A-42", qty)
    [card] = chat(f"V벨트 A-42 {qty}개 들어옴").json()["cards"]
    received = _post(client, f"/chat/entries/{card['entry_id']}/confirm", {}, user="worker")
    assert (received["po_match"], received["movement"]["po_id"]) == ("complete", order_id)
    final = _get(client, f"/purchase-orders/{order_id}")
    assert (final["status"], final["received_qty"]) == ("received", qty)


def _approve_proposal(client, review_id):
    review = _get(client, f"/reviews/{review_id}")
    return _post(
        client,
        f"/reviews/{review_id}/decision",
        {"action": "approve_proposal", "snapshot_hash": review["snapshot"]["hash"]},
        status=201,
        **{"Idempotency-Key": f"flow-{uuid.uuid4()}"},
    )["purchase_order"]


def test_worker_view_question_and_pdf(client, chat, flow):
    """작업자는 자기 요청을 보고, 관리자는 질문하고 승인한 뒤 결재용 PDF를 받는다."""
    [card] = chat("V벨트 A-42 30개 시켜주세요, 저번 데서요").json()["cards"]
    review_id = _post(client, f"/chat/entries/{card['entry_id']}/confirm", {}, user="worker")[
        "review_id"
    ]
    assert _get(client, f"/reviews/{review_id}", user="worker")["id"] == review_id
    mine = _get(client, "/reviews", user="worker")["items"]
    assert [r["id"] for r in mine] == [review_id]
    answer = _post(client, f"/reviews/{review_id}/questions", {"question": "왜 그 수량이야?"})
    assert (answer["topic"], answer["source"]) == ("qty", "template")
    order = _approve_proposal(client, review_id)
    if _has_pango():
        pdf = client.get(f"/api/v1/reviews/{review_id}/pdf", headers=auth_header("owner"))
        assert (pdf.status_code, pdf.headers["content-type"]) == (200, "application/pdf")
    _order_and_receive(client, chat, flow, order["id"], order["qty"])


def test_held_review_clarified_by_worker_then_approved(client, chat, demo_db, flow):
    """보류(부품 미확정) → 작업자 보완 → 직접 수정 승인 → 주문 완료 → 입고완료."""
    scope = sessionmaker(demo_db.app, expire_on_commit=False).begin
    with scope() as s:
        set_tenant(s, COMPANY)
        order = OrderRequest(qty=30, supplier_id=str(SUPPLIER_A), unit_price=18000)
        review_id = create_review(
            s, COMPANY, entry="staff_request", order=order, part_id=None, requested_by=WORKER
        ).id
    assert run_review(scope, None, COMPANY, review_id) == "held"
    held = _get(client, f"/reviews/{review_id}", user="worker")
    assert held["hold_reasons"][0] == "part_unresolved"
    _post(client, f"/reviews/{review_id}/clarify", {"part_id": str(A42)}, user="worker", status=202)
    edited = {"qty": 8, "supplier_id": str(SUPPLIER_A), "unit_price": 18000}
    preview = _post(client, f"/reviews/{review_id}/recheck", edited)
    decided = _post(
        client,
        f"/reviews/{review_id}/decision",
        {"action": "approve_edited", "edited": edited, "recheck_hash": preview["recheck_hash"]},
        status=201,
        **{"Idempotency-Key": f"flow-{uuid.uuid4()}"},
    )
    _order_and_receive(client, chat, flow, decided["purchase_order"]["id"], 8)


def test_stock_draft_to_receipt(client, chat, demo_db, flow, monkeypatch):
    """출고로 재주문점을 벗어나면 재고 부족 초안 → 수정안 승인 → 주문 완료 → 입고완료."""
    from bjk_server.db.models import PartMetrics
    from bjk_server.reviews import drafts
    from bjk_server.reviews.service import ReviewRunner
    from sqlalchemy import select

    from .test_chat_purchase_request import _Inline

    scope = sessionmaker(demo_db.app, expire_on_commit=False).begin
    monkeypatch.setattr(drafts, "request_runner", lambda db: ReviewRunner(scope, None, _Inline()))
    with Session(demo_db.admin) as s:
        m = s.scalar(select(PartMetrics).where(PartMetrics.part_id == A42))
    qty = max(1, m.stock + m.hidden_confirmed - m.reorder_point)
    out = {
        "client_message_id": f"out-{uuid.uuid4()}",
        "type": "OUT",
        "part_id": str(A42),
        "qty": qty,
    }
    recorded = _post(client, "/chat/entries", out, user="worker")
    draft_id = recorded["triggered"]["draft_review_id"]
    assert draft_id is not None
    draft = _get(client, f"/reviews/{draft_id}")
    assert (draft["entry"], draft["requested_by"], draft["status"]) == (
        "stock_draft",
        None,
        "reviewed",
    )
    order = _approve_proposal(client, draft_id)
    _order_and_receive(client, chat, flow, order["id"], order["qty"])
