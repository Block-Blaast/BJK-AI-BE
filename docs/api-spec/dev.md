# 개발·시연 API

`APP_ENV=dev`일 때만 라우트를 등록한다. 그 외 환경에서는 404 `NOT_FOUND`.

## DEV-03 POST /api/v1/dev/seed/reset

- 권한: owner
- 동작: 모든 앱 테이블을 비우고 시연 시드(`demo_v1`)를 다시 넣는다. 소유자 DB 계정(`ADMIN_DATABASE_URL`)으로 실행한다.
- 시드 ID가 고정이라 초기화 전에 받은 시연 계정 토큰을 그대로 쓸 수 있다.

```json
// Request
{ "scenario": "demo_v1" }

// 200 Response
{ "scenario": "demo_v1", "company_code": "HS7F3K", "reset_at": "2026-11-04T10:00:00+09:00" }
```

| 상황 | 응답 |
| --- | --- |
| 토큰 없음 | 401 `UNAUTHORIZED` |
| owner 아님 | 403 `FORBIDDEN_ROLE` |
| 없는 시나리오 | 400 `VALIDATION_ERROR` |
| 개발 환경 아님 | 404 `NOT_FOUND` |

## DEV-04 POST /api/v1/dev/impersonate

- 권한: owner
- 동작: 같은 회사에서 요청한 역할의 시연 계정 토큰을 발급한다. 시드 계정(owner·manager·worker)이 활성 상태면 그 계정, 아니면 그 역할로 가장 먼저 만든 활성 계정을 쓴다.

```json
// Request
{ "role": "worker" }

// 200 Response (AUTH-02와 같은 형식)
{ "access_token": "eyJ...", "refresh_token": "eyJ...", "expires_in": 900, "user": { "id": "...", "name": "이현장", "role": "worker" } }
```

| 상황 | 응답 |
| --- | --- |
| owner 아님 | 403 `FORBIDDEN_ROLE` |
| `worker`·`manager`·`owner` 외 값 | 400 `VALIDATION_ERROR` |
| 해당 역할 계정 없음 | 404 `NOT_FOUND` |
| 개발 환경 아님 | 404 `NOT_FOUND` |

## DEV-01 POST /api/v1/dev/jobs/{name}/run

- 권한: owner
- `{name}`: `nightly`, `missed-scan`, `order-check`, `briefing`, `weekly-merge`
- 동작: 배치를 즉시(동기) 실행하고 실행 기록(`job_runs`, `trigger: manual`)을 남긴다. 응답에 작업 요약을 펼쳐 담는다. 예약 실행과 같이 앱 계정으로 돈다.

```json
// 200 Response
{ "job": "nightly", "status": "ok", "started_at": "...", "finished_at": "...", "parts_computed": 6 }
```

| `status` | 뜻 |
| --- | --- |
| `ok` | 완료 |
| `skipped` | 미구현 작업(`reason: not_implemented`) 또는 같은 작업 실행 중(`reason: already_running`) |
| `error` | 실패. 작업 변경은 롤백되고 `error`에 사유 |

| 상황 | 응답 |
| --- | --- |
| 없는 작업 이름 | 400 `VALIDATION_ERROR` |
| owner 아님 | 403 `FORBIDDEN_ROLE` |
| 개발 환경 아님 | 404 `NOT_FOUND` |
