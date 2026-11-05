# 만료 행 정리 배치

- 날짜: 2026-11-05
- 영역: server
- 관련: #185, `history/2026-11-05-07-server-todo.md` 30번

## 목적

- `rate_limits`, `pin_attempts`, `idempotency_keys`에 만료 행이 계속 쌓이는 문제 해소

## 한 일

- `jobs/cleanup.py`: `cleanup` 배치. 테이블별 삭제 수를 요약으로 남김
- `jobs/runner.py` `JobName`, `jobs/registry.py`, `jobs/scheduler.py`(매일 04:00), `infra/cron/crontab`에 추가
- `docs/api-spec/jobs.md`, `docs/api-spec/dev.md`에 작업 이름 추가
- `tests/test_cleanup_job.py`: 만료·유지 경계 검증

## 결정과 근거

- 보관 기간은 명세에 없음. 2026-11-05 사용자 결정: `rate_limits` 창 종료 1시간 뒤, `pin_attempts` 잠금 해제와 마지막 실패 1일 뒤, `idempotency_keys` 7일 뒤
- `pin_attempts`·`idempotency_keys`는 RLS 대상이라 회사마다 `set_tenant` 뒤 삭제. `rate_limits`는 RLS 없음
- 04:00은 nightly(03:00)·weekly-merge(월 03:30)와 07:00 배치 사이

## 검증

- `REQUIRE_DB_TESTS=1 uv run pytest tests/test_cleanup_job.py tests/test_scheduler.py tests/test_jobs.py`: 22개 통과
- `REQUIRE_DB_TESTS=1 make test`: 555개 통과
- dev 반영 후 `REQUIRE_DB_TESTS=1 make test` 575개 통과
- `make lint` 통과

## 남은 일·확인 필요

- 운영 DB 행 수 기준 실행 시간 미측정
