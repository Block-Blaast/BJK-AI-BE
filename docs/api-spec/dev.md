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
