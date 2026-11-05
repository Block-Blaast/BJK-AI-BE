# 인증 API

토큰 형식과 역할 규칙은 [common.md](common.md#인증과-회사-격리) 참고.

## AUTH-01 POST /api/v1/auth/owner/signup

- 권한: 공개. 사장님 가입과 회사 생성.
- 회사 코드(6자, 헷갈리는 글자 0·O·1·I·L 제외)를 새로 만들고, 기본 설정(SYS-01 기본값)과 기본 카테고리 4종(F-SETUP-03)을 함께 넣는다.
- 이메일은 앞뒤 공백을 지우고 소문자로 저장한다. 대소문자만 다른 이메일은 같은 이메일로 본다.
- 회사가 정해지기 전이라 새 회사 ID를 먼저 정해 트랜잭션의 회사로 지정한 뒤 RLS 안에서 넣는다.
- IP당 시간당 10회. 실패한 요청도 횟수에 포함한다.

```json
// Request
{ "company_name": "한서정밀", "name": "김사장", "email": "owner@hanseo.kr", "password": "********" }

// 201 Response
{
  "access_token": "eyJ...", "refresh_token": "eyJ...", "expires_in": 900,
  "user": { "id": "...", "name": "김사장", "role": "owner" },
  "company": { "id": "...", "name": "한서정밀", "code": "HS7F3K" }
}
```

| 상황 | 응답 |
| --- | --- |
| 비밀번호 8자 미만, 이메일 형식 오류, 빈 이름·회사 이름 | 400 `VALIDATION_ERROR` |
| 이미 가입된 이메일 (동시 가입 포함) | 409 `EMAIL_TAKEN` |
| 시간당 10회 초과 | 429 `RATE_LIMITED`, `Retry-After` 헤더 |

- 명세에 없어 정한 것: 가입 호출 제한(IP당 시간당 10회), 이메일 형식은 `@`와 도메인 점 포함 여부만 확인.

## AUTH-02 POST /api/v1/auth/login

- 권한: 공개. 사장님·관리자 이메일 로그인.
- 이메일은 앞뒤 공백을 지우고 대소문자를 구분하지 않는다.
- 로그인 전에는 회사를 알 수 없어 `auth_lookup_by_email` 함수(SECURITY DEFINER)가 사용자·회사 ID만 찾고, 사용자 조회와 비밀번호 검증은 그 회사의 RLS 안에서 한다.

```json
// Request
{ "email": "owner@hanseo.kr", "password": "********" }

// 200 Response
{ "access_token": "eyJ...", "refresh_token": "eyJ...", "expires_in": 900, "user": { "id": "...", "name": "김사장", "role": "owner" } }
```

| 상황 | 응답 |
| --- | --- |
| 없는 이메일, 비밀번호 불일치 | 401 `INVALID_CREDENTIALS` (둘을 구분하지 않음) |
| 필드 누락 | 400 `VALIDATION_ERROR` |

## AUTH-05 POST /api/v1/auth/refresh

- 권한: 리프레시 토큰.
- 액세스·리프레시 토큰을 모두 새로 발급한다. 역할은 토큰이 아니라 현재 사용자 정보로 정한다.
- 이전 리프레시 토큰은 폐기하지 않는다(명세에 회전 폐기 규정 없음). 만료(14일)까지 유효.

```json
// Request
{ "refresh_token": "eyJ..." }

// 200 Response
{ "access_token": "eyJ...", "refresh_token": "eyJ...", "expires_in": 900 }
```

| 상황 | 응답 |
| --- | --- |
| 만료·위조 토큰, 액세스 토큰 사용 | 401 `UNAUTHORIZED` |
| 비활성·없는 사용자 | 401 `UNAUTHORIZED` |

## AUTH-08 GET /api/v1/me

- 권한: 로그인한 모든 사용자.

```json
// 200 Response
{ "id": "...", "name": "김사장", "role": "owner", "company": { "id": "...", "name": "한서정밀", "code": "HS7F3K" } }
```

| 상황 | 응답 |
| --- | --- |
| 토큰 없음·만료 | 401 `UNAUTHORIZED` |
| 비활성·없는 사용자, 토큰의 회사와 사용자가 다름 | 401 `UNAUTHORIZED` |

## AUTH-03 GET /api/v1/auth/companies/{code}/members

- 권한: 회사 코드. 기기에 저장된 회사 코드로 PIN 로그인용 이름 목록을 받는다.
- PIN이 등록된 활성 사용자만, 이름순. `user_id`, `name` 외 정보는 주지 않는다.
- 회사 코드는 대소문자를 구분하지 않는다.
- IP당 분당 10회. 없는 회사 코드 조회도 횟수에 포함한다.

```json
// 200 Response
{ "items": [ { "user_id": "...", "name": "이현장" }, { "user_id": "...", "name": "박정비" } ] }
```

| 상황 | 응답 |
| --- | --- |
| 없는 회사 코드 | 404 `NOT_FOUND` |
| 분당 10회 초과 | 429 `RATE_LIMITED`, `Retry-After` 헤더, `detail.retry_after_seconds` |

## AUTH-04 POST /api/v1/auth/pin-login

- 권한: 공개. 같은 계정 5회 연속 실패 시 10분 잠금. 성공하면 연속 실패 횟수를 0으로 되돌린다.
- 실패 기록은 요청 트랜잭션과 따로 커밋해 오류 응답이어도 남는다.

```json
// Request
{ "company_code": "HS7F3K", "user_id": "...", "pin": "1234" }

// 200 Response
{ "access_token": "eyJ...", "refresh_token": "eyJ...", "expires_in": 900, "user": { "id": "...", "name": "이현장", "role": "worker" } }

// 401 Response
{ "code": "INVALID_PIN", "message": "PIN이 맞지 않습니다.", "detail": { "remaining_attempts": 2 } }

// 423 Response
{ "code": "PIN_LOCKED", "message": "10분 뒤 다시 시도하세요.", "detail": { "retry_after_seconds": 600 } }
```

| 상황 | 응답 |
| --- | --- |
| PIN 불일치 (1~4회째) | 401 `INVALID_PIN`, `remaining_attempts` |
| 5회째 실패, 잠금 중 요청 | 423 `PIN_LOCKED`, `Retry-After` 헤더 |
| 없는 회사 코드, 없는 사용자, PIN 미등록 사용자 | 404 `NOT_FOUND` |
