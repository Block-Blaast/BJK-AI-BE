# LLM 사용처 안내 문구 정리

- 날짜: 2026-11-05
- 영역: server
- 관련: #170, #21, #22, #154, #83

## 목적

- 에이전트 안내 문서의 LLM 사용처를 실제 `apps/ai` 엔드포인트에 맞춘다
- `2026-11-05-07-server-todo.md`의 이미 끝난 항목을 바로잡는다

## 한 일

- `CLAUDE.md`·`AGENTS.md`: `apps/ai` 설명과 설계 원칙의 "별칭 후보 순위, 리포트 설명 문장 세 곳"을 채팅 해석·검토 의견서 문장·엑셀 이관 제안·부품 이름 임베딩 네 곳으로 수정
- `docs/work-areas.md`: `area:ai` 설명과 개발 경계 문구 같은 내용으로 수정
- `apps/server/src/bjk_server/chat/matching.py` 독스트링: dev 기준 옛 문구 없음 확인, 변경 없음

## 결정과 근거

- 호출 지점은 `apps/ai/src/bjk_ai/main.py`의 `/v1/chat/parse`, `/v1/opinions`, `/v1/imports/suggest`, `/v1/embeddings` 기준
- 매칭 순위는 LLM이 매기지 않음(F-MATCH-01, #21 종료, `docs/ai-work-rules.md` 2장)
- "리포트 설명 문장"은 현재 ai 엔드포인트가 없어 호출 지점에서 제외

## `2026-11-05-07-server-todo.md` 정정

- 1번 스택 머지 방식: PR #84로 dev에 한 번에 반영 완료(2026-11-05)
- 3번 `QUERY` 소진 예상일: 구현 완료(#22 체크리스트)
- 21~23번 ai 연동(채팅 해석 클라이언트, 임베딩·RRF·코사인 확정, `/health`의 `llm`): #154로 완료
- 30번 `rate_limits` 정리 배치: 별도 Issue로 진행

## 검증

- `grep -rn "별칭 후보 순위"`: 수정 대상 세 문서에서 없음 확인
- 문서 변경만 있어 테스트 대상 아님

## 남은 일·확인 필요

- `docs/ai-work-rules.md` 55줄, `docs/ai-integration.md` 16줄, `docs/api-spec/chat.md` 73줄에 옛 문구를 설명하는 문장이 남음. 다른 영역 문서라 담당자 확인 후 정리
