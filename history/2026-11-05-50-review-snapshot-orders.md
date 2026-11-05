# 검토 스냅샷에 열린 발주 O·C-03·최근 단가 연결

- 날짜: 2026-11-05
- 영역: server
- 관련: #161 남은 항목, F-REVIEW-02·04, C-03·C-05

## 목적

- 발주 테이블(#207)을 검토 근거에 반영해 입고 예정 O, 중복 발주 C-03, 단가 이상 C-05가 동작하게 함

## 한 일

- `reviews/snapshot.py`에 수집 함수 `_orders` 하나를 `COLLECTORS`에 추가 (기존 수집 함수는 그대로)
- `open_orders`, `incoming`, `price_stats` 채움. `purchasing/orders.py` 조회 함수 재사용
- `tests/test_review_snapshot_orders.py` 5개

## 결정과 근거

- 대상 부품: 그 부품과 그 부품으로 병합된 부품. 같은 규격 다른 등록 부품은 숨은 재고(C-04)가 따로 다룸
- 도착 예정일: 주문 완료 시각(없으면 승인 시각) + 부품×공급사 LT50, 새벽 계산 전이면 공급사 기본 납기, 없으면 7일
- O는 필요 시점(t_out) 이전 도착분만. t_out이 없으면 잔량 전부 (F-REVIEW-02 "필요 시점 전 도착분")
- 단가 통계는 취소 제외 최근 1년·최신 20건, 표본 표준편차

## 검증

- `tests/test_review_snapshot_orders.py` 5개 통과 (O·C-03·수정안 0개, 부분입고 잔량, 늦은 도착 제외, C-05, 발주 없음)
- `REQUIRE_DB_TESTS=1 make test` 813개 통과(1개 건너뜀), `make lint` 통과

## 남은 일·확인 필요

- nightly 재주문점·권장량(F-ANAL-09 R의 O)과 실제 납기 LT50·LT90 반영은 다음 작업
- `api/parts.py`(SET-04)의 `stock.incoming`은 A 레인 파일이라 그대로 빈 목록
