"""검토 조회 테스트용 행. 검토 실행 서비스(#146)와 같은 구조로 저장한다."""

import uuid
from datetime import date, datetime, timedelta

from bjk_review import (
    OpenOrder,
    OrderRequest,
    PriceStats,
    ReviewSettings,
    ReviewSnapshot,
    SupplierOffer,
    run_review,
)
from bjk_server.db.models import Review
from bjk_server.db.models import ReviewSnapshot as SnapshotRow
from bjk_server.seed.demo import COMPANY_CODE, demo_id
from sqlalchemy.orm import Session

COMPANY = demo_id("company", COMPANY_CODE)
VBELT = demo_id("part", "a42")
SUP_A, SUP_B = str(demo_id("supplier", "a")), str(demo_id("supplier", "b"))
COMPUTED_AT = datetime.fromisoformat("2026-11-04T03:00:00+09:00")


def vbelt_snapshot() -> ReviewSnapshot:
    """기능명세서 F-REVIEW-10 V벨트 예시(S 2, O 10, m 1.5)."""
    return ReviewSnapshot(
        as_of=date(2026, 11, 4),
        computed_at=COMPUTED_AT,
        part_id=str(VBELT),
        part_name="V벨트 A-42",
        stock=2,
        incoming=10,
        open_orders=[OpenOrder(qty=10, eta=date(2026, 11, 8))],
        m=1.5,
        d95=4,
        d99=5,
        default_supplier_id=SUP_A,
        suppliers=[
            SupplierOffer(supplier_id=SUP_A, name="공급사 A", unit_price=18000, lt90=7),
            SupplierOffer(supplier_id=SUP_B, name="공급사 B", unit_price=15000, moq=5, lt90=8),
        ],
        price_stats=PriceStats(mean=13000, sigma=1200, n=4),
    )


def add_review(
    s: Session,
    *,
    snapshot: ReviewSnapshot | None = None,
    qty: int = 30,
    entry: str = "staff_request",
    requested_by: uuid.UUID | None = None,
    created_at: datetime = COMPUTED_AT,
    status: str | None = None,
) -> Review:
    """검토를 실행해 저장한 상태의 행. `status`만 바꾸면 결정 뒤 상태도 흉내 낸다."""
    snapshot = snapshot or vbelt_snapshot()
    request = OrderRequest(qty=qty, supplier_id=SUP_A, unit_price=18000)
    settings = ReviewSettings()
    result = run_review(snapshot, request, settings)
    if entry == "staff_request" and requested_by is None:
        requested_by = demo_id("user", "worker")
    review = Review(
        id=uuid.uuid4(),
        company_id=COMPANY,
        entry=entry,
        status=status or ("held" if result.verdict == "hold" else "reviewed"),
        part_id=uuid.UUID(snapshot.part_id) if snapshot.part_id else None,
        requested_by=requested_by,
        request={**request.model_dump(mode="json"), "text": f"V벨트 {qty}개"},
        verdict=result.verdict,
        flags=list(result.flags),
        hold_reasons=list(result.hold_reasons),
        result=result.model_dump(
            mode="json", exclude={"verdict", "flags", "hold_reasons", "review_hash"}
        ),
        opinion={
            "text": "[수정 권고] 이번 발주는 필요하지 않습니다.",
            "source": "template",
            "verified": True,
        },
        original_total=result.original.total,
        saving=result.proposal.saving if result.proposal else 0,
        loss=result.risk_if_not_ordered.loss,
        expires_at=created_at + timedelta(days=7),
        created_at=created_at,
    )
    s.add(review)
    s.flush()
    s.add(
        SnapshotRow(
            company_id=COMPANY,
            review_id=review.id,
            hash=result.review_hash,
            values=snapshot.model_dump(mode="json"),
            settings=settings.model_dump(mode="json"),
            computed_at=snapshot.computed_at,
        )
    )
    return review
