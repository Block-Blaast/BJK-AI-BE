"""수량 올림과 공급사별 금액 계산.

금액 표시(원안·수정안·대안의 `total`)는 단가 × 수량이고, 공급사를 고를 때만 배송비를 더한
총액으로 비교한다(F-REVIEW-05 2번). F-REVIEW-10 예시의 금액이 단가 × 수량이기 때문이다.
"""

from bjk_review.models import SupplierOffer


def ceil_to_moq(qty: int, moq: int) -> int:
    """MOQ 배수로 올림. 0 이하면 0(발주 불필요)."""
    if qty <= 0:
        return 0
    moq = max(moq, 1)
    return -(-qty // moq) * moq


def unit_price_at(offer: SupplierOffer, qty: int) -> int:
    price = offer.unit_price
    for tier in sorted(offer.price_tiers, key=lambda t: t.min_qty):
        if qty >= tier.min_qty:
            price = tier.unit_price
    return price


def landed_cost(offer: SupplierOffer, qty: int) -> tuple[int, int, int]:
    """그 공급사에서 살 때의 (MOQ 올림 수량, 단가, 배송비 포함 총액)."""
    qty = ceil_to_moq(qty, offer.moq)
    price = unit_price_at(offer, qty)
    shipping = offer.shipping_fee if qty > 0 else 0
    return qty, price, qty * price + shipping
