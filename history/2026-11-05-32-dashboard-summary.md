# 대시보드 요약 조회

- 날짜: 2026-11-05
- 영역: server
- 관련: #180, DSH-02, W-01

## 목적

- 관리자 웹 첫 화면의 위험 부품·검토 대기·의심 항목·묶인 재고·외부 요인·오늘 활동 요약 제공

## 한 일

- `api/dashboard.py`: `GET /dashboard/summary`
- `docs/api-spec/dashboard.md`, `tests/test_dashboard.py`

## 결정과 근거

- `tied_up_stock_amount`: 명세에 계산식 없음. 2026-11-05 사용자 결정으로 180일 미출고 부품의 재고 × 단가
- `pending_reviews`: 2026-11-05 사용자 결정으로 `reviewed`·`held`
- `awaiting_order`: 발주 테이블(G4) 전이라 0
- `external.level`: DSH-03 계산을 재사용해 지표 등급 최댓값

## 검증

- `REQUIRE_DB_TESTS=1 uv run pytest apps/server/tests/test_dashboard.py`: 5개 통과
- `REQUIRE_DB_TESTS=1 make test`: 702개 통과, `make lint` 통과
- 시드 DB(`bjk_b`) nightly 후 server :8020 실제 호출로 응답 형식 확인

## 남은 일·확인 필요

- 발주 트랙 머지(G4) 후 `awaiting_order` 연결
