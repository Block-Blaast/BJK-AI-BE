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

## PO-02 GET /api/v1/purchase-orders/{id}

- 권한: manager 이상. worker는 403, 없는 발주·다른 회사 발주는 404.
- PO-01 항목에 `order_message`(공급사 문자 문구, F-APPROVAL-03)를 더한다. 희망 납기는 발주를 만든 검토의 최근 스냅샷 `t_out`(필요 시점)이고, 검토 없이 들어온 발주나 `t_out`이 없으면 날짜 문장을 뺀다.

```json
{ "order_message": "안녕하세요. V벨트 A-42 4개 주문 부탁드립니다. 11월 12일까지 받을 수 있을까요?" }
```

## PO-03 POST /api/v1/purchase-orders/{id}/mark-ordered

- 권한: manager 이상.
- 전화·문자로 주문했다고 표시한다. `ordered`로 바꾸고 `ordered_at`·`ordered_by`(요청자)를 남긴다. 실제 납기는 이 시각부터 잰다(F-LEDGER-04).

```json
// Request (ordered_at을 비우면 지금)
{ "ordered_at": "2026-11-04T11:20:00+09:00" }
// 200 Response
{ "id": "...", "status": "ordered", "ordered_at": "2026-11-04T11:20:00+09:00" }
```

| 상황 | 응답 |
| --- | --- |
| `approved`가 아닌 발주 | 409 `ORDER_STATE_CONFLICT`, `detail` `{status, action: "mark_ordered"}` |
| `ordered_at`이 승인 시각보다 이르거나 미래, 시간대 없음 | 400 `VALIDATION_ERROR`, `detail.field` (명세에 없어 이 레포에서 정함) |
| 없는 발주, 다른 회사 발주 | 404 `NOT_FOUND` |

## PO-04 POST /api/v1/purchase-orders/{id}/cancel

```json
// Request (reason 선택)
{ "reason": "재고 확인 결과 불필요" }
// 200 Response
{ "id": "...", "status": "cancelled" }
```

- `approved`에서만 받는다. 그 밖의 상태는 409 `ORDER_STATE_CONFLICT`(`detail.status`, `detail.action`). 없는 발주는 404.
- 취소한 발주는 열린 발주(입고 예정 O, C-03, 초안 차단)에서 빠진다.
