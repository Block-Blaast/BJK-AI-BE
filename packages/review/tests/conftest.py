"""기능명세서 F-REVIEW-10 예시 5개와 볼트 H_u 변형의 검토 입력.

예시 표에 없는 값(공급사 납기·MOQ·배송비, D99, m 등)은 예시의 판정이 성립하는 범위에서 정했다.
"""

from datetime import date, datetime

import pytest
from bjk_review import (
    HiddenStock,
    OpenOrder,
    OrderRequest,
    PriceStats,
    PriceTier,
    ReviewSnapshot,
    SupplierOffer,
)

AS_OF = date(2026, 11, 4)
COMPUTED_AT = datetime.fromisoformat("2026-11-04T03:00:00+09:00")


def snapshot(**values):
    defaults = {"as_of": AS_OF, "computed_at": COMPUTED_AT, "part_id": "p-1"}
    return ReviewSnapshot(**{**defaults, **values})


def vbelt():
    return snapshot(
        part_name="V벨트 A-42",
        stock=2,
        incoming=10,
        open_orders=[OpenOrder(qty=10, eta=date(2026, 11, 8))],
        m=1.5,
        d95=4,
        d99=5,
        default_supplier_id="sup-a",
        suppliers=[
            SupplierOffer(supplier_id="sup-a", name="공급사 A", unit_price=18000, lt90=7),
            SupplierOffer(supplier_id="sup-b", name="공급사 B", unit_price=15000, moq=5, lt90=8),
        ],
        price_stats=PriceStats(mean=13000, sigma=1200, n=4),
    )


def bearing_6205():
    return snapshot(
        part_name="볼베어링 6205ZZ",
        stock=3,
        f_period=4,
        f_12m=16,
        m=0.5,
        d95=11,
        d99=13,
        t_out=date(2026, 11, 20),
        t_deadline=date(2026, 11, 9),
        default_supplier_id="sup-a",
        suppliers=[
            SupplierOffer(
                supplier_id="sup-a",
                name="공급사 A",
                unit_price=18000,
                moq=10,
                price_tiers=[PriceTier(min_qty=20, unit_price=16500)],
                shipping_fee=4000,
                lt90=11,
            )
        ],
        import_dependent=True,
        r_lead=1.5,
        loss=2400000,
        loss_equipment=["3호기"],
        loss_is_estimate=True,
    )


def bolt(confirmed):
    return snapshot(
        part_name="볼트 M8×20",
        stock=40,
        hidden=[HiddenStock(part_id="p-hexa", name="헥사볼트 M8x20", qty=800, confirmed=confirmed)],
        m=30,
        d95=120,
        d99=130,
        default_supplier_id="sup-a",
        suppliers=[
            SupplierOffer(supplier_id="sup-a", name="공급사 A", unit_price=120, moq=10, lt90=3)
        ],
    )


def bearing_6204():
    return snapshot(
        part_name="볼베어링 6204ZZ",
        stock=2,
        m=4,
        d95=12,
        d99=14,
        t_out=date(2026, 11, 30),
        default_supplier_id="sup-a",
        suppliers=[
            SupplierOffer(
                supplier_id="sup-a", name="공급사 A", unit_price=21000, shipping_fee=4000, lt90=5
            ),
            SupplierOffer(
                supplier_id="sup-b",
                name="공급사 B",
                unit_price=14800,
                moq=10,
                shipping_fee=3000,
                lt90=6,
            ),
        ],
        price_stats=PriceStats(mean=15500, sigma=900, n=5),
    )


def bearing_6203():
    return snapshot(
        part_name="볼베어링 6203ZZ",
        stock=2,
        m=4,
        d95=12,
        d99=14,
        t_out=date(2026, 11, 30),
        default_supplier_id="sup-a",
        suppliers=[
            SupplierOffer(supplier_id="sup-a", name="공급사 A", unit_price=9000, lt90=5),
            SupplierOffer(supplier_id="sup-c", name="공급사 C", unit_price=7900, lt90=6),
        ],
        price_stats=PriceStats(mean=9000, sigma=300, n=5),
    )


CASES = {
    "vbelt": (vbelt, OrderRequest(qty=30, supplier_id="sup-a", unit_price=18000)),
    "bearing_6205": (bearing_6205, OrderRequest(qty=10)),
    "bolt_confirmed": (lambda: bolt(True), OrderRequest(qty=50, supplier_id="sup-a")),
    "bolt_unconfirmed": (lambda: bolt(False), OrderRequest(qty=50, supplier_id="sup-a")),
    "bearing_6204": (bearing_6204, OrderRequest(qty=10, supplier_id="sup-a", unit_price=21000)),
    "bearing_6203": (bearing_6203, OrderRequest(qty=10, supplier_id="sup-a", unit_price=9000)),
}


@pytest.fixture
def case():
    """`case("vbelt")` → (스냅샷, 원안). 호출마다 새 스냅샷을 만든다."""

    def _case(name):
        build, request = CASES[name]
        return build(), request

    return _case


@pytest.fixture(params=list(CASES))
def each_case(request, case):
    return case(request.param)
