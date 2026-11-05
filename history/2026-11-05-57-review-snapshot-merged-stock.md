# 검토 스냅샷에 병합 부품 재고 연결

- 날짜: 2026-11-05
- 영역: server
- 관련: #209 마지막 항목, F-LEDGER-02, F-MATCH-03

## 목적

- 부품 병합(#213) 후 검토 근거가 병합된 부품의 원장까지 보게 함

## 한 일

- `reviews/snapshot.py` `_stock`: 사용 기록 여부(`has_usage_history`)에 병합된 부품의 출고 포함. S는 #213의 `stock_of`가 이미 병합 합산
- `_hidden`: 같은 규격 다른 등록 부품의 재고를 `stock_subquery`로 계산해 그 부품에 병합된 부품까지 합산
- 모듈 설명의 "병합 부품 재고 비어 있음" 문구 정리
- `tests/test_review_snapshot_merged.py` 2개

## 결정과 근거

- 합산 규칙은 `inventory.stock_of`·`stock_subquery`(#213)를 그대로 따름
- 병합된 부품 자신은 숨은 재고 후보에서 빠짐(`merged_into IS NULL` 조건 유지)

## 검증

- `REQUIRE_DB_TESTS=1 make test` 876개 통과(1개 건너뜀), `make lint` 통과

## 남은 일·확인 필요

- 없음
