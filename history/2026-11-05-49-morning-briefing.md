# 아침 브리핑과 briefing 배치

- 날짜: 2026-11-05
- 영역: server
- 관련: #182, DSH-01, F-NOTI-02, F-MISSED-02, F-SETUP-04, F-APPROVAL-02

## 목적

- 사장님·관리자가 아침에 확인할 일을 한 화면과 알림으로 받기

## 한 일

- `briefing/service.py`: 브리핑 계산(놓친 발주·검토 대기·실사 필요·주문 확인·정비 완료 확인)
- `api/briefing.py`: `GET /briefing/today`
- `jobs/briefing.py`: 결정 대기 검토 만료와 요청자 알림, 브리핑 알림(하루 1회)
- `docs/api-spec/briefing.md`, `jobs.md` 갱신, `tests/test_briefing.py`

## 결정과 근거

- 실사 필요: 실사를 아직 요청하지 않은 열린 의심 항목. 명세에 정확한 기준이 없어 관리자가 처리할 건으로 정함
- 검토 대기: 놓친 발주와 겹치지 않게 `missed_draft` 제외
- 주문 확인: 승인 후 24시간 미주문만. LT90 초과 미입고는 order-check(G4)와 함께
- 만료 알림 채널은 F-NOTI-04 결정 결과 표 기준 `chat`

## 검증

- `REQUIRE_DB_TESTS=1 uv run pytest apps/server/tests/test_briefing.py`: 4개 통과
- `REQUIRE_DB_TESTS=1 make test`: 812개 통과(1개 생략), `make lint` 통과
- 시드 DB(`bjk_b`) nightly → briefing 배치 → `GET /briefing/today`·`GET /notifications` 실제 호출 확인(실사 필요 6건, 알림 2건)

## 남은 일·확인 필요

- 회사별 `notify.briefing_time` 반영
- order-check 배치 머지 후 미입고 확인 건 추가
