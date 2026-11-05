# server ↔ ai 채팅 해석·임베딩 연동

- 날짜: 2026-11-05
- 영역: AI·server
- 관련: Issue #154, F-CHAT-01, F-MATCH-01, F-SETUP-02 5단계, CHAT-01, SET-05, SYS-02, `2026-11-05-17-ai-stack-merge.md`

## 목적

- dev 머지 뒤에도 server가 ai를 부르지 않아 채팅 해석·임베딩이 늘 대체 경로로 동작하던 상태 해소
- `docs/ai-integration.md` 6장 1~3단계 구현

## 한 일

- 연결 공통: `AI_BASE_URL` 설정, `httpx` 런타임 의존성, `bjk_server/ai/client.py`(HTTP 실패 → `timeout`·`error`, 계약과 다른 응답 → `schema_invalid`), compose server·scheduler에 `AI_BASE_URL`
- `llm_calls` 테이블·RLS(마이그레이션 0018), 응답 `usage`를 한 줄씩 기록(`bjk_server/ai/usage.py`)
- SYS-02 `llm`: ai `/health` 값을 그대로, 연결 실패면 `error`
- 채팅: `AiInterpreter`가 `/v1/chat/parse`를 불러 첫 품목을 `Interpretation`으로 바꿈. 박스 단위는 부품 입수량을 곱함(입수량 없으면 수량을 비워 되물음)
- 임베딩: 열을 `vector(1024)`로(마이그레이션 0019, 기존 벡터 지움), 부품 등록·이름 변경 때 저장, nightly가 빈 부품·별칭 임베딩을 채움
- 매칭: 의미 유사도 상위 10개(같은 모델, 모호 별칭 제외) + 철자 순위를 RRF로 결합, 코사인 확정(`system.match_confirm_cosine`·`match_confirm_gap`), 후보 `reason: semantic`

## 결정과 근거

- 채팅 중 검색용 임베딩은 2초만 기다린다. 채팅 응답 3초 목표(비기능 요구사항) 때문. 실패하면 규격·철자 매칭만 한다
- 철자 기준에 들지 않은 의미 유사 후보는 코사인 0.5 이상만 넣는다. 명세에 기준이 없어 정한 초깃값이다. 없으면 상위 10개가 늘 후보가 되어 미등록 카드가 나오지 않는다
- RRF 상수 k = 60(표준값). 명세는 "RRF로 합산"만 정함
- 규격 일치 후보를 먼저 두는 기존 순서를 유지한다. 규격이 다른 부품은 의미가 가까워도 후보에서 뺀다(F-MATCH-01 금지 규칙)
- SYS-02 `llm`의 `error` 값은 API 명세서에 없다(명세는 예시 `ok`만). 연결 실패를 `not_configured`로 보이면 설정 문제와 구분되지 않아 더했다
- 등록 때 임베딩이 실패해도 등록은 성공시키고 nightly가 다시 채운다. 별칭 임베딩은 nightly에서만 만든다(확인 카드 응답을 늦추지 않으려고)

## 검증

- `REQUIRE_DB_TESTS=1 uv run pytest`: 552개 통과. 새 테스트 43개(ai 클라이언트·어댑터·단위 환산 22개, 의미 매칭 7개, DB 연동 12개, 상태 확인 2개)
- `ruff check`, `ruff format --check` 통과
- 빈 DB `alembic upgrade head` → `alembic check` 차이 없음 → `downgrade base` → `upgrade head` 통과
- 이 브랜치 server(:8010) → 이 브랜치 ai(:8011, LLM 미설정) 실제 HTTP: `/health` `not_configured` 전달, `/v1/chat/parse`·`/v1/embeddings` 200 대체 응답으로 폼 카드·빈 임베딩 확인
- 미검증: Bedrock 실제 호출(로컬 자격 증명 없음), 실제 Titan 벡터에서 코사인 기준 0.5·0.85의 적절성

## 남은 일·확인 필요

- 검토 흐름 연동(`bjk-review`, `collect_snapshot`, `review_requests`, REV API)
- 회사별 일일 토큰 상한: API 명세서 1-5에 있으나 SYS-01 설정 키가 없음. 키 이름·기본값 확인 필요
- 여러 품목 채팅 카드, 엑셀 이관 제안(`/v1/imports/suggest`) 연결
- 의미 유사 후보 기준 0.5와 SYS-02 `llm: error`를 명세에 반영할지 팀 확인
