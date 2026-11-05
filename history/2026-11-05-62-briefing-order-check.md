# 브리핑 주문 확인 필요 집계 정리

- 날짜: 2026-11-05
- 영역: server
- 관련: Issue #182, DSH-01, F-NOTI-02, F-MISSED-02

## 목적

- #182 남은 항목 `order_check_needed` 집계를 명세와 맞춤

## 한 일

- `briefing/service.py`: 24시간 미주문 발주에 더해 LT90을 넘긴 미입고 발주도 집계
- `jobs/order_check.py`: 대상 발주 조회(`not_ordered`, `overdue_receipts`)를 공개해 브리핑과 같은 기준 사용
- `docs/api-spec/briefing.md` 갱신

## 결정과 근거

- F-MISSED-02: 주문 확인·입고 확인 두 경우 모두 아침 브리핑에 표시
- 응답 필드는 그대로 두고 두 경우를 `order_check_needed` 하나로 합산(API 명세서 DSH-01 필드 목록 유지)

## 검증

- `test_briefing.py`, `test_order_check.py` 9개 통과
- `make lint` 통과
- 전체 테스트는 사용자 지시로 별도 세션에서 실행 예정(미실행)

## 남은 일·확인 필요

- 없음
