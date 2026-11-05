# 발주 목록·주문 취소 API

- 날짜: 2026-11-05
- 영역: server
- 관련: #165, PO-01·04, F-APPROVAL-02

## 목적

- 발주 목록(W-09)과 주문하지 않기로 한 발주의 취소 제공

## 한 일

- `api/purchase_orders.py`: PO-01 목록(상태·부품·공급사 필터, 커서), PO-04 취소(사유 저장)
- 응답 모양 `PurchaseOrderOut`은 PO-02 상세(#163)에서 같이 쓰도록 둠
- `docs/api-spec/purchase-orders.md`, 테스트 10개

## 결정과 근거

- 취소는 `domain/purchase_order.cancel`로 상태 확인, 그 밖 상태는 409 `ORDER_STATE_CONFLICT`
- 발주 행 `FOR UPDATE` 후 상태 변경. 입고 대조(#164)와 같은 행을 동시에 바꾸지 않게 함
- 주문 완료 표시 없이 입고된 발주는 `ordered_by`·`actual_lead_time_days`를 `null`로 보여 줌(납기 표본 제외 표시)
- `actual_lead_time_days` 계산이 #164 `lead_time_days`를 써서 #164 브랜치 위에서 작업

## 검증

- `tests/test_purchase_order_api.py` 10개 통과
- `REQUIRE_DB_TESTS=1 make test` 724개 통과, `make lint` 통과 (#164 브랜치 기준)

## 남은 일·확인 필요

- #207·#216 머지 후 dev 기준으로 맞춤
