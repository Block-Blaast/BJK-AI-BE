# 오늘 활동 목록·채팅 인박스 API 추가

- 날짜: 2026-11-05
- 영역: server
- 관련: #275, W-01, M-02, F-AUDIT-06, F-CHAT-05, DSH-02

## 목적

- 프론트 목업에만 있던 `/api/activity/today`, `/api/chat/inbox`를 서버 API로 대체

## 한 일

- `GET /api/v1/activity/today`(manager 이상): 오늘 원장 기록·검토 생성·결정·실사 요청·실사 종료를 최신 순 한 줄 목록으로. 조회 시 계산, 최대 100개
- `GET /api/v1/chat/inbox`(로그인 사용자): 본인 담당 응답 대기 실사 요청. 장부 수량 없음
- `audit/counts.py`: 전달된 실사 요청 조회를 `delivered_requests`로 옮겨 채팅 `COUNT` 의도와 인박스가 함께 사용
- 테스트 `test_activity_inbox.py` 4개

## 결정과 근거

- 형식은 프론트 목업 타입(`Activity`, `ChatInboxItem`)을 따름. 인박스에는 `kind`, `count_request_id`를 더함
- 하루치·본인 대기분이라 커서 대신 `items`만 줌(활동은 최대 100개)
- 목업 인박스의 장부 수량 문구와 입고 검수 안내는 넣지 않음. 블라인드 실사(F-AUDIT-06)와 명세에 없는 안내라서
- 목업만 있는 나머지 API는 추가하지 않음
  - `POST /api/chat/drafts/{id}`: 명세는 출고 확정 때 서버가 초안을 자동으로 만들고(F-LEDGER-03) 확정 응답 `triggered.draft_review_id`로 알림. 작업자가 누르는 단계가 없음
  - `/api/twin/layout`, `/api/twin/projection`: 명세 밖 화면이고 현재 프론트가 호출하지 않음

## 남은 일·확인 필요

- 프론트 경로를 `/v1/activity/today`, `/v1/chat/inbox`로 바꾸고 `items`를 읽도록 수정
- 인박스가 시연 시드에서 비어 있음. 실사 요청을 보내야 항목이 생김
