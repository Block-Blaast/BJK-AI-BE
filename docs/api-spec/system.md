# 설정·시스템 API

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
| `db` | `ok`, `error` (연결 실패 시 503, 나머지 항목은 `null`) |
| `llm` | ai `/health`의 `llm` 값(`ok`, `not_configured`). `AI_BASE_URL` 미설정이면 `not_configured`, ai에 연결하지 못하면 `error` |
| `last_batch` | 마지막 nightly 실행의 종료 시각과 상태(`ok`, `error`, `skipped`). 실행 기록이 없으면 둘 다 `null` |
| `external_indicators` | 외부 지표 마지막 갱신 시각, 24시간 넘게 갱신되지 않았거나 지표가 없으면 `stale: true` |

- ai 연결 점검은 1초 안에 끝낸다. `error`는 API 명세서에 없는 값으로 이 레포에서 더했다.
