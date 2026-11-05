# 발주 테이블과 열린 발주·최근 단가 조회

- 날짜: 2026-11-05
- 영역: server
- 관련: #161, F-APPROVAL-02·03, F-REVIEW-02, F-LEDGER-04, PO-01~04

## 목적

- 발주(PO) 트랙의 저장 기반과 검토 스냅샷이 쓸 O·p̄·σ_p·n 조회 함수 마련

## 한 일

- `purchase_orders` 테이블·RLS·인덱스(마이그레이션 0026), `PurchaseOrder` 모델
- `movements.po_id`에 `purchase_orders` 외래 키 추가
- `purchasing/orders.py`: `open_orders`, `open_qty`, `remaining_qty`, `recent_price_stats`
- `domain/purchase_order.py`에 `price_stats` 순수 함수 추가(#137의 상태 전이 함수는 그대로 사용)

## 결정과 근거

- 열은 API 명세서 PO-01·02 응답 기준. 주문 완료 없이 입고된 건은 `implicit_order`로 표시해 납기 표본에서 제외(F-LEDGER-04)
- `review_id`는 null 허용. 시드의 과거 발주 이력(#12)은 검토가 없음
- 최근 구매 단가는 취소 제외 최근 1년·최신 20건, 표본 표준편차(n − 1)
- 검토 스냅샷 연결은 #146 머지 후 별도 PR로 분리(#161 코멘트)

## 검증

- `tests/test_purchase_orders.py` 7개(열린 발주·미입고 수량, 단가 통계, 제약 4종, 회사 격리), `price_stats` 단위 테스트 1개
- `REQUIRE_DB_TESTS=1 make test` 694개 통과, `make lint` 통과

## 남은 일·확인 필요

- 검토 스냅샷 O·C-03·단가 통계 연결(작업 6)
- `api/parts.py`의 `stock.incoming`은 아직 빈 목록. A 레인 파일이라 O 연결 때 같이 확인 필요
