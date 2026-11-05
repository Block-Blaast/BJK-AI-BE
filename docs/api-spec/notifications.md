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

## 웹 푸시 발송 (NOT-04, `bjk_server.notify.push`)

- 대상: `channels`에 `push`가 있고 보낼 시각(`sent_at`)이 지났으며 아직 보내지 않은(`pushed_at` 없음) 알림. 받는 사람의 모든 구독(`push_subscriptions`)으로 보낸다.
- 시점: 알림을 만든 트랜잭션이 커밋된 직후 백그라운드로 보낸다(롤백되면 보내지 않음). 조용한 시간으로 미룬 알림과 커밋 직후 발송이 돌지 못한 알림은 `push` 배치(10분마다)가 보낸다.
- 성공·실패와 관계없이 `pushed_at`을 남겨 한 번만 시도한다. 만료 응답(404·410)을 받은 구독은 지우고, 그 밖의 실패는 구독을 남긴다. 알림 목록(NOT-01)에는 그대로 보인다.
- 본문(JSON): `{"notification_id", "kind", "title", "target": {"type", "id"} | null}`.
- VAPID 개인 키(`VAPID_PRIVATE_KEY`)가 없으면 보내지 않는다. 발송은 `pywebpush`(VAPID, aes128gcm), 시간 제한 5초.
