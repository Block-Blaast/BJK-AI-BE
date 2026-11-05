# 배치 (HTTP API 아님)

API 명세서 14장 기준. 플랫폼 cron이 서버 이미지에서 CLI를 호출한다. 서버 프로세스 안에서 예약하지 않아 서버를 여러 대 띄워도 중복 실행되지 않는다.

```bash
python -m bjk_server.jobs nightly
```

| 이름 | 시각 (Asia/Seoul) | 구현 |
| --- | --- | --- |
| `nightly` | 매일 03:00 | 미구현 (근거 지표 계산 Issue) |
| `missed-scan` | 매일 07:00 | 미구현 |
| `order-check` | 매일 07:00 | 미구현 |
| `briefing` | 매일 07:30 | 미구현 |
| `weekly-merge` | 월요일 03:30 | 미구현 |

- 예약 예시: `infra/cron/crontab`
- 소유자 DB 계정(`ADMIN_DATABASE_URL`)으로 회사 전체를 대상으로 실행한다.
- 같은 작업은 advisory lock으로 한 번에 하나만 돈다. 겹치면 `skipped`(`already_running`)로 기록한다.
- 실패하면 작업 트랜잭션을 롤백하고 `job_runs`에 `error`로 남긴다. CLI 종료 코드 1.
- 실행 기록(`job_runs`)은 `GET /health`의 마지막 배치 상태에 쓴다.
