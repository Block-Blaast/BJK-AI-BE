"""의심 항목 저장과 장부 검증 실행 (F-AUDIT-01~06, F-LEDGER-03).

규칙 판정은 bjk_server.domain.audit의 순수 함수가 하고, 여기서는 원장을 읽어 넘기고 결과를
audit_flags에 묶어 저장한다.
"""

import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from bjk_server.clock import KST
from bjk_server.db.models import (
    AuditFlag,
    CompanySettings,
    EquipmentPart,
    Maintenance,
    Movement,
    Part,
    PartMetrics,
)
from bjk_server.defaults import DEFAULT_SETTINGS
from bjk_server.domain import audit as rules
from bjk_server.domain.audit import Hit, LedgerRow

# 정비 완료 기록을 거슬러 보는 기간. 그보다 오래된 정비는 새로 판단하지 않는다.
MAINTENANCE_LOOKBACK = timedelta(days=14)
# 급변 사후 점검 대상 출고 기간 (배치가 하루 빠져도 놓치지 않도록 넉넉히)
SPIKE_LOOKBACK = timedelta(days=7)
PATTERN_WEEKS = 52


def _is_event_key(key: str) -> bool:
    """정비·원장 행처럼 사건을 가리키는 키. 규칙 이름만인 키와 구분한다."""
    return ":" in key


def _suppress_days(db: Session, company_id: uuid.UUID) -> int:
    row = db.get(CompanySettings, company_id)
    system = row.system if row else DEFAULT_SETTINGS["system"]
    return int(system.get("count_suppress_days", DEFAULT_SETTINGS["system"]["count_suppress_days"]))


def _entry(hit: Hit) -> dict:
    return {"rule": hit.rule, "level": hit.level, "evidence": hit.evidence}


def record_hits(
    db: Session,
    company_id: uuid.UUID,
    part_id: uuid.UUID,
    hits: Sequence[Hit],
    now: datetime,
    suppress_days: int,
) -> tuple[AuditFlag | None, bool]:
    """걸린 규칙을 부품의 열린 항목 하나에 묶는다. (항목, 새로 만들었는지)를 돌려준다.

    - 사건 키(정비·원장 행)는 한 번 의심 항목이 됐으면 다시 만들지 않는다.
    - 규칙 키(소모 패턴·실사 경과)는 열린 항목에 있거나 닫힌 지 억제 기간이 안 됐으면 건너뛴다.
    - 열린 항목이 있으면 대표 규칙을 등급 순으로 다시 고르고 나머지는 related에 둔다.
    """
    flags = db.scalars(
        select(AuditFlag).where(AuditFlag.part_id == part_id).with_for_update()
    ).all()
    open_flag = next((f for f in flags if f.status != "closed"), None)
    seen = {k for f in flags for k in f.keys}
    recent = {
        k
        for f in flags
        if f.status == "closed"
        and f.closed_at
        and now - f.closed_at < timedelta(days=suppress_days)
        for k in f.keys
    }
    open_keys = set(open_flag.keys) if open_flag else set()
    fresh = [
        h
        for h in hits
        if h.key not in open_keys
        and not (_is_event_key(h.key) and h.key in seen)
        and not (not _is_event_key(h.key) and h.key in recent)
    ]
    if not fresh:
        return open_flag, False

    if open_flag is None:
        top = rules.primary(fresh)
        flag = AuditFlag(
            id=uuid.uuid4(),
            company_id=company_id,
            part_id=part_id,
            rule=top.rule,
            level=top.level,
            status="open",
            evidence=top.evidence,
            related=[_entry(h) for h in fresh if h is not top],
            keys=[h.key for h in fresh],
            created_at=now,
            updated_at=now,
        )
        db.add(flag)
        db.flush()
        return flag, True

    current = Hit(open_flag.rule, "", open_flag.evidence)
    others = [Hit(r["rule"], "", r["evidence"]) for r in open_flag.related]
    top = rules.primary([current, *fresh])
    if top is not current:
        open_flag.rule, open_flag.level, open_flag.evidence = top.rule, top.level, top.evidence
        others.append(current)
    open_flag.related = [_entry(h) for h in [*others, *fresh] if h is not top]
    open_flag.keys = [*open_flag.keys, *(h.key for h in fresh)]
    open_flag.updated_at = now
    return open_flag, False


def check_after_record(
    db: Session, part: Part, movement: Movement, stock_after: int
) -> uuid.UUID | None:
    """기록 직후 음수 재고 검사 (F-LEDGER-03). 0 미만으로 넘어가면 의심 항목을 바로 만든다."""
    if not stock_after - movement.qty >= 0 > stock_after:
        return None
    row = LedgerRow(movement.id, movement.type, movement.qty, movement.occurred_at.astimezone(KST))
    flag, _ = record_hits(
        db,
        part.company_id,
        part.id,
        [rules.negative_stock_hit(row, stock_after)],
        movement.occurred_at,
        _suppress_days(db, part.company_id),
    )
    return flag.id if flag else None


def _weekly_events(rows: Sequence[LedgerRow], now: datetime) -> list[int]:
    """정비에 연결되지 않은 출고 횟수를 주별로 센다 (오래된 주 → 최근 주, 첫 기록 주부터)."""
    outs = [r for r in rows if r.type == "OUT" and r.maintenance_id is None]
    if not rows:
        return []
    today = now.astimezone(KST).date()
    first = rows[0].occurred_at.astimezone(KST).date()
    weeks = max(0, min(PATTERN_WEEKS, (today - first).days // 7))
    buckets = [0] * weeks
    for r in outs:
        index = weeks - 1 - (today - r.occurred_at.astimezone(KST).date()).days // 7
        if 0 <= index < weeks:
            buckets[index] += 1
    return buckets


def audit_company(db: Session, company_id: uuid.UUID, now: datetime) -> int:
    """새벽 배치 장부 검증. 회사가 지정된 세션에서 근거 지표 계산 뒤에 실행한다.

    새로 만든 의심 항목 수를 돌려준다.
    """
    today = now.astimezone(KST).date()
    suppress_days = _suppress_days(db, company_id)
    parts = db.scalars(
        select(Part).where(Part.company_id == company_id, Part.merged_into.is_(None))
    ).all()
    ledger: dict[uuid.UUID, list[LedgerRow]] = defaultdict(list)
    for m in db.execute(
        select(
            Movement.id,
            Movement.part_id,
            Movement.type,
            Movement.qty,
            Movement.occurred_at,
            Movement.maintenance_id,
        )
        .where(Movement.company_id == company_id, Movement.occurred_at <= now)
        .order_by(Movement.occurred_at, Movement.created_at, Movement.id)
    ):
        # 근거에 남는 시각은 화면 기준(Asia/Seoul)으로 둔다.
        occurred_at = m.occurred_at.astimezone(KST)
        ledger[m.part_id].append(LedgerRow(m.id, m.type, m.qty, occurred_at, m.maintenance_id))
    demand_class = dict(
        db.execute(
            select(PartMetrics.part_id, PartMetrics.demand_class).where(
                PartMetrics.company_id == company_id, PartMetrics.computed_on == today
            )
        ).all()
    )

    hits: dict[uuid.UUID, list[Hit]] = defaultdict(list)
    per_maintenance = {
        (link.equipment_id, link.part_id): link.qty_per_maintenance
        for link in db.scalars(select(EquipmentPart).where(EquipmentPart.company_id == company_id))
    }
    for m in db.scalars(
        select(Maintenance).where(
            Maintenance.company_id == company_id,
            Maintenance.completed_at.between(now - MAINTENANCE_LOOKBACK, now),
        )
    ):
        if m.required_parts is not None:
            required: dict[uuid.UUID, int] = defaultdict(int)
            for item in m.required_parts:
                required[uuid.UUID(item["part_id"])] += int(item["qty"])
        else:
            required = {p: q for (e, p), q in per_maintenance.items() if e == m.equipment_id}
        for part_id, qty in required.items():
            linked = sum(
                -r.qty
                for r in ledger.get(part_id, [])
                if r.type == "OUT" and r.maintenance_id == m.id
            )
            completed_at = m.completed_at.astimezone(KST)
            hit = rules.maintenance_mismatch(m.id, completed_at, qty, linked, now)
            if hit:
                hits[part_id].append(hit)

    for part in parts:
        rows = ledger.get(part.id, [])
        if not rows:
            continue
        hits[part.id] += rules.negative_stock(rows)
        if demand_class.get(part.id) == "smooth":
            pattern = rules.pattern_deviation(_weekly_events(rows, now))
            if pattern:
                hits[part.id].append(pattern)
        hits[part.id] += rules.spikes([r for r in rows if r.type == "OUT"], now - SPIKE_LOOKBACK)
        # 실사 기록 기능 전이라 원장 첫 기록일부터 센다.
        overdue = rules.count_overdue(
            None,
            rows[0].occurred_at.astimezone(KST).date(),
            sum(1 for r in rows[1:] if r.type in ("IN", "OUT")),
            today,
        )
        if overdue:
            hits[part.id].append(overdue)

    active = {p.id for p in parts}
    created = 0
    for part_id, part_hits in hits.items():
        if part_id in active and part_hits:
            _, new = record_hits(db, company_id, part_id, part_hits, now, suppress_days)
            created += new
    db.flush()
    return created
