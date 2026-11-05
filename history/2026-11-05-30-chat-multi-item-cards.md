# 채팅 여러 품목 확인 카드

- 날짜: 2026-11-05
- 영역: server
- 관련: Issue #192, F-CHAT-01, CHAT-01

## 목적

- ai 해석의 여러 품목(`items`)을 첫 품목만 쓰던 제약 해소

## 한 일

- `Interpretation.more`에 두 번째 품목부터 담도록 `AiInterpreter` 수정
- `chat/intents/record.py`에서 `OUT`·`IN` 품목마다 카드 생성, 답변은 줄바꿈으로 연결
- `docs/api-spec/chat.md`, `docs/ai-integration.md` 갱신

## 결정과 근거

- 카드는 품목마다 따로 확정·취소(CHAT-03·04 변경 없음)
- `QUERY` 등 다른 의도는 첫 품목만 사용

## 검증

- `REQUIRE_DB_TESTS=1 make test` 556개 통과(여러 품목 테스트 2개 포함)
- `make lint` 통과

## 남은 일·확인 필요

- 선행 PR #178(#174) 머지 후 머지
- 클라이언트의 여러 카드 표시는 미검증
