"""weekly-merge 배치: 중복 등록 부품 후보 저장 (매주 월요일 03:30, F-MATCH-03).

이미 저장한 쌍은 상태와 관계없이 다시 만들지 않는다. 사람이 '다른 부품'으로 정한 쌍이 매주 다시
뜨지 않게 하기 위해서다. 한쪽이 병합돼 사라진 열린 후보는 closed로 닫는다.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session, aliased

from bjk_server.auth import set_tenant
from bjk_server.db.models import MergeCandidate, Part
from bjk_server.domain.merge import MergePart, find_duplicates
from bjk_server.jobs.runner import company_ids, job

OPEN_STATUSES = ("open", "count_requested")


@job("weekly-merge")
def run(session: Session, now: datetime) -> dict[str, Any]:
    created = closed = 0
    for company_id in company_ids(session):
        set_tenant(session, company_id)
        closed += close_stale(session, company_id)
        parts = session.scalars(
            select(Part).where(Part.company_id == company_id, Part.merged_into.is_(None))
        ).all()
        known = {
            (a, b)
            for a, b in session.execute(
                select(MergeCandidate.part_a_id, MergeCandidate.part_b_id).where(
                    MergeCandidate.company_id == company_id
                )
            )
        }
        for pair in find_duplicates(_merge_part(p) for p in parts):
            if (pair.part_a, pair.part_b) in known:
                continue
            session.add(
                MergeCandidate(
                    company_id=company_id,
                    part_a_id=pair.part_a,
                    part_b_id=pair.part_b,
                    score=pair.score,
                    reason=pair.reason,
                )
            )
            created += 1
        session.flush()
    return {"created": created, "closed": closed}


def close_stale(session: Session, company_id) -> int:
    """한쪽이 이미 병합된 열린 후보를 닫는다."""
    a, b = aliased(Part), aliased(Part)
    stale = (
        select(MergeCandidate.id)
        .join(a, a.id == MergeCandidate.part_a_id)
        .join(b, b.id == MergeCandidate.part_b_id)
        .where(
            MergeCandidate.company_id == company_id,
            MergeCandidate.status.in_(OPEN_STATUSES),
            or_(a.merged_into.is_not(None), b.merged_into.is_not(None)),
        )
    )
    return session.execute(
        update(MergeCandidate).where(MergeCandidate.id.in_(stale)).values(status="closed")
    ).rowcount


def _merge_part(part: Part) -> MergePart:
    embedding = None if part.embedding is None else [float(x) for x in part.embedding]
    return MergePart(
        part_id=part.id,
        category_id=part.category_id,
        name=part.name,
        spec=part.spec,
        embedding=embedding,
        embedding_model=part.embedding_model,
    )
