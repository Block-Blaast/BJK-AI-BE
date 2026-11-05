# 공통 규칙

Notion API 명세서 1장 기준.

## Base URL

- 모든 기능 API는 `/api/v1` 아래에 둔다 (`bjk_server.api.api_router`).

## 오류 형식

모든 오류는 한 가지 형식으로 응답한다 (`bjk_server.errors`).

```json
{ "code": "REVIEW_NOT_DECIDABLE", "message": "검토가 끝난 건만 결정할 수 있습니다.", "detail": { "status": "held" } }
```

- `ApiError(code, message, detail, headers)`로 던지면 코드별 HTTP 상태로 변환한다.
- 요청 형식 오류는 400 `VALIDATION_ERROR`, `detail.errors`에 위치(`loc`)와 사유를 담는다.
- 없는 경로는 404 `NOT_FOUND`.

| HTTP | code |
| --- | --- |
| 400 | `VALIDATION_ERROR` |
| 401 | `UNAUTHORIZED`, `INVALID_CREDENTIALS`, `INVALID_PIN` |
| 403 | `FORBIDDEN_ROLE`, `SELF_APPROVAL_NOT_ALLOWED` |
| 404 | `NOT_FOUND` |
| 409 | `EMAIL_TAKEN`, `NAME_TAKEN`, `ALREADY_CONFIRMED`, `REVIEW_ALREADY_DECIDED`, `REVIEW_NOT_DECIDABLE`, `SNAPSHOT_REFRESHED`, `ORDER_STATE_CONFLICT`, `PDF_NOT_READY` |
| 410 | `ENTRY_EXPIRED`, `INVITE_EXPIRED` |
| 422 | `REASON_REQUIRED`, `PART_NOT_RESOLVED` |
| 423 | `PIN_LOCKED` |
| 429 | `RATE_LIMITED` (`Retry-After` 헤더) |

## 목록과 커서

- 응답: `{ "items": [...], "next_cursor": "..." }`. 마지막 페이지면 `next_cursor`는 `null`.
- 쿼리: `?cursor=&limit=`. `limit` 기본 20, 최대 100. 범위 밖이면 400 `VALIDATION_ERROR`.
- 커서는 정렬 키 값을 담은 불투명 문자열이다. 잘못된 커서는 400.

## 멱등성

- 채팅·폼 입력은 본문 `client_message_id`, 검토 결정은 `Idempotency-Key` 헤더를 키로 쓴다.
- 키는 회사·용도(`scope`)별로 유일하다. 같은 키로 다시 보내면 처음 응답을 그대로 돌려준다.
- 동시에 같은 키가 들어오면 뒤 요청은 앞 요청의 트랜잭션이 끝날 때까지 기다린 뒤 저장된 응답을 받는다.

## 인증과 회사 격리

- 헤더: `Authorization: Bearer {access_token}`. 액세스 토큰 15분, 리프레시 토큰 14일 (HS256).
- 클레임: `user_id`, `company_id`, `role`(`worker`, `manager`, `owner`), `type`(`access`, `refresh`), `jti`.
- 토큰 없음·만료·위조·리프레시 토큰 사용은 401 `UNAUTHORIZED`.
- 역할은 `worker < manager < owner` 순서. `require_role("manager")`는 manager·owner만 통과, 부족하면 403 `FORBIDDEN_ROLE`.
- 회사 격리는 PostgreSQL RLS로 한다. 요청 트랜잭션마다 `set_config('app.company_id', ..., true)`(SET LOCAL)를 실행하고, 정책이 `company_id = app_company_id()`인 행만 보이게 한다. 다른 회사 리소스는 보이지 않으므로 404가 된다.
- 앱은 `bjk_app` 역할에 속한 로그인 계정으로 접속한다. 테이블 소유자·superuser가 아니라 RLS를 우회하지 못하고, `movements`는 UPDATE·DELETE 권한이 없다.
- 운영(`APP_ENV`가 `dev`가 아님)에서는 32자 이상 `JWT_SECRET`이 없으면 서버가 시작하지 않는다.

## 호출 제한

- DB 고정 창 카운터(`rate_limits`)로 센다. 여러 서버 프로세스가 같은 횟수를 본다.
- 요청이 실패로 롤백돼도 횟수는 남는다(별도 트랜잭션).
- 초과 시 429 `RATE_LIMITED`, `Retry-After` 헤더는 현재 창이 끝날 때까지 남은 초.

## 기능명세서와 다르게 정한 것

| 항목 | 명세 | 구현 | 이유 |
| --- | --- | --- | --- |
| 회사 격리 | 테이블에 `FORCE ROW LEVEL SECURITY`를 걸어 소유자도 우회 못 하게 함 | 앱 요청과 배치는 소유자·superuser가 아닌 `bjk_app` 역할 계정으로 접속해 RLS를 우회하지 못함. 소유자 계정은 마이그레이션과 개발 환경 시드 초기화에만 씀 | `FORCE`를 걸면 로그인 전 조회 함수(SECURITY DEFINER)도 RLS에 막혀 BYPASSRLS 역할이 따로 필요하고, 관리형 PostgreSQL에서는 이 권한을 받기 어려움. 업무 코드가 RLS를 우회하지 못한다는 목적은 같게 지킴 |
| 비밀번호·PIN 해시 | bcrypt | argon2id (`argon2-cffi`) | OWASP 1순위 권장, 메모리 집약형이라 무차별 대입에 더 강함. 4자리 PIN의 실제 보호 수단은 5회 실패 10분 잠금 |

- 회사 목록이 필요한 곳(배치)은 `system_company_ids()`, 로그인 전 조회는 `auth_lookup_by_email()`·`auth_company_by_code()`로 ID만 받는다. 세 함수 모두 `bjk_app`에만 실행 권한을 준다.
