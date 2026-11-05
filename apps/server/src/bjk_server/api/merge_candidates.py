"""중복 등록 부품 후보·병합 API (API 명세서 MAT-01·02, 기능명세서 F-MATCH-03)."""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, aliased

from bjk_server import clock
from bjk_server.auth import TenantDB, require_role
from bjk_server.clock import KST
from bjk_server.db.models import CountRequest, MergeCandidate, Part, PartAlias
from bjk_server.errors import ApiError, ErrorCode
from bjk_server.inventory import stock_of
from bjk_server.pagination import Page, PageParams, keyset_page, page_params
from bjk_server.security import TokenClaims

router = APIRouter(prefix="/merge-candidates", tags=["merge-candidates"])

Manager = Annotated[TokenClaims, Depends(require_role("manager"))]
CandidateStatus = Literal["open", "count_requested", "merged", "different", "closed"]
DECIDABLE = ("open", "count_requested")


class CandidatePart(BaseModel):
    id: uuid.UUID
    name: str
    stock: int
    last_counted_at: date | None


class MergeCandidateItem(BaseModel):
    id: uuid.UUID
    score: float
    reason: str
    status: CandidateStatus
    part_a: CandidatePart
    part_b: CandidatePart
    representative_part_id: uuid.UUID | None
    created_at: datetime


def _part_out(db: Session, part: Part) -> CandidatePart:
    counted = db.scalar(
        select(func.max(CountRequest.answered_at)).where(CountRequest.part_id == part.id)
    )
    return CandidatePart(
        id=part.id,
        name=part.name,
        stock=stock_of(db, part.id),
        last_counted_at=counted.astimezone(KST).date() if counted else None,
    )


def _item(db: Session, c: MergeCandidate) -> MergeCandidateItem:
    return MergeCandidateItem(
        id=c.id,
        score=c.score,
        reason=c.reason,
        status=c.status,
        part_a=_part_out(db, db.get(Part, c.part_a_id)),
        part_b=_part_out(db, db.get(Part, c.part_b_id)),
        representative_part_id=c.representative_part_id,
        created_at=c.created_at,
    )


@router.get("", response_model=Page[MergeCandidateItem])
def list_merge_candidates(
    _: Manager,
    db: TenantDB,
    params: Annotated[PageParams, Depends(page_params)],
    status: CandidateStatus | None = None,
) -> Page[MergeCandidateItem]:
    """MAT-01. 중복 등록 후보(W-07). 기본은 결정 대기(open·count_requested), 점수 높은 순."""
    stmt = select(MergeCandidate)
    if status:
        stmt = stmt.where(MergeCandidate.status == status)
    else:
        stmt = stmt.where(MergeCandidate.status.in_(DECIDABLE))
    return keyset_page(
        db,
        stmt,
        [MergeCandidate.score, MergeCandidate.id],
        params,
        to_item=lambda r: _item(db, r.MergeCandidate),
        cursor_of=lambda r: [r.MergeCandidate.score, r.MergeCandidate.id],
        descending=True,
    )


class DecisionRequest(BaseModel):
    action: Literal["merge", "different", "request_count"]
    representative_part_id: uuid.UUID | None = None


@router.post("/{candidate_id}/decision", response_model=MergeCandidateItem)
def decide_merge_candidate(
    candidate_id: uuid.UUID, body: DecisionRequest, user: Manager, db: TenantDB
) -> MergeCandidateItem:
    """MAT-02. 병합 / 다른 부품 / 실사 요청 후 결정.

    병합하면 대표가 아닌 부품에 merged_into를 정하고 별칭을 대표 부품으로 옮긴다. 원장은 고치지
    않고 재고 계산 때 합산한다(F-LEDGER-02).
    """
    now = clock.utcnow()
    c = db.scalar(select(MergeCandidate).where(MergeCandidate.id == candidate_id).with_for_update())
    if c is None:
        raise ApiError(ErrorCode.NOT_FOUND, "병합 후보를 찾을 수 없습니다.")
    if c.status not in DECIDABLE:
        raise ApiError(
            ErrorCode.ALREADY_CONFIRMED, "이미 결정한 병합 후보입니다.", {"status": c.status}
        )
    if body.action == "merge":
        _merge(db, c, body.representative_part_id)
        c.representative_part_id = body.representative_part_id
        c.status = "merged"
    else:
        c.status = "different" if body.action == "different" else "count_requested"
    if c.status != "count_requested":
        c.decided_by, c.decided_at = user.user_id, now
    db.flush()
    return _item(db, c)


def _merge(db: Session, c: MergeCandidate, representative_id: uuid.UUID | None) -> None:
    pair = (c.part_a_id, c.part_b_id)
    if representative_id not in pair:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "대표 부품은 후보 두 부품 중 하나여야 합니다.",
            {"field": "representative_part_id"},
        )
    absorbed_id = pair[1] if representative_id == pair[0] else pair[0]
    parts = db.scalars(select(Part).where(Part.id.in_(pair)).with_for_update()).all()
    if any(p.merged_into is not None for p in parts):
        raise ApiError(ErrorCode.ALREADY_CONFIRMED, "이미 병합된 부품입니다.", {"status": "merged"})
    # 흡수되는 부품에 먼저 병합된 부품도 대표로 바로 연결해 병합 사슬을 만들지 않는다.
    db.execute(
        update(Part)
        .where(or_(Part.id == absorbed_id, Part.merged_into == absorbed_id))
        .values(merged_into=representative_id)
    )
    _move_aliases(db, absorbed_id, representative_id)
    # 사라진 부품이 들어간 다른 열린 후보는 더 볼 필요가 없다.
    other = aliased(MergeCandidate)
    db.execute(
        update(other)
        .where(
            other.id != c.id,
            other.status.in_(DECIDABLE),
            or_(other.part_a_id == absorbed_id, other.part_b_id == absorbed_id),
        )
        .values(status="closed")
    )


def _move_aliases(db: Session, from_id: uuid.UUID, to_id: uuid.UUID) -> None:
    """별칭을 대표 부품으로 옮긴다. 대표 부품에 같은 호칭이 있으면 확정 횟수를 더하고 합친다."""
    existing = {a.text: a for a in db.scalars(select(PartAlias).where(PartAlias.part_id == to_id))}
    for alias in db.scalars(select(PartAlias).where(PartAlias.part_id == from_id)).all():
        kept = existing.get(alias.text)
        if kept is None:
            alias.part_id = to_id
            continue
        kept.confirmed_count += alias.confirmed_count
        kept.ambiguous = kept.ambiguous or alias.ambiguous
        db.delete(alias)
