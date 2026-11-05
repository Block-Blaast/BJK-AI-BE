"""부품 엑셀 이관 API (API 명세서 3-2 SET-01·02)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, UploadFile

from bjk_server.ai.client import AiClient, get_ai_client
from bjk_server.auth import TenantDB, require_role
from bjk_server.errors import ApiError, ErrorCode
from bjk_server.imports.parse import MAX_FILE_BYTES
from bjk_server.imports.service import (
    ConfirmOut,
    ConfirmRequest,
    ImportOut,
    build_import,
    confirm_import,
)
from bjk_server.security import TokenClaims

router = APIRouter(prefix="/imports", tags=["imports"])

Manager = Annotated[TokenClaims, Depends(require_role("manager"))]
Ai = Annotated[AiClient | None, Depends(get_ai_client)]


@router.post("/parts", response_model=ImportOut)
def upload_parts(file: UploadFile, user: Manager, db: TenantDB, ai: Ai) -> ImportOut:
    """SET-01. 부품 엑셀(xlsx, csv) → 규격·카테고리 제안 목록. ai가 실패해도 200으로 대체 응답."""
    content = file.file.read(MAX_FILE_BYTES + 1)
    if len(content) > MAX_FILE_BYTES:
        raise ApiError(ErrorCode.VALIDATION_ERROR, "파일은 5MB 이하여야 합니다.")
    return build_import(db, ai, user, file.filename or "", content)


@router.post("/parts/{import_id}/confirm", response_model=ConfirmOut)
def confirm_parts(
    import_id: uuid.UUID, body: ConfirmRequest, user: Manager, db: TenantDB, ai: Ai
) -> ConfirmOut:
    """SET-02. 제안 확정. 재이관이면 stock_mode로 재고를 무시·미리 보기·차이 반영 중에서 고른다."""
    return confirm_import(db, ai, user, import_id, body)
