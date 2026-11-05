# 알림 (NOT)

API 명세서 11장, 기능명세서 F-NOTI-01·03·04 기준.

## NOT-01 `GET /notifications`

- 권한: 로그인한 모든 역할. 자기 알림만 본다.
- 쿼리: `cursor`, `limit` (common.md 목록 규칙). 정렬은 `sent_at` 최신 순.
- `sent_at`이 지난 알림만 보인다. 조용한 시간에 생긴 알림은 끝나는 시각까지 보이지 않는다.
- 응답: `{"items":[{"id","kind","target":{"type","id"}|null,"title","channels","read","sent_at"}],"unread":1,"next_cursor":null}`. `unread`는 보이는 알림 중 읽지 않은 수.

## NOT-02 `POST /notifications/{id}/read`

- 응답: 200, 읽음 처리한 알림 한 개(NOT-01 `items` 원소와 같은 형식). 명세에 응답 본문이 없어 정한 형식이다.
- 이미 읽은 알림은 처음 읽은 시각을 유지한다. 없거나 다른 사람 알림은 404 `NOT_FOUND`.

## 알림 만들기 (`bjk_server.notify.service.notify`)

- `kind`: `review_completed`, `review_urgent`, `briefing`, `decision_result`, `order_check`, `receipt_check`, `count_request`, `maintenance_check`.
- 받는 사람마다 `notifications` 한 줄. 같은 `dedupe_key`는 사용자마다 한 번만 만든다. 마감 2일 전 재알림은 다른 키를 쓴다.
- 조용한 시간(`notify.quiet_hours`, 기본 21:00~07:00, Asia/Seoul)에 생기면 긴급 건도 `sent_at`을 끝나는 시각으로 미룬다.
- 웹 푸시 발송은 NOT-04(#184)에서 붙인다.
