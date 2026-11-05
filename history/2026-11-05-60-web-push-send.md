# 웹 푸시 발송

- 날짜: 2026-11-05
- 영역: server
- 관련: #184, F-NOTI-04, NOT-04

## 목적

- 구독(PR #234) 위에 `push` 채널 알림 발송과 만료 구독 정리 추가

## 한 일

- `notify/push.py`: 발송 대상 선택(`SKIP LOCKED`), 구독별 발송, 404·410 구독 삭제, `pushed_at` 기록, 커밋 후 백그라운드 발송
- `notify/service.py`: 지금 보낼 수 있는 `push` 알림은 커밋 직후 발송 예약
- `jobs/push.py`, 스케줄 10분마다: 조용한 시간으로 미룬 알림 발송
- 마이그레이션 `notifications.pushed_at`, 의존성 `pywebpush`
- 테스트 `test_push_send.py` 7개(가짜 푸시 서버), 문서 `notifications.md`·`jobs.md`

## 결정과 근거

- 한 번만 시도(재시도 없음): 명세에 재시도 규칙이 없고, 앱 안 알림·브리핑이 대체 경로(F-NOTI-04)
- 미룬 알림 발송 주기 10분은 이 레포에서 정함

## 검증

- 로컬 PostgreSQL 16 `REQUIRE_DB_TESTS=1 make test` 890개 통과(PDF 모듈 1개는 macOS `make` 환경에서 건너뜀), `make lint` 통과

## 남은 일·확인 필요

- 실제 브라우저 푸시 서비스(FCM·Apple)로 발송은 미검증(VAPID 키·HTTPS 배포 필요)
