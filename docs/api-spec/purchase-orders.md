# 발주 (PO)

정본: Notion「API 명세서」8장 PO-01~04, 기능명세서 F-APPROVAL-02·03, F-LEDGER-04. 권한은 manager 이상(worker 403).

## PO-01 GET /api/v1/purchase-orders

Query: `status`(`approved`, `ordered`, `partially_received`, `received`, `cancelled`), `part_id`, `supplier_id`, `cursor`, `limit`. 최근 승인부터.

```json
{
  "items": [
    {
      "id": "...", "review_id": null,
      "part": { "id": "...", "name": "볼베어링 6204ZZ" },
      "supplier": { "id": "...", "name": "공급사 B" },
      "qty": 10, "unit_price": 14800, "total": 148000,
      "status": "ordered",
      "approved_at": "2026-11-04T02:00:00Z", "approved_by": "김사장",
      "ordered_at": "2026-11-04T02:20:00Z", "ordered_by": "김사장",
      "received_qty": 0, "received_at": null, "actual_lead_time_days": null
    }
  ],
  "next_cursor": null
}
```

- `actual_lead_time_days`: 입고 완료된 발주의 주문 완료 → 입고 완료 일수. 주문 완료 표시 없이 입고된 건(서버가 `ordered`로 보정)은 납기 표본에서 빼 `null`, `ordered_by`도 `null`.
- `order_message`(공급사 문자 문구)는 PO-02 상세에서 준다(#163).

## PO-04 POST /api/v1/purchase-orders/{id}/cancel

```json
// Request (reason 선택)
{ "reason": "재고 확인 결과 불필요" }
// 200 Response
{ "id": "...", "status": "cancelled" }
```

- `approved`에서만 받는다. 그 밖의 상태는 409 `ORDER_STATE_CONFLICT`(`detail.status`, `detail.action`). 없는 발주는 404.
- 취소한 발주는 열린 발주(입고 예정 O, C-03, 초안 차단)에서 빠진다.
