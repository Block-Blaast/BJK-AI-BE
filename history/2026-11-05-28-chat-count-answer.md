# 채팅 실사 응답 의도 연결

- 날짜: 2026-11-05
- 영역: server
- 관련: Issue #179, F-CHAT-05, CHAT-01, AUD-03

## 목적

- 채팅 "세어보니 940개"를 실사 응답(AUD-03)과 같은 처리로 연결

## 한 일

- `chat/intents/count.py` 추가, `HANDLERS`에 `COUNT` 등록
- 담당자 본인에게 전달된 응답 대기 요청 조회, 여럿이면 부품 표현으로 특정
- `MessageResponse.count_request_id` 추가(사유 입력 AUD-04용)
- `docs/api-spec/chat.md`, `docs/api-spec/audit.md` 갱신

## 결정과 근거

- 명세(F-CHAT-05, AUD-03)상 확인 카드 없이 바로 실사조정, 응답 후에만 차이 표시
- 사유 입력에 실사 요청 ID가 필요해 응답에 `count_request_id`를 더함(추가 필드, 기존 응답 호환)
- 박스 단위는 입수량으로 환산

## 검증

- `REQUIRE_DB_TESTS=1 make test` 558개 통과(채팅 실사 테스트 4개 포함)
- `make lint` 통과

## 남은 일·확인 필요

- 선행 PR #178(#174) 머지 후 머지
- 웹·앱 클라이언트의 `count_request_id` 사용은 미검증
