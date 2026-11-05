# 웹 푸시 구독 (NOT-04)

API 명세서 11장 기준. Web Push(VAPID). 발송은 [notifications.md](notifications.md)의 웹 푸시 발송을 따른다.

## `GET /push/vapid-key`

- 로그인한 모든 역할. 브라우저 구독(`applicationServerKey`)에 쓰는 공개 키 `{"public_key": "..."}`. 설정(`VAPID_PUBLIC_KEY`)이 없으면 `null`.

## NOT-04 `POST /push/subscriptions`

- 요청: `{"endpoint":"https://...","keys":{"p256dh":"...","auth":"..."}}`. endpoint는 https만, `p256dh`는 1~200자, `auth`는 1~100자. 벗어나면 400 `VALIDATION_ERROR`.
- 응답: 201 `{"id","endpoint","created_at"}`(명세에 응답 본문이 없어 정한 형식).
- 같은 회사에서 같은 endpoint를 다시 등록하면 새 행을 만들지 않고 키와 사용자를 바꾼다(기기를 다른 직원이 쓰는 경우).

## `GET /push/subscriptions`, `DELETE /push/subscriptions/{id}`

- 내 구독 목록(최근 순, 커서 없이 배열), 내 구독 해지(204). 남의 구독은 404. 명세 밖 추가 API.
