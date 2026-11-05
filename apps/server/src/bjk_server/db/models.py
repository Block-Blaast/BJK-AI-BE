"""MVP 기본 테이블. 회사 소유 테이블은 모두 company_id를 가진다."""

import uuid
from datetime import date, datetime
from typing import Any

from bjk_contracts import EMBEDDING_DIM
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# 임베딩 차원은 ai 계약(bjk_contracts.EMBEDDING_DIM, 1024)을 따른다. 마이그레이션 0019.
# 모델이 다른 벡터끼리는 비교할 수 없어 벡터와 모델명을 함께 둔다.
EMBEDDING_PAIR = "(embedding IS NULL) = (embedding_model IS NULL)"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map = {dict[str, Any]: JSONB, uuid.UUID: UUID(as_uuid=True)}


def _id() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, server_default=sql_text("gen_random_uuid()"))


def _company_id() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = _id()
    name: Mapped[str] = mapped_column(String(100))
    code: Mapped[str] = mapped_column(String(16), unique=True)
    created_at: Mapped[datetime] = _created_at()


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('worker', 'manager', 'owner')", name="role"),)

    id: Mapped[uuid.UUID] = _id()
    company_id: Mapped[uuid.UUID] = _company_id()
    name: Mapped[str] = mapped_column(String(50))
    role: Mapped[str] = mapped_column(String(16))
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text)
    pin_hash: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("true"))
    created_at: Mapped[datetime] = _created_at()


class Invite(Base):
    """직원 초대 (API 명세서 AUTH-06·07). 일회용, 72시간. 토큰은 해시만 저장한다."""

    __tablename__ = "invites"
    __table_args__ = (
        CheckConstraint("role IN ('worker', 'manager')", name="role"),
        CheckConstraint("(used_at IS NULL) = (used_by IS NULL)", name="used_pair"),
    )

    id: Mapped[uuid.UUID] = _id()
    company_id: Mapped[uuid.UUID] = _company_id()
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    role: Mapped[str] = mapped_column(String(16))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created_at()


class CompanySettings(Base):
    __tablename__ = "company_settings"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True
    )
    notify: Mapped[dict[str, Any]]
    review: Mapped[dict[str, Any]]
    system: Mapped[dict[str, Any]]
    # 개발·시연 시나리오 스위치 (DEV-02 외부 충격 등). 운영에서는 비어 있다.
    scenarios: Mapped[dict[str, Any]] = mapped_column(server_default=sql_text("'{}'::jsonb"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("company_id", "name"),
        CheckConstraint("import_dependency IN ('high', 'medium', 'low')", name="import_dependency"),
    )

    id: Mapped[uuid.UUID] = _id()
    company_id: Mapped[uuid.UUID] = _company_id()
    name: Mapped[str] = mapped_column(String(50))
    import_dependency: Mapped[str] = mapped_column(String(8), server_default="low")
    lead_factors: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    price_factors: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    hs_code: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = _created_at()


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[uuid.UUID] = _id()
    company_id: Mapped[uuid.UUID] = _company_id()
    name: Mapped[str] = mapped_column(String(100))
    contact: Mapped[str | None] = mapped_column(String(100))
    default_lead_time_days: Mapped[int | None] = mapped_column(Integer)
    holidays: Mapped[list[date]] = mapped_column(ARRAY(Date), server_default="{}")
    created_at: Mapped[datetime] = _created_at()


class Part(Base):
    __tablename__ = "parts"
    __table_args__ = (
        CheckConstraint(
            "import_override IS NULL OR import_override IN ('high', 'medium', 'low')",
            name="import_override",
        ),
        CheckConstraint(EMBEDDING_PAIR, name="embedding_model"),
    )

    id: Mapped[uuid.UUID] = _id()
    company_id: Mapped[uuid.UUID] = _company_id()
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("categories.id"))
    default_supplier_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("suppliers.id"))
    name: Mapped[str] = mapped_column(String(200))
    spec: Mapped[dict[str, Any]] = mapped_column(server_default=sql_text("'{}'::jsonb"))
    unit: Mapped[str] = mapped_column(String(16))
    pack_qty: Mapped[int | None] = mapped_column(Integer)
    monthly_estimate: Mapped[int | None] = mapped_column(Integer)
    import_override: Mapped[str | None] = mapped_column(String(8))
    location: Mapped[str | None] = mapped_column(String(100))
    merged_into: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parts.id"))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    embedding_model: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PartAlias(Base):
    __tablename__ = "part_aliases"
    __table_args__ = (
        UniqueConstraint("company_id", "text", "part_id"),
        CheckConstraint(EMBEDDING_PAIR, name="embedding_model"),
    )

    id: Mapped[uuid.UUID] = _id()
    company_id: Mapped[uuid.UUID] = _company_id()
    part_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parts.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(String(100))
    confirmed_count: Mapped[int] = mapped_column(Integer, server_default="0")
    ambiguous: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("false"))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    embedding_model: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = _created_at()


class SupplierPart(Base):
    __tablename__ = "supplier_parts"
    __table_args__ = (UniqueConstraint("supplier_id", "part_id"),)

    id: Mapped[uuid.UUID] = _id()
    company_id: Mapped[uuid.UUID] = _company_id()
    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("suppliers.id", ondelete="CASCADE"))
    part_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parts.id", ondelete="CASCADE"))
    unit_price: Mapped[int] = mapped_column(Integer)
    moq: Mapped[int] = mapped_column(Integer, server_default="1")
    price_tiers: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=sql_text("'[]'::jsonb")
    )
    shipping_fee: Mapped[int] = mapped_column(Integer, server_default="0")


class Equipment(Base):
    __tablename__ = "equipment"

    id: Mapped[uuid.UUID] = _id()
    company_id: Mapped[uuid.UUID] = _company_id()
    name: Mapped[str] = mapped_column(String(100))
    loss_per_hour: Mapped[int] = mapped_column(Integer, server_default="0")
    loss_is_estimate: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("true"))
    operating_hours: Mapped[int] = mapped_column(Integer, server_default="8")
    created_at: Mapped[datetime] = _created_at()


class EquipmentPart(Base):
    __tablename__ = "equipment_parts"
    __table_args__ = (UniqueConstraint("equipment_id", "part_id"),)

    id: Mapped[uuid.UUID] = _id()
    company_id: Mapped[uuid.UUID] = _company_id()
    equipment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("equipment.id", ondelete="CASCADE"))
    part_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parts.id", ondelete="CASCADE"))
    qty_per_maintenance: Mapped[int] = mapped_column(Integer)


class Maintenance(Base):
    __tablename__ = "maintenance"

    id: Mapped[uuid.UUID] = _id()
    company_id: Mapped[uuid.UUID] = _company_id()
    equipment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("equipment.id", ondelete="CASCADE"))
    scheduled_date: Mapped[date] = mapped_column(Date)
    # [{"part_id": ..., "qty": ...}]. 비어 있으면 설비의 qty_per_maintenance를 쓴다.
    required_parts: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created_at()


class CalendarEvent(Base):
    """연휴 캘린더 (F-EXT-01). 납기 구간과 겹치면 겹친 일수만큼 납기를 늘린다."""

    __tablename__ = "calendar_events"
    __table_args__ = (
        CheckConstraint("scope IN ('KR', 'CN', 'supplier')", name="scope"),
        CheckConstraint("end_date >= start_date", name="date_order"),
        CheckConstraint("(scope = 'supplier') = (supplier_id IS NOT NULL)", name="supplier_scope"),
        Index("ix_calendar_events_company_start", "company_id", "start_date"),
    )

    id: Mapped[uuid.UUID] = _id()
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    # KR: 국내 명절, CN: 중국(춘절 등), supplier: 특정 공급사 휴무
    scope: Mapped[str] = mapped_column(String(16))
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("suppliers.id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = _created_at()


class Movement(Base):
    """원장 이벤트. 추가만 하고 수정·삭제하지 않는다(DB 트리거로 차단)."""

    __tablename__ = "movements"
    __table_args__ = (
        CheckConstraint("type IN ('IN', 'OUT', 'ADJUST')", name="type"),
        CheckConstraint(
            "(type = 'IN' AND qty > 0) OR (type = 'OUT' AND qty < 0) "
            "OR (type = 'ADJUST' AND qty <> 0)",
            name="qty_sign",
        ),
        Index("ix_movements_company_part_occurred", "company_id", "part_id", "occurred_at"),
        # 재고 합산(part_id별 SUM(qty))을 인덱스만 읽고 끝내기 위한 인덱스
        Index("ix_movements_company_part_qty", "company_id", "part_id", postgresql_include=["qty"]),
    )

    id: Mapped[uuid.UUID] = _id()
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    part_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parts.id"))
    type: Mapped[str] = mapped_column(String(8))
    qty: Mapped[int] = mapped_column(Integer)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    source_text: Mapped[str | None] = mapped_column(Text)
    equipment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("equipment.id"))
    maintenance_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("maintenance.id"))
    # 채팅으로 기록한 경우 원본 메시지. 폼 입력·실사조정 등은 null.
    message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chat_messages.id"))
    # 발주 테이블은 발주 Issue에서 추가하고 외래 키를 건다.
    po_id: Mapped[uuid.UUID | None]
    reason: Mapped[str | None] = mapped_column(Text)
    corrects_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("movements.id"))
    created_at: Mapped[datetime] = _created_at()


class IdempotencyKey(Base):
    """멱등 처리 기록 (API 명세서 1-4). 같은 키의 재요청에는 저장한 응답을 돌려준다."""

    __tablename__ = "idempotency_keys"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True
    )
    scope: Mapped[str] = mapped_column(String(32), primary_key=True)
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    status_code: Mapped[int | None] = mapped_column(Integer)
    response: Mapped[dict[str, Any] | None]
    created_at: Mapped[datetime] = _created_at()


class PinAttempt(Base):
    """PIN 연속 실패 기록 (API 명세서 1-5). 5회 실패 시 10분 잠금."""

    __tablename__ = "pin_attempts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    company_id: Mapped[uuid.UUID] = _company_id()
    failed_count: Mapped[int] = mapped_column(Integer, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RateLimit(Base):
    """고정 창 호출 제한 카운터. 회사 구분 전(로그인 화면) 요청에도 쓰므로 RLS를 걸지 않는다."""

    __tablename__ = "rate_limits"

    bucket: Mapped[str] = mapped_column(String(200), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, server_default="0")


class ChatMessage(Base):
    """채팅 메시지와 서버 답변 (API 명세서 CHAT-01)."""

    __tablename__ = "chat_messages"
    __table_args__ = (
        UniqueConstraint("company_id", "client_message_id"),
        Index("ix_chat_messages_company_user_created", "company_id", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _id()
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    client_message_id: Mapped[str] = mapped_column(String(128))
    text: Mapped[str] = mapped_column(Text)
    intent: Mapped[str] = mapped_column(String(32))
    reply: Mapped[str] = mapped_column(Text)
    ai: Mapped[dict[str, Any]]
    created_at: Mapped[datetime] = _created_at()


class ChatEntry(Base):
    """확인 카드 하나. 확정되면 의도에 맞는 기록(원장 등)을 만든다."""

    __tablename__ = "chat_entries"
    __table_args__ = (
        CheckConstraint(
            "type IN ('confirm', 'select', 'warning', 'unregistered', 'form')", name="type"
        ),
        CheckConstraint("status IN ('open', 'confirmed', 'cancelled')", name="status"),
    )

    id: Mapped[uuid.UUID] = _id()
    company_id: Mapped[uuid.UUID] = _company_id()
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    type: Mapped[str] = mapped_column(String(16))
    intent: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), server_default="open")
    # 카드 내용 (part_text, qty, equipment, candidates, part_id ...)
    payload: Mapped[dict[str, Any]]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict[str, Any] | None]
    created_at: Mapped[datetime] = _created_at()


class JobRun(Base):
    """배치 실행 기록 (API 명세서 14장). 회사 단위가 아닌 시스템 기록이라 RLS를 걸지 않는다."""

    __tablename__ = "job_runs"
    __table_args__ = (
        CheckConstraint("status IN ('ok', 'error', 'skipped')", name="status"),
        CheckConstraint("trigger IN ('schedule', 'manual')", name="trigger"),
        Index("ix_job_runs_name_started", "name", "started_at"),
    )

    id: Mapped[uuid.UUID] = _id()
    name: Mapped[str] = mapped_column(String(32))
    trigger: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    summary: Mapped[dict[str, Any]] = mapped_column(server_default=sql_text("'{}'::jsonb"))
    error: Mapped[str | None] = mapped_column(Text)


class ExternalIndicator(Base):
    """외부 지표 값과 위험도 (F-EXT). 회사 공통 데이터라 RLS를 걸지 않는다."""

    __tablename__ = "external_indicators"
    __table_args__ = (
        UniqueConstraint("code", "as_of"),
        CheckConstraint("series IN ('lead', 'price')", name="series"),
    )

    id: Mapped[uuid.UUID] = _id()
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(100))
    series: Mapped[str] = mapped_column(String(8))
    as_of: Mapped[date] = mapped_column(Date)
    value: Mapped[float] = mapped_column(Float)
    # 위험도는 해당 날짜까지의 값으로 계산한다.
    z: Mapped[float | None] = mapped_column(Float)
    r: Mapped[float] = mapped_column(Float, server_default="0")
    level: Mapped[str] = mapped_column(String(8), server_default="normal")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PartMetrics(Base):
    """부품별 근거 지표의 날짜별 스냅샷 (F-ANAL). 화면과 검토는 최신 것만 읽는다."""

    __tablename__ = "part_metrics"
    __table_args__ = (
        UniqueConstraint("part_id", "computed_on"),
        Index("ix_part_metrics_company_computed_on", "company_id", "computed_on"),
    )

    id: Mapped[uuid.UUID] = _id()
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    part_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parts.id", ondelete="CASCADE"))
    computed_on: Mapped[date] = mapped_column(Date)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    abc: Mapped[str] = mapped_column(String(1))
    abc_basis: Mapped[str] = mapped_column(String(8))  # amount: 사용 금액, qty: 단가 미입력
    demand_class: Mapped[str] = mapped_column(String(16))
    data_mode: Mapped[str] = mapped_column(String(16))  # statistical, estimated
    forecast_weekly: Mapped[float] = mapped_column(Float)
    m: Mapped[float] = mapped_column(Float)
    f_items: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    default_supplier_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("suppliers.id"))
    lt50: Mapped[int] = mapped_column(Integer)
    lt90: Mapped[int] = mapped_column(Integer)
    period_days: Mapped[int] = mapped_column(Integer)
    d95: Mapped[int] = mapped_column(Integer)
    d99: Mapped[int] = mapped_column(Integer)
    reorder_point: Mapped[int] = mapped_column(Integer)
    stock: Mapped[int] = mapped_column(Integer)
    hidden_confirmed: Mapped[int] = mapped_column(Integer)
    hidden_unconfirmed: Mapped[int] = mapped_column(Integer)
    t_out: Mapped[date | None] = mapped_column(Date)
    t_deadline: Mapped[date | None] = mapped_column(Date)
    p_out: Mapped[float] = mapped_column(Float)
    loss: Mapped[int] = mapped_column(Integer)
    loss_equipment: Mapped[list[str]] = mapped_column(ARRAY(Text))
    loss_is_estimate: Mapped[bool] = mapped_column(Boolean)
    priority: Mapped[float] = mapped_column(Float)
    recommended_qty: Mapped[int] = mapped_column(Integer)
    r_lead: Mapped[float] = mapped_column(Float)
    r_price: Mapped[float] = mapped_column(Float)
    external_level: Mapped[str] = mapped_column(String(8))


class AuditFlag(Base):
    """장부 의심 항목 (F-AUDIT). 같은 부품의 열린 항목은 하나로 묶는다."""

    __tablename__ = "audit_flags"
    __table_args__ = (
        CheckConstraint(
            "rule IN ('NEGATIVE_STOCK', 'MAINTENANCE_OUT_MISMATCH', 'PATTERN_DEVIATION', "
            "'SPIKE', 'COUNT_OVERDUE')",
            name="rule",
        ),
        CheckConstraint("level IN ('high', 'medium', 'low')", name="level"),
        CheckConstraint("status IN ('open', 'count_requested', 'closed')", name="status"),
        Index(
            "uq_audit_flags_open_part",
            "company_id",
            "part_id",
            unique=True,
            postgresql_where=sql_text("status <> 'closed'"),
        ),
        Index("ix_audit_flags_company_created", "company_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _id()
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    part_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parts.id", ondelete="CASCADE"))
    # 대표 규칙(등급이 가장 높은 것)과 근거. 함께 걸린 규칙은 related에 둔다.
    rule: Mapped[str] = mapped_column(String(32))
    level: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16), server_default="open")
    evidence: Mapped[dict[str, Any]]
    # [{"rule": ..., "level": ..., "evidence": {...}}]
    related: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=sql_text("'[]'::jsonb")
    )
    # 이 항목에 담긴 규칙의 중복 판단 키 (bjk_server.domain.audit.Hit.key)
    keys: Mapped[list[str]] = mapped_column(ARRAY(Text))
    # 종료 사유. 실사 기능에서 채운다.
    resolution: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CountRequest(Base):
    """블라인드 실사 요청 (F-AUDIT-06). 담당자에게 장부 수량을 보여주지 않는다."""

    __tablename__ = "count_requests"
    __table_args__ = (
        CheckConstraint("status IN ('scheduled', 'sent', 'answered', 'closed')", name="status"),
        CheckConstraint(
            "reason IS NULL OR reason IN ('lost', 'missing_record', 'damaged', 'other')",
            name="reason",
        ),
        Index("ix_count_requests_company_assignee", "company_id", "assignee_id"),
    )

    id: Mapped[uuid.UUID] = _id()
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    audit_flag_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("audit_flags.id", ondelete="CASCADE"), index=True
    )
    part_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parts.id", ondelete="CASCADE"))
    assignee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    # scheduled: 하루 한도를 넘어 scheduled_for에 보냄, sent: 응답 대기,
    # answered: 차이가 있어 사유 대기, closed: 종료
    status: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(Text)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    counted_qty: Mapped[int | None] = mapped_column(Integer)
    book_qty_before: Mapped[int | None] = mapped_column(Integer)
    diff: Mapped[int | None] = mapped_column(Integer)
    adjust_movement_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("movements.id"))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(String(16))
    note: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()


class PartSupplierMetrics(Base):
    """부품×공급사별 납기 (F-ANAL-04, 외부 요인·휴무일 반영 후)."""

    __tablename__ = "part_supplier_metrics"
    __table_args__ = (UniqueConstraint("part_id", "supplier_id", "computed_on"),)

    id: Mapped[uuid.UUID] = _id()
    company_id: Mapped[uuid.UUID] = _company_id()
    part_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parts.id", ondelete="CASCADE"))
    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("suppliers.id", ondelete="CASCADE"))
    computed_on: Mapped[date] = mapped_column(Date)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lt50: Mapped[int] = mapped_column(Integer)
    lt90: Mapped[int] = mapped_column(Integer)
    samples: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[int] = mapped_column(Integer)
    moq: Mapped[int] = mapped_column(Integer)


class ServerEvent(Base):
    """SSE 실시간 이벤트 (API 명세서 NOT-03). id는 SSE 이벤트 ID로 쓴다."""

    __tablename__ = "events"
    __table_args__ = (Index("ix_events_company_id_id", "company_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(32))
    data: Mapped[dict[str, Any]]
    created_at: Mapped[datetime] = _created_at()


class Review(Base):
    """발주 검토 (API 명세서 REV-01·02). 목록 정렬·필터에 쓰는 값만 열로 두고 나머지는 JSONB."""

    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint("entry IN ('staff_request', 'stock_draft', 'missed_draft')", name="entry"),
        CheckConstraint(
            "status IN ('reviewing', 'reviewed', 'held', 'approved', 'closed', 'expired')",
            name="status",
        ),
        CheckConstraint("verdict IS NULL OR verdict IN ('ok', 'revise', 'hold')", name="verdict"),
        CheckConstraint("flags <@ ARRAY['urgent', 'caution', 'alternative']::text[]", name="flags"),
        CheckConstraint(
            "hold_reasons <@ "
            "ARRAY['part_unresolved', 'supplier_unresolved', 'no_demand_data']::text[]",
            name="hold_reasons",
        ),
        # 직원 요청만 요청자가 있고, 시스템 초안(재고 부족·놓친 발주)은 요청자가 없다.
        CheckConstraint("(entry = 'staff_request') = (requested_by IS NOT NULL)", name="requester"),
        CheckConstraint("(decided_at IS NULL) = (decided_by IS NULL)", name="decided_pair"),
        Index("ix_reviews_company_status", "company_id", "status"),
        Index("ix_reviews_company_part", "company_id", "part_id"),
    )

    id: Mapped[uuid.UUID] = _id()
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    entry: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), server_default="reviewing")
    # 검토가 끝나기 전에는 null
    verdict: Mapped[str | None] = mapped_column(String(8))
    flags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    hold_reasons: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    # 부품을 특정하지 못하면(보류 part_unresolved) null
    part_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parts.id"))
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chat_messages.id"))
    # 원안: {"qty", "supplier_id", "unit_price", "text"}
    request: Mapped[dict[str, Any]]
    # 엔진 결과(checks, original, proposal, alternatives, risk_if_not_ordered, count_requests)
    result: Mapped[dict[str, Any] | None]
    # 의견서: {"text", "source", "verified"}
    opinion: Mapped[dict[str, Any] | None]
    original_total: Mapped[int | None] = mapped_column(BigInteger)
    saving: Mapped[int] = mapped_column(BigInteger, server_default="0")
    # 미발주 시 예상 손실. 목록 정렬(긴급 먼저, 그다음 예상 손실)에 쓴다.
    loss: Mapped[int] = mapped_column(BigInteger, server_default="0")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision: Mapped[dict[str, Any] | None]
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReviewSnapshot(Base):
    """검토 근거 스냅샷 (F-REVIEW-02). 현재 스냅샷은 검토의 가장 최근 행이다."""

    __tablename__ = "review_snapshots"
    __table_args__ = (Index("ix_review_snapshots_review_created", "review_id", "created_at"),)

    id: Mapped[uuid.UUID] = _id()
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    review_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reviews.id", ondelete="CASCADE"))
    hash: Mapped[str] = mapped_column(String(80))
    values: Mapped[dict[str, Any]]
    # 스냅샷을 만들 때 쓴 설정값. 설정이 바뀌어도 이 검토의 판정은 그대로 재현된다.
    settings: Mapped[dict[str, Any]]
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LlmCall(Base):
    """ai 호출 한 번의 비용·장애 기록. 재시도까지 합친 값이다 (bjk_contracts.LlmUsage)."""

    __tablename__ = "llm_calls"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('chat_parse', 'import_suggest', 'opinion', 'embedding')", name="purpose"
        ),
        # 회사별 일일 토큰 합계 (호출 제한, API 명세서 1-5)
        Index("ix_llm_calls_company_created", "company_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _id()
    company_id: Mapped[uuid.UUID] = _company_id()
    purpose: Mapped[str] = mapped_column(String(16))
    model: Mapped[str] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer)
    attempts: Mapped[int] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = _created_at()
