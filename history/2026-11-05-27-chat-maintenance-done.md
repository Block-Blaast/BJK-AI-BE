# 채팅 정비 완료 의도 연결

- 날짜: 2026-11-05
- 영역: server
- 관련: Issue #186, F-CHAT-06, CHAT-01, CHAT-03, SET-09

## 목적

- 채팅 "3호기 정비 끝"을 정비 완료(SET-09)로 연결

## 한 일

- `chat/intents/maintenance_done.py` 추가, `HANDLERS`에 `MAINTENANCE_DONE` 등록
- 카드에 `maintenance`(id, 예정일) 추가, CHAT-03 확정 시 정비 완료 처리
- `api/maintenance.py`에 SET-09와 공용인 `mark_completed` 분리
- `docs/api-spec/chat.md`, `docs/api-spec/master-data.md` 갱신

## 결정과 근거

- 명세 F-CHAT-06: 가장 가까운 미완료 정비를 확인 카드로 보여준 뒤 완료
- 가장 가까운 정비는 오늘(Asia/Seoul)과 예정일 차이 최소, 같으면 앞선 일정
- 완료 시각은 카드 확정 시각

## 검증

- `REQUIRE_DB_TESTS=1 make test` 558개 통과(채팅 정비 완료 테스트 4개 포함)
- `make lint` 통과

## 남은 일·확인 필요

- 선행 PR #178(#174) 머지 후 머지
- #179(COUNT)와 `chat/intents/__init__.py` 등록 표에서 충돌 예상, 양쪽 유지
