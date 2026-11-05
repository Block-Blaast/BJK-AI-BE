"""부품 엑셀 이관 (SET-01·02, F-SETUP-01·02).

SET-01은 파일을 읽어 줄마다 규격·카테고리 제안, 기존 부품, 중복 의심을 붙여 `part_imports`에 둔다.
규격·카테고리 제안은 ai `/v1/imports/suggest`가 하고, ai가 없거나 실패하면 규격은 정규식만 쓰고
카테고리는 비워 관리자가 직접 고르게 한다. 정규식이 찾은 규격 키는 정규식 값을 쓰고, 나머지 키만
ai 값을 쓴다. 둘이 다르면 그 줄 확신도를 낮춰 위로 올린다 (docs/ai-integration.md 4장).

SET-02는 관리자가 고친 값으로 부품을 만들거나 갱신한다. 기존 부품의 원장은 덮지 않는다.
"""

import hashlib
import uuid
from dataclasses import asdict
from typing import Any, Literal

from bjk_contracts import (
    IMPORT_MAX_ROWS,
    AiMeta,
    CategoryOption,
    FallbackReason,
    ImportRow,
    ImportSuggestRequest,
    RowSuggestion,
)
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from bjk_server import clock
from bjk_server.ai.client import AiClient, AiUnavailable
from bjk_server.ai.embeddings import embed_rows
from bjk_server.ai.usage import record_usage
from bjk_server.db.models import (
    Category,
    Movement,
    Part,
    PartAlias,
    PartImport,
    Supplier,
    SupplierPart,
)
from bjk_server.domain.matching import extract_spec, normalize, similarity
from bjk_server.errors import ApiError, ErrorCode
from bjk_server.events import publish_stock_changed
from bjk_server.imports.parse import ParsedRow, parse_parts_file
from bjk_server.inventory import lock_part_stock, stock_of
from bjk_server.security import TokenClaims

# 엑셀 이관·부품 등록 때 들어간 시작 재고의 원장 사유 (api/parts.py와 같은 값)
INITIAL_STOCK_REASON = "초기 재고"
REIMPORT_REASON = "엑셀 재이관"
# 정규식과 ai 규격이 다르면 확신도를 이만큼 곱한다
SPEC_CONFLICT_PENALTY = 0.5
# 중복 의심: 같은 규격, 또는 규격이 겹치지 않으면서 이름 자모 유사도가 이 값 이상
NAME_SIMILAR = 0.6
MAX_SUSPECTS = 3

StockMode = Literal["initial", "ignore", "preview", "apply"]


class SuggestedCategory(BaseModel):
    id: uuid.UUID
    name: str
    confidence: float


class DuplicateSuspect(BaseModel):
    part_id: uuid.UUID
    name: str
    reason: Literal["spec_exact", "name_similar"]


class ImportRowOut(BaseModel):
    row: int
    name: str
    stock: int | None
    unit: str
    spec: dict[str, str]
    suggested_category: SuggestedCategory | None
    existing_part_id: uuid.UUID | None
    duplicate_suspects: list[DuplicateSuspect]
    errors: list[str]
    # 막지는 않지만 반영하지 못하는 값 (예: 등록되지 않은 공급사 이름)
    warnings: list[str] = Field(default_factory=list)


class ImportOut(BaseModel):
    import_id: uuid.UUID
    is_reimport: bool
    rows: list[ImportRowOut]
    ai: AiMeta


class ConfirmRow(BaseModel):
    row: int
    category_id: uuid.UUID | None = None
    spec: dict[str, str] | None = None
    merge_with_part_id: uuid.UUID | None = None


class ConfirmRequest(BaseModel):
    rows: list[ConfirmRow] = Field(min_length=1)
    stock_mode: StockMode | None = None


class StockDiff(BaseModel):
    row: int
    part_id: uuid.UUID | None
    name: str
    ledger_stock: int
    file_stock: int
    diff: int


class ConfirmOut(BaseModel):
    created: int
    updated: int
    adjust_movements: int
    stock_diffs: list[StockDiff]


def _suggest(
    db: Session,
    ai: AiClient | None,
    company_id: uuid.UUID,
    categories: list[Category],
    rows: list[ParsedRow],
) -> tuple[dict[int, RowSuggestion] | None, AiMeta]:
    """ai 제안을 줄 번호별로. 하나의 묶음이라도 실패하면 전체를 대체 경로로 본다."""
    targets = [r for r in rows if r.name]
    if ai is None or not categories or not targets:
        return None, AiMeta(used=False, fallback=True, reason=FallbackReason.ERROR)
    options = [CategoryOption(id=str(c.id), name=c.name) for c in categories]
    suggestions: dict[int, RowSuggestion] = {}
    for start in range(0, len(targets), IMPORT_MAX_ROWS):
        batch = targets[start : start + IMPORT_MAX_ROWS]
        body = ImportSuggestRequest(
            company_id=company_id,
            categories=options,
            rows=[
                ImportRow(
                    row=r.row, name=r.name, spec_text=r.spec_text[:200] if r.spec_text else None
                )
                for r in batch
            ],
        )
        try:
            response = ai.suggest_import(body)
        except AiUnavailable as e:
            return None, AiMeta.failed(e.reason)
        record_usage(db, company_id, response.usage)
        if response.suggestions is None:
            return None, response.ai
        suggestions.update({s.row: s for s in response.suggestions})
    return suggestions, AiMeta.ok()


def _merge_spec(regex: dict[str, str], ai_spec: dict[str, str]) -> tuple[dict[str, str], bool]:
    conflict = any(k in ai_spec and ai_spec[k] != v for k, v in regex.items())
    return {**ai_spec, **regex}, conflict


def _spec_values(spec: dict[str, Any]) -> dict[str, str]:
    return {k: str(v).replace(" ", "").replace("-", "").upper() for k, v in spec.items()}


def _same_spec(a: dict[str, str], b: dict[str, Any]) -> bool:
    return bool(a) and a == _spec_values(b)


def build_import(
    db: Session, ai: AiClient | None, user: TokenClaims, file_name: str, content: bytes
) -> ImportOut:
    """SET-01. 파일을 읽고 제안 목록을 만들어 저장한다."""
    parsed = parse_parts_file(file_name, content)
    categories = list(db.scalars(select(Category).order_by(Category.name)))
    by_category = {str(c.id): c for c in categories}
    suggestions, meta = _suggest(db, ai, user.company_id, categories, parsed)
    parts = list(db.scalars(select(Part).where(Part.merged_into.is_(None))))
    suppliers = {s.name for s in db.scalars(select(Supplier))}
    is_reimport = (
        db.scalar(select(PartImport.id).where(PartImport.status == "confirmed").limit(1))
        is not None
    )

    out: list[ImportRowOut] = []
    stored: list[dict[str, Any]] = []
    for r in parsed:
        regex = extract_spec(f"{r.name} {r.spec_text or ''}")
        suggestion = suggestions.get(r.row) if suggestions else None
        spec, conflict = _merge_spec(regex, suggestion.spec if suggestion else {})
        category = None
        if suggestion and suggestion.category_id in by_category:
            confidence = suggestion.confidence * (SPEC_CONFLICT_PENALTY if conflict else 1)
            c = by_category[suggestion.category_id]
            category = SuggestedCategory(id=c.id, name=c.name, confidence=round(confidence, 2))
        key = normalize(r.name)
        # 재이관 기준: 부품명 + 규격 (F-SETUP-01)
        existing = next(
            (
                p
                for p in parts
                if normalize(p.name) == key
                and (_same_spec(spec, p.spec or {}) or not (spec or p.spec))
            ),
            None,
        )
        suspects: list[DuplicateSuspect] = []
        for p in parts:
            if p is existing or len(suspects) == MAX_SUSPECTS or not r.name:
                continue
            if _same_spec(spec, p.spec or {}):
                suspects.append(DuplicateSuspect(part_id=p.id, name=p.name, reason="spec_exact"))
            elif not (set(spec) & set(p.spec or {})) and similarity(r.name, p.name) >= NAME_SIMILAR:
                suspects.append(DuplicateSuspect(part_id=p.id, name=p.name, reason="name_similar"))
        warnings = ["supplier_unknown"] if r.supplier and r.supplier not in suppliers else []
        row = ImportRowOut(
            row=r.row,
            name=r.name,
            stock=r.stock,
            unit=r.unit,
            spec=spec,
            suggested_category=category,
            existing_part_id=existing.id if existing else None,
            duplicate_suspects=suspects,
            errors=r.errors,
            warnings=warnings,
        )
        out.append(row)
        stored.append({**row.model_dump(mode="json"), "source": asdict(r)})

    # 확신도 낮은 줄(제안 없음 포함)이 위로, 같으면 파일 순서
    def order(row: ImportRowOut) -> tuple[int, float, int]:
        confidence = row.suggested_category.confidence if row.suggested_category else 0.0
        return (0 if row.errors else 1, confidence, row.row)

    out.sort(key=order)
    record = PartImport(
        id=uuid.uuid4(),
        company_id=user.company_id,
        created_by=user.user_id,
        file_name=file_name[:200],
        file_sha256=hashlib.sha256(content).hexdigest(),
        is_reimport=is_reimport,
        rows=stored,
    )
    db.add(record)
    db.flush()
    return ImportOut(import_id=record.id, is_reimport=is_reimport, rows=out, ai=meta)


def _own_part(db: Session, part_id: uuid.UUID) -> Part:
    part = db.get(Part, part_id)
    if part is None or part.merged_into is not None:
        raise ApiError(
            ErrorCode.NOT_FOUND, "병합할 부품을 찾을 수 없습니다.", {"part_id": str(part_id)}
        )
    return part


def _adjust(db: Session, user: TokenClaims, part: Part, qty: int, reason: str, now) -> None:
    db.add(
        Movement(
            id=uuid.uuid4(),
            company_id=user.company_id,
            part_id=part.id,
            type="ADJUST",
            qty=qty,
            occurred_at=now,
            author_id=user.user_id,
            reason=reason,
        )
    )
    publish_stock_changed(db, user.company_id, part.id)


def confirm_import(
    db: Session, ai: AiClient | None, user: TokenClaims, import_id: uuid.UUID, body: ConfirmRequest
) -> ConfirmOut:
    """SET-02. 고른 줄만 반영한다.

    새 부품은 시작 재고를 ADJUST로 넣고, 기존 부품은 `stock_mode`대로 처리한다.

    - initial: 처음 이관 전용. 기존 부품의 재고는 건드리지 않는다.
    - ignore: 기존 부품은 정보만 갱신.
    - preview: 기존 부품의 원장 합계와 파일 재고 차이만 돌려준다(저장 안 함).
    - apply: preview 이후에만. 차이만 ADJUST(사유 `엑셀 재이관`)로 더한다.
    """
    record = db.scalar(select(PartImport).where(PartImport.id == import_id).with_for_update())
    if record is None:
        raise ApiError(ErrorCode.NOT_FOUND, "이관 기록을 찾을 수 없습니다.")
    if record.status == "confirmed":
        raise ApiError(ErrorCode.ALREADY_CONFIRMED, "이미 확정한 이관입니다.")
    mode: StockMode = body.stock_mode or ("ignore" if record.is_reimport else "initial")
    if mode == "initial" and record.is_reimport:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "재이관은 initial을 쓸 수 없습니다. ignore·preview·apply 중에서 고르세요.",
            {"stock_mode": mode},
        )
    if mode == "apply" and not record.stock_previewed:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "재고 차이를 먼저 확인해 주세요(preview).",
            {"stock_mode": mode},
        )

    by_row = {r["row"]: r for r in record.rows}
    seen: set[int] = set()
    for c in body.rows:
        stored = by_row.get(c.row)
        if stored is None or c.row in seen:
            raise ApiError(ErrorCode.VALIDATION_ERROR, "파일에 없는 줄입니다.", {"row": c.row})
        if stored["errors"]:
            raise ApiError(
                ErrorCode.VALIDATION_ERROR,
                "오류가 있는 줄은 확정할 수 없습니다.",
                {"row": c.row, "errors": stored["errors"]},
            )
        seen.add(c.row)
    category_ids = {c.id for c in db.scalars(select(Category))}
    for c in body.rows:
        if c.category_id is not None and c.category_id not in category_ids:
            raise ApiError(
                ErrorCode.VALIDATION_ERROR,
                "없는 카테고리입니다.",
                {"category_id": str(c.category_id)},
            )

    def target_of(c: ConfirmRow) -> Part | None:
        part_id = c.merge_with_part_id or by_row[c.row]["existing_part_id"]
        return _own_part(db, uuid.UUID(str(part_id))) if part_id else None

    if mode == "preview":
        diffs = []
        for c in body.rows:
            stored = by_row[c.row]
            target = target_of(c)
            ledger = stock_of(db, target.id) if target else 0
            diffs.append(
                StockDiff(
                    row=c.row,
                    part_id=target.id if target else None,
                    name=stored["name"],
                    ledger_stock=ledger,
                    file_stock=stored["stock"],
                    diff=stored["stock"] - ledger,
                )
            )
        record.stock_previewed = True
        return ConfirmOut(
            created=0, updated=0, adjust_movements=0, stock_diffs=[d for d in diffs if d.diff]
        )

    now = clock.utcnow()
    suppliers = {s.name: s for s in db.scalars(select(Supplier))}
    created: list[Part] = []
    updated = adjusts = 0
    diffs: list[StockDiff] = []
    for c in body.rows:
        stored = by_row[c.row]
        source = stored["source"]
        spec = _spec_values(c.spec) if c.spec is not None else stored["spec"]
        category_id = c.category_id or (
            uuid.UUID(stored["suggested_category"]["id"]) if stored["suggested_category"] else None
        )
        supplier = suppliers.get(source["supplier"]) if source["supplier"] else None
        fields: dict[str, Any] = {"unit": source["unit"], "spec": spec, "updated_at": now}
        if category_id:
            fields["category_id"] = category_id
        if supplier:
            fields["default_supplier_id"] = supplier.id
        if source["monthly_estimate"] is not None:
            fields["monthly_estimate"] = source["monthly_estimate"]
        if source["location"]:
            fields["location"] = source["location"]

        target = target_of(c)
        if target is None:
            part = Part(id=uuid.uuid4(), company_id=user.company_id, name=source["name"], **fields)
            db.add(part)
            db.flush()
            created.append(part)
            # 새 부품은 원장이 없으므로 어느 모드든 파일 재고가 시작 재고다
            if source["stock"]:
                _adjust(db, user, part, source["stock"], INITIAL_STOCK_REASON, now)
                adjusts += 1
        else:
            part = target
            for key, value in fields.items():
                setattr(part, key, value)
            updated += 1
            if c.merge_with_part_id and normalize(source["name"]) != normalize(part.name):
                exists = db.scalar(
                    select(PartAlias.id).where(
                        PartAlias.part_id == part.id, PartAlias.text == source["name"][:100]
                    )
                )
                if exists is None:
                    db.add(
                        PartAlias(
                            id=uuid.uuid4(),
                            company_id=user.company_id,
                            part_id=part.id,
                            text=source["name"][:100],
                        )
                    )
            if mode == "apply":
                if not lock_part_stock(db, user.company_id, part.id):
                    raise ApiError(ErrorCode.NOT_FOUND, "부품을 찾을 수 없습니다.")
                ledger = stock_of(db, part.id)
                diff = source["stock"] - ledger
                if diff:
                    _adjust(db, user, part, diff, REIMPORT_REASON, now)
                    adjusts += 1
                    diffs.append(
                        StockDiff(
                            row=c.row,
                            part_id=part.id,
                            name=part.name,
                            ledger_stock=ledger,
                            file_stock=source["stock"],
                            diff=diff,
                        )
                    )
        if supplier and source["unit_price"] is not None:
            link = db.scalar(
                select(SupplierPart).where(
                    SupplierPart.supplier_id == supplier.id, SupplierPart.part_id == part.id
                )
            )
            if link is None:
                db.add(
                    SupplierPart(
                        id=uuid.uuid4(),
                        company_id=user.company_id,
                        supplier_id=supplier.id,
                        part_id=part.id,
                        unit_price=source["unit_price"],
                    )
                )
            else:
                link.unit_price = source["unit_price"]
    db.flush()
    record.status, record.confirmed_at = "confirmed", now
    if ai and created:
        embed_rows(db, ai, user.company_id, created)
    return ConfirmOut(
        created=len(created), updated=updated, adjust_movements=adjusts, stock_diffs=diffs
    )
