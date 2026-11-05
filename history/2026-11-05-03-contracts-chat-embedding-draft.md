# 채팅 해석·임베딩 계약 스키마 초안

- 날짜: 2026-11-05
- 영역: AI (contracts)
- 관련: Issue #61, 브랜치 `feat/ai-contracts-chat-embedding/#61`(dev 기준), F-CHAT-01, F-SETUP-02, F-MATCH-01, CHAT-01, API 명세서 1-6, `llm_calls`

## 목적

- server ↔ ai 사이 채팅 해석과 부품 이름 임베딩 요청·응답 스키마 초안을 `packages/contracts`에 정의
- 임베딩 차원 1536 반영(사용자 결정)

## 한 일

- `packages/contracts/src/bjk_contracts/common.py`: `AiMeta`(API 응답 `ai` 객체와 같은 모양), `FallbackReason`, `LlmPurpose`, `LlmUsage`
- `packages/contracts/src/bjk_contracts/chat.py`: `ChatIntent`, `ChatParseRequest`(500자 상한), `ParsedItem`, `ChatParseResponse`
- `packages/contracts/src/bjk_contracts/embedding.py`: `EMBEDDING_DIM = 1536`, `EmbedTask`(`document`/`query`), `EmbedRequest`, `EmbedResponse`
- `packages/contracts/src/bjk_contracts/__init__.py`: 위 타입 공개
- `apps/ai/tests/test_contracts.py`: 계약 검증 테스트 8건
- 아직 엔드포인트·Gemini 호출 코드 없음. 계약만 정의

## 결정과 근거

- **intent는 메시지 단위, 품목은 `items` 배열:** CHAT-01 응답의 `intent`가 메시지 단위이고, F-CHAT-01이 여러 품목을 items 배열로 받도록 정함
- **ai는 표현만 뽑음:** `part_text`·`equipment_text`·`supplier_text`는 원문 그대로. ID 변환(매칭), "저번 데" 해석, 되묻기는 server 몫(F-CHAT-01, F-MATCH-01). 명세 필드명 `equipment`는 원문 표현임을 드러내려고 `equipment_text`로 씀
- **단위는 원문 그대로:** 박스 → 개 환산에는 부품의 입수량이 필요하고, 입수량은 매칭 뒤에야 알 수 있어 server가 정규화
- **재시도는 ai 안에서 1회:** F-CHAT-01 "1회 재시도 후 폼 입력". 실패 응답은 `intent=None`, `items=[]`, `ai.fallback=True`로 고정해 server가 폼 카드로 넘기기 쉽게 함
- **토큰 기록은 응답의 `usage`로 전달:** `llm_calls` 테이블은 server DB에 있으므로 ai는 기록할 값만 돌려줌. 재시도를 합친 값이며 `attempts`로 횟수 표시
- **회사별 일일 토큰 상한은 server가 판단:** 합계를 아는 쪽이 server(`llm_calls`). 상한을 넘으면 server가 ai를 부르지 않고 `quota_exceeded`로 대체
- **임베딩 용도 `document`/`query` 분리:** 등록하는 부품 이름(저장용)과 채팅에서 찾는 표현(검색용)을 나눔. Gemini 임베딩이 작업 유형을 받으므로 구현 때 이 값으로 연결 예정
- **임베딩 응답에 `model` 포함:** 모델이 바뀌면 이전 벡터와 비교할 수 없어 server가 벡터와 함께 저장해야 함
- **벡터는 L2 정규화해서 돌려줌:** 3072가 아닌 차원으로 줄인 Gemini 임베딩은 정규화가 필요하다고 알고 있음. 구현 때 Gemini 문서로 확인
- **상한값 `EMBED_MAX_TEXTS = 100`, `EMBED_TEXT_MAX_LEN = 500`:** 명세에 없는 초깃값. 엑셀 이관 때 줄을 묶어 보내려고 정함. Gemini 배치 한도는 구현 때 확인
- 계약 테스트는 루트 `pyproject.toml`의 `testpaths`를 바꾸지 않으려고 `apps/ai/tests`에 둠

## 검증

- `make install` 성공
- `make test`: 10개 통과(이번에 추가한 계약 테스트 8개 포함)
- `make lint`: ruff check·format 통과
- server 쪽 사용 여부, Gemini 실제 호출은 미검증(아직 구현 없음)

## 남은 일·확인 필요

- **server 담당과 계약 합의:** dev-harness §0에 따라 계약 변경은 확인 대상. 특히 `equipment_text` 이름, `usage` 전달 방식, 상한 판단을 server가 하는 것
- **pgvector 열:** `parts`·`part_aliases`의 임베딩 열을 `vector(1536)`로, 모델명 열을 함께 두도록 server 스키마(`chore/db-schema-migration/#9`)에 요청 필요
- **커밋·브랜치:** Issue #61 생성, `dev` 기준 브랜치 `feat/ai-contracts-chat-embedding/#61`에 커밋(별도 worktree `../BJK-AI-BE-ai-contracts-61`). 원래 폴더 main에는 다른 작업(`about_project/` staged)이 있어 건드리지 않음. push·PR은 아직 안 함
- `dev`에는 아직 `about_project/`가 없음. 규칙 문서·기록이 가리키는 명세 경로는 해당 폴더가 dev에 들어오면 유효
- 다음 작업 후보: `apps/ai`에 Gemini 클라이언트와 `/chat/parse`·`/embed` 엔드포인트 구현, 시간 초과·재시도·대체 응답 테스트
