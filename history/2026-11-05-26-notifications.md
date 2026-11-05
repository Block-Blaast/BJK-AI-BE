# 알림 목록과 읽음 처리

- 날짜: 2026-11-05
- 영역: server
- 관련: #183, NOT-01·02, F-NOTI-01·03·04

## 목적

- 브리핑·검토·실사 알림을 저장하고 앱 안에서 보여 줄 공통 기반 마련

## 한 일

- `notifications` 테이블·RLS (마이그레이션 0021)
- `bjk_server/notify/service.py`: 받는 사람별 생성, `dedupe_key` 중복 방지, 조용한 시간 보류
- `api/notifications.py`: `GET /notifications`, `POST /notifications/{id}/read`
- `docs/api-spec/notifications.md`, `tests/test_notifications.py`

## 결정과 근거

- 조용한 시간 보류는 `sent_at`을 끝나는 시각으로 두고 목록에서 `sent_at <= now`만 보여 처리. 별도 발송 배치 없이 아침에 보임
- NOT-02 응답 본문은 명세에 없어 알림 한 개를 돌려줌
- 재알림(마감 2일 전)은 부르는 쪽이 다른 `dedupe_key`를 써서 표현

## 검증

- `REQUIRE_DB_TESTS=1 uv run pytest apps/server/tests/test_notifications.py`: 11개 통과
- `REQUIRE_DB_TESTS=1 make test`: 586개 통과, `make lint` 통과
- dev 반영 후 `REQUIRE_DB_TESTS=1 make test` 592개 통과, 마이그레이션 0021(dev 최신 0020 다음) 확인

## 남은 일·확인 필요

- 실제 알림 생성 지점(검토 완료·실사 요청·브리핑) 연결은 각 Issue에서
- 마이그레이션 번호 0021은 A의 #137 머지 순서에 따라 바뀔 수 있음
