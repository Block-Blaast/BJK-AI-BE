"""장부 검증·실사 API (API 명세서 3-7 AUD)."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import case, select

from bjk_server import clock
from bjk_server.audit.counts import request_count
from bjk_server.auth import TenantDB, require_role
from bjk_server.db.models import AuditFlag, Part
from bjk_server.domain.audit import Level, Rule
from bjk_server.pagination import Page, PageParams, keyset_page, page_params
from bjk_server.security import TokenClaims

router = APIRouter(tags=["audit"])

Manager = Annotated[TokenClaims, Depends(require_role("manager"))]
FlagStatus = Literal["open", "count_requested", "closed"]


class PartRef(BaseModel):
    id: uuid.UUID
    name: str


class RelatedRule(BaseModel):
    rule: Rule
    level: Level
    evidence: dict[str, Any]


class AuditFlagItem(BaseModel):
    id: uuid.UUID
    part: PartRef
    rule: Rule
    level: Level
    status: FlagStatus
    evidence: dict[str, Any]
    # 같은 부품에 함께 걸린 다른 규칙. 열린 항목은 부품당 하나다.
    related: list[RelatedRule]
    created_at: datetime
    updated_at: datetime


_level_rank = case((AuditFlag.level == "high", 3), (AuditFlag.level == "medium", 2), else_=1)


@router.get("/audit-flags", response_model=Page[AuditFlagItem])
def list_audit_flags(
    _: Manager,
    db: TenantDB,
    params: Annotated[PageParams, Depends(page_params)],
    status: FlagStatus | None = None,
    level: Level | None = None,
    rule: Rule | None = None,
) -> Page[AuditFlagItem]:
    """AUD-01. 의심 항목. 등급 높은 순, 같은 등급은 최근 것부터."""
    rank = _level_rank.label("rank")
    stmt = select(AuditFlag, Part.name.label("part_name"), rank).join(
        Part, Part.id == AuditFlag.part_id
    )
    if status:
        stmt = stmt.where(AuditFlag.status == status)
    if level:
        stmt = stmt.where(AuditFlag.level == level)
    if rule:
        stmt = stmt.where(AuditFlag.rule == rule)
    return keyset_page(
        db,
        stmt,
        [_level_rank, AuditFlag.created_at, AuditFlag.id],
        params,
        to_item=lambda r: AuditFlagItem(
            id=r.AuditFlag.id,
            part=PartRef(id=r.AuditFlag.part_id, name=r.part_name),
            rule=r.AuditFlag.rule,
            level=r.AuditFlag.level,
            status=r.AuditFlag.status,
            evidence=r.AuditFlag.evidence,
            related=r.AuditFlag.related,
            created_at=r.AuditFlag.created_at,
            updated_at=r.AuditFlag.updated_at,
        ),
        cursor_of=lambda r: [r.rank, r.AuditFlag.created_at, r.AuditFlag.id],
        descending=True,
    )


class CountRequestCreate(BaseModel):
    assignee_id: uuid.UUID


class CountRequestCreated(BaseModel):
    count_request_id: uuid.UUID
    status: Literal["sent", "scheduled"]
    scheduled_for: datetime | None
    message_preview: str


@router.post(
    "/audit-flags/{flag_id}/count-request", status_code=201, response_model=CountRequestCreated
)
def create_count_request(
    flag_id: uuid.UUID, body: CountRequestCreate, user: Manager, db: TenantDB
) -> CountRequestCreated:
    """AUD-02. 블라인드 실사 요청. 문구에 장부 수량을 넣지 않는다."""
    request = request_count(db, user, flag_id, body.assignee_id, clock.utcnow())
    return CountRequestCreated(
        count_request_id=request.id,
        status=request.status,
        scheduled_for=request.scheduled_for,
        message_preview=request.message,
    )
