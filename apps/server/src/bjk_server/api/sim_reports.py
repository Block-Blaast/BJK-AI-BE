"""검증 리포트 목록 (기능명세서 F-SIM-03·04, 화면 W-09).

Notion API 명세서에 없어 사용자 결정(2026-11-05, #260)으로 이 레포에서 정했다. 응답 원소는 프론트가
쓰던 형식(`id`, `title`, `created_at`, `pdf_url`)에 `source`를 더했다. 검증 하네스가 아직 없어
시연 시드의 더미 행(`source: sample`)만 있고, PDF가 없어 `pdf_url`은 항상 null이다.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from bjk_server.auth import TenantDB, require_role
from bjk_server.db.models import SimReport
from bjk_server.pagination import Page, PageParams, keyset_page, page_params
from bjk_server.security import TokenClaims

router = APIRouter(prefix="/sim-reports", tags=["sim-reports"])

Manager = Annotated[TokenClaims, Depends(require_role("manager"))]


class SimReportItem(BaseModel):
    id: uuid.UUID
    title: str
    source: Literal["sample", "harness"]
    created_at: datetime
    pdf_url: str | None


@router.get("", response_model=Page[SimReportItem])
def list_sim_reports(
    _: Manager, db: TenantDB, params: Annotated[PageParams, Depends(page_params)]
) -> Page[SimReportItem]:
    """검증 리포트 목록. 최신 순 커서 목록."""
    return keyset_page(
        db,
        select(SimReport),
        [SimReport.created_at, SimReport.id],
        params,
        to_item=lambda r: SimReportItem(
            id=r.SimReport.id,
            title=r.SimReport.title,
            source=r.SimReport.source,
            created_at=r.SimReport.created_at,
            pdf_url=None,
        ),
        cursor_of=lambda r: [r.SimReport.created_at, r.SimReport.id],
        descending=True,
    )
