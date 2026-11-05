# 설정·시스템 API

## SYS-01 GET·PATCH /api/v1/settings

- 권한: owner. 다른 역할은 403 `FORBIDDEN_ROLE`.
- 설정은 사장님이 바꾸는 값(`notify`, `review`)과 시뮬레이션 결과로만 조정하는 시스템 값(`system`)으로 나뉜다.
- 설정 행이 없는 회사는 기본값(`bjk_server.defaults`)을 주고 `updated_at`은 `null`. 첫 PATCH 때 행을 만든다.

```json
// GET 200 Response
{
  "notify": { "quiet_hours": { "start": "21:00", "end": "07:00" }, "briefing_time": "07:30" },
  "review": { "service_level": { "A": 0.98, "B": 0.95, "C": 0.90 }, "next_order_weeks": 4, "c02_months": 12, "c05_sigma": 2, "c06_ratio": 0.9, "c08_days": 5 },
  "system": { "c05_min_ratio": 1.05, "c05_small_n_ratio": 1.15, "hidden_stock_count_days": 30, "review_expire_days": 7, "missed_p_out_min": 0.3, "match_confirm_cosine": 0.85, "match_confirm_gap": 0.05, "external_k": 0.25, "count_per_worker_per_day": 2, "count_suppress_days": 30, "llm_daily_tokens": 1000000 },
  "updated_at": "2026-11-04T09:00:00+09:00"
}

// PATCH Request (보낸 키만 바뀌고 나머지는 유지)
{ "notify": { "briefing_time": "07:00" }, "review": { "c08_days": 7 } }
```

| 키 | 허용 범위 |
| --- | --- |
| `notify.quiet_hours.start`, `end` | `HH:MM` |
| `notify.briefing_time` | 06:00~10:00 |
| `review.service_level.A`·`B`·`C` | 0.80~0.995 |
| `review.next_order_weeks` | 1~8 (정수) |
| `review.c02_months` | 3~24 (정수) |
| `review.c05_sigma` | 1~3 |
| `review.c06_ratio` | 0.5~0.95 |
| `review.c08_days` | 1~14 (정수) |

| 상황 | 응답 |
| --- | --- |
| `system` 키, 정의되지 않은 키, 허용 범위 밖 값, `null` 값 | 400 `VALIDATION_ERROR` |
| owner가 아닌 역할 | 403 `FORBIDDEN_ROLE` |

- 바꾼 값은 다음 검토·다음 배치부터 적용된다. nightly는 실행 시점의 `review`·`system` 값을 읽는다.

## SYS-02 GET /api/v1/health

- 권한: 공개. 회사 데이터는 담지 않는다.
- 기존 `/health`(Base URL 밖)는 제거했다.

```json
// 200 Response
{
  "db": "ok",
  "llm": "not_configured",
  "last_batch": { "nightly": "2026-11-04T03:04:12+09:00", "status": "ok" },
  "external_indicators": { "updated_at": "2026-11-04T03:00:40+09:00", "stale": false }
}
```

| 항목 | 값 |
| --- | --- |
| `db` | `ok`, `error` (연결 실패 시 503. `llm`은 그대로 채우고 `last_batch`·`external_indicators`는 `null`) |
| `llm` | ai `/health`의 `llm` 값(`ok`, `not_configured`). `AI_BASE_URL` 미설정이면 `not_configured`, ai에 연결하지 못하면 `error` |
| `last_batch` | 마지막 nightly 실행의 종료 시각과 상태(`ok`, `error`, `skipped`). 실행 기록이 없으면 둘 다 `null` |
| `external_indicators` | 외부 지표 마지막 갱신 시각, 24시간 넘게 갱신되지 않았거나 지표가 없으면 `stale: true` |

- ai 연결 점검은 1초 안에 끝낸다. `error`는 API 명세서에 없는 값으로 이 레포에서 더했다.
