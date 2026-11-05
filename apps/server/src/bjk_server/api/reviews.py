"""발주 검토 조회 API (API 명세서 REV-01·02).

검토 결과는 검토 실행 서비스(`bjk_server.reviews`)가 `reviews.result`에 저장한
`bjk_review.ReviewResult` 구조(판정·표시·보류 사유·해시 제외)를 그대로 읽는다.
manager 이상은 회사 전체, worker는 본인이 올린 요청만 본다. 남의 검토는 404.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from bjk_server.auth import CurrentUser, TenantDB
from bjk_server.clock import KST
from bjk_server.db.models import Part, Review, ReviewSnapshot, User
from bjk_server.errors import ApiError, ErrorCode
from bjk_server.security import TokenClaims

router = APIRouter(prefix="/reviews", tags=["reviews"])

Entry = Literal["staff_request", "stock_draft", "missed_draft"]
Status = Literal["reviewing", "reviewed", "held", "approved", "closed", "expired"]
Verdict = Literal["ok", "revise", "hold"]


class Requester(BaseModel):
    type: Literal["user"] = "user"
    id: uuid.UUID
    name: str


class SupplierRef(BaseModel):
    id: str
    name: str


class Line(BaseModel):
    qty: int
    supplier: SupplierRef | None
    unit_price: int | None
    total: int


class Proposal(Line):
    saving: int
    no_order: bool
    basis: list[str]


class Alternative(Line):
    id: str
    kind: str
    saving: int


class Opinion(BaseModel):
    text: str
    source: Literal["llm", "template"]
    verified: bool


class SnapshotOut(BaseModel):
    id: uuid.UUID
    hash: str
    values: dict[str, Any]


class ReviewDetail(BaseModel):
    id: uuid.UUID
    entry: Entry
    part: str | None
    requested_by: Requester | None
    status: Status
    verdict: Verdict | None
    flags: list[str]
    hold_reasons: list[str]
    checks: list[dict[str, Any]]
    original: Line | None
    proposal: Proposal | None
    alternatives: list[Alternative]
    risk_if_not_ordered: dict[str, Any] | None
    count_requests: list[dict[str, Any]]
    opinion: Opinion | None
    snapshot: SnapshotOut | None
    computed_at: datetime | None
    expires_at: datetime | None
    decision: dict[str, Any] | None
    created_at: datetime


def visible_reviews(user: TokenClaims):
    """역할에 따라 볼 수 있는 검토. worker는 본인 요청만."""
    stmt = select(Review)
    if user.role == "worker":
        stmt = stmt.where(Review.requested_by == user.user_id)
    return stmt


def _supplier(line: dict[str, Any]) -> SupplierRef | None:
    if line.get("supplier_id") is None:
        return None
    return SupplierRef(id=line["supplier_id"], name=line.get("supplier_name") or "")


def _line_fields(line: dict[str, Any]) -> dict[str, Any]:
    return {
        "qty": line["qty"],
        "supplier": _supplier(line),
        "unit_price": line.get("unit_price"),
        "total": line["total"],
    }


def snapshot_values(values: dict[str, Any], request_qty: int | None) -> dict[str, Any]:
    """저장한 스냅샷에서 명세의 근거 수치 키(Q, S, O, H_c, ...)를 뽑는다."""
    hidden = values.get("hidden", [])
    h_c = sum(h["qty"] for h in hidden if h["confirmed"])
    h_u = sum(h["qty"] for h in hidden if not h["confirmed"])
    stock, incoming, d95 = values["stock"], values.get("incoming", 0), values["d95"]
    default = next(
        (
            s
            for s in values.get("suppliers", [])
            if s["supplier_id"] == values.get("default_supplier_id")
        ),
        None,
    )
    p = sum(r["qty"] for r in values.get("open_requests", []))
    return {
        "Q": request_qty,
        "S": stock,
        "O": incoming,
        "H_c": h_c,
        "H_u": h_u,
        "P": p,
        "m": values.get("m", 0.0),
        "F": values.get("f_period", 0),
        "D95": d95,
        "D99": values["d99"],
        "R": max(0, d95 - stock - incoming - h_c - p),
        "MOQ": default["moq"] if default else None,
        "p_mean": values.get("price_stats", {}).get("mean"),
    }


@router.get("/{review_id}", response_model=ReviewDetail)
def get_review(review_id: uuid.UUID, user: CurrentUser, db: TenantDB) -> ReviewDetail:
    """REV-02. 판정·체크·원안·수정안·대안·미발주 리스크·의견서·스냅샷."""
    review = db.scalar(visible_reviews(user).where(Review.id == review_id))
    if review is None:
        raise ApiError(ErrorCode.NOT_FOUND, "검토를 찾을 수 없습니다.")
    snap = db.scalar(
        select(ReviewSnapshot)
        .where(ReviewSnapshot.review_id == review.id)
        .order_by(ReviewSnapshot.created_at.desc(), ReviewSnapshot.id)
        .limit(1)
    )
    requester = db.get(User, review.requested_by) if review.requested_by else None
    result = review.result or {}
    proposal = result.get("proposal")
    request_qty = (review.request or {}).get("qty")
    part_name = snap.values.get("part_name") if snap else None
    if part_name is None and review.part_id is not None:
        part = db.get(Part, review.part_id)
        part_name = part.name if part else None
    return ReviewDetail(
        id=review.id,
        entry=review.entry,
        part=part_name,
        requested_by=Requester(id=requester.id, name=requester.name) if requester else None,
        status=review.status,
        verdict=review.verdict,
        flags=review.flags,
        hold_reasons=review.hold_reasons,
        checks=result.get("checks", []),
        original=Line(**_line_fields(result["original"])) if "original" in result else None,
        proposal=Proposal(
            **_line_fields(proposal),
            saving=proposal["saving"],
            no_order=proposal["no_order"],
            basis=proposal["basis"],
        )
        if proposal
        else None,
        alternatives=[
            Alternative(**_line_fields(a), id=a["id"], kind=a["kind"], saving=a["saving"])
            for a in result.get("alternatives", [])
        ],
        risk_if_not_ordered=result.get("risk_if_not_ordered"),
        count_requests=result.get("count_requests", []),
        opinion=Opinion(**review.opinion) if review.opinion else None,
        snapshot=SnapshotOut(
            id=snap.id, hash=snap.hash, values=snapshot_values(snap.values, request_qty)
        )
        if snap
        else None,
        computed_at=snap.computed_at.astimezone(KST) if snap else None,
        expires_at=review.expires_at.astimezone(KST) if review.expires_at else None,
        decision=review.decision,
        created_at=review.created_at.astimezone(KST),
    )
