# Gemini 기반 채팅 해석·임베딩 ai 엔드포인트

- 날짜: 2026-11-05
- 영역: AI
- 관련: Issue #67, Draft PR #70(→ #61 브랜치), 브랜치 `feat/ai-gemini-chat-embedding/#67`(#61 브랜치 위에 쌓음), F-CHAT-01, F-SETUP-02, F-MATCH-01, 17장 비기능 요구사항

## 목적

- PR #63의 계약을 실제로 응답하는 `apps/ai` 엔드포인트 구현
- LLM 실패·시간 초과·API 키 미설정에서도 오류 대신 대체 응답

## 한 일

- 의존성: `apps/ai`에 `google-genai`(2.34.0), `pydantic-settings` 추가
- `apps/ai/src/bjk_ai/config.py`: API 키·모델 ID·시간 예산 설정. server의 `Settings` 방식(pydantic-settings, `get_settings` 캐시)을 따름
- `apps/ai/src/bjk_ai/gateway.py`: `LlmGateway` 프로토콜, `GeminiGateway`, 시간 예산 안 재시도 `call_with_retry`, `usage_from`
- `apps/ai/src/bjk_ai/chat.py`: 채팅 해석 시스템 프롬프트, Gemini 응답 스키마, 계약 변환
- `apps/ai/src/bjk_ai/embedding.py`: 용도별 입력 형식, 차원·개수 검사, L2 정규화
- `apps/ai/src/bjk_ai/main.py`: `POST /v1/chat/parse`, `POST /v1/embeddings`, `/health`에 `llm` 항목 추가
- `apps/ai/tests/test_app.py`: 가짜 게이트웨이로 정상·재시도·대체 경로 테스트
- `docs/ai-work-rules.md`: 실행 설정(환경 변수) 표 추가

## 결정과 근거

- **모델 기본값:** 채팅은 `gemini-3.5-flash-lite`(공식 모델 페이지 기준 stable, 저지연), 임베딩은 `gemini-embedding-2`(stable, 2026-04 갱신). 환경 변수로 바꿀 수 있음
- **스키마 강제는 Gemini 구조화 출력으로:** 명세의 "tool calling으로 스키마 강제"를 `response_mime_type="application/json"` + `response_schema`로 구현. 받은 JSON은 다시 pydantic으로 검증하고, 실패하면 `schema_invalid`
- **LLM용 스키마와 계약 분리:** Gemini에 넘기는 `_LlmOutput`은 제약 없는 단순 타입으로 두고, 받은 뒤 계약 `ParsedItem`(qty ≥ 0 등)으로 검증. Gemini 스키마 변환에서 제약 표현이 문제 되지 않게 하기 위함
- **재시도는 시간 예산 안에서:** 채팅은 확인 카드까지 3초(17장). 재시도까지 합쳐 2.5초 예산을 나눠 쓰고, 남은 시간이 없으면 `timeout`으로 대체
- **문자열 정리:** 앞뒤 공백 제거, 빈 문자열은 null. `OTHER`면 품목을 비움(계약 설명과 일치)
- **API 키 미설정:** Gemini를 부르지 않고 `ai: {used: false, fallback: true, reason: "error"}`, `usage: null`
- **임베딩은 텍스트마다 `Content`로 나눠 요청:** Gemini 문서상 `gemini-embedding-2`는 문자열 목록을 벡터 하나로 합침. 텍스트별 벡터를 받기 위함
- **용도는 입력 앞의 작업 지시로 전달:** `gemini-embedding-2`는 `task_type`을 쓸 수 없음. 문서의 형식대로 저장용 `title: none | text: …`, 검색용 `task: search result | query: …`
- **정규화를 한 번 더 함:** `gemini-embedding-2`는 1536차원도 정규화해 주지만, 모델을 `gemini-embedding-001`로 바꾸면 직접 정규화가 필요. 영벡터는 `schema_invalid`
- **제공자 오류 로그는 예외 종류만:** 오류 메시지에 요청 내용이 섞일 수 있어 남기지 않음
- **경로 `/v1/...`:** ai 내부 API 버전 표시. server 담당과 맞출 대상

## 검증

- `uv run pytest`: 25개 통과(ai 24개, server 1개)
- `uv run ruff check .`, `uv run ruff format --check .`: 통과
- **실제 Gemini 호출은 미검증:** 이 환경에 `GEMINI_API_KEY` 없음. 모델 ID, 구조화 출력 스키마 변환, 응답 지연(2.5초 예산 안에 드는지)은 키를 넣고 확인 필요

## 남은 일·확인 필요

- 실제 키로 확인: `GEMINI_API_KEY=... make ai` 후 `/v1/chat/parse`, `/v1/embeddings` 호출. 지연이 길면 `thinking_config`(생각 수준 낮추기) 검토
- `compose.yaml`의 `ai` 서비스에 `GEMINI_API_KEY` 전달 추가 필요. server 스택이 같은 파일을 고치는 중이라 이번 PR에서는 건드리지 않음
- server의 `bjk_server.chat.interpreter`는 현재 품목 하나(`Interpretation`)만 받음. ai는 `items` 배열로 주므로 server 연동 때 여러 품목 처리 합의 필요
- 회사별 일일 토큰 상한은 server 몫(`2026-11-05-03` 기록). ai는 `usage`만 돌려줌
- 참고 문서: [Gemini 모델](https://ai.google.dev/gemini-api/docs/models), [Gemini 임베딩](https://ai.google.dev/gemini-api/docs/embeddings), [gemini-embedding-2](https://ai.google.dev/gemini-api/docs/models/gemini-embedding-2)
