# 발주 상세·주문 완료 표시 API

- 날짜: 2026-11-05
- 영역: server
- 관련: #163, F-APPROVAL-03, F-LEDGER-04, PO-02·03

## 목적

- 승인된 발주의 공급사 문자 문구 확인과 실제 주문 시각 기록

## 한 일

- `api/purchase_orders.py`: `GET /purchase-orders/{id}`(PO-01 항목 + `order_message`), `POST /purchase-orders/{id}/mark-ordered`(상태 전이 순수 함수 `mark_ordered`, 주문 완료자·시각 기록)
- 테스트 `test_purchase_order_detail.py` 7개, 문서 `docs/api-spec/purchase-orders.md`

## 결정과 근거

- 문자 문구 희망 납기는 결정 API와 같게 검토 스냅샷 `t_out`
- `ordered_at`은 승인 시각 이후·지금 이전만 허용(명세에 없음, 실제 납기 표본 오염 방지)

## 검증

- 로컬 PostgreSQL 16 `REQUIRE_DB_TESTS=1 make test` 850개 통과(PDF 모듈 1개는 macOS `make` 환경에서 건너뜀), `make lint` 통과

## 남은 일·확인 필요

- `ordered_at` 범위 검증 정책 확인
