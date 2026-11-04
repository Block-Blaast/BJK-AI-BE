# 인증 API

토큰 형식과 역할 규칙은 [common.md](common.md#인증과-회사-격리) 참고.

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
