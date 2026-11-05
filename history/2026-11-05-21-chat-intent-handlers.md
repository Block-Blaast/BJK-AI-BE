# 채팅 의도별 처리기 분리

- 날짜: 2026-11-05
- 영역: server
- 관련: Issue #174, CHAT-01

## 목적

- 의도 추가(COUNT·MAINTENANCE_DONE·PURCHASE_REQUEST) 전에 `chat/service.py` 분기 정리

## 한 일

- `chat/intents/base.py`: `IntentContext`(카드 저장 `add_entry` 포함), `IntentResult`
- `chat/intents/record.py`(OUT·IN), `chat/intents/query.py`(QUERY)로 분리
- `chat/intents/__init__.py`의 `HANDLERS` 표에 의도 한 줄씩 등록, 미등록 의도는 도움말 답변

## 결정과 근거

- 등록은 import 부수효과 없이 명시적 표로 관리
- 응답·저장 동작 변경 없음

## 검증

- `REQUIRE_DB_TESTS=1 make test` 554개 통과
- `make lint` 통과

## 남은 일·확인 필요

- 없음
