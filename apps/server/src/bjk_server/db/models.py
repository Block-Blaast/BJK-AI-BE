"""MVP 기본 테이블. 회사 소유 테이블은 모두 company_id를 가진다."""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
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


class CompanySettings(Base):
    __tablename__ = "company_settings"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True
    )
    notify: Mapped[dict[str, Any]]
    review: Mapped[dict[str, Any]]
    system: Mapped[dict[str, Any]]
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
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PartAlias(Base):
    __tablename__ = "part_aliases"
    __table_args__ = (UniqueConstraint("company_id", "text", "part_id"),)

    id: Mapped[uuid.UUID] = _id()
    company_id: Mapped[uuid.UUID] = _company_id()
    part_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parts.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(String(100))
    confirmed_count: Mapped[int] = mapped_column(Integer, server_default="0")
    ambiguous: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("false"))
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
