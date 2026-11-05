# 발주 검토 의견서 문장 엔드포인트와 실제 Gemini 확인

- 날짜: 2026-11-05
- 영역: AI (contracts 포함)
- 관련: Issue #71, 브랜치 `feat/ai-review-opinion/#71`(#67 브랜치 위에 쌓음), F-REVIEW-05~10, REV-02

## 목적

- 의견서 문장(F-REVIEW-08)을 ai가 쓰는 계약과 엔드포인트 추가
- 사용자가 `.env`에 넣은 Gemini 키로 채팅 해석·임베딩·의견서를 실제 호출해 확인

## 한 일

- `packages/contracts/src/bjk_contracts/opinion.py`: `OpinionRequest`(판정·표시·보류 사유·체크와 근거 숫자·원안·수정안·대안·리스크·계산 방식·계산 시각·재작성용 `previous_text`/`feedback`), `OpinionResponse`
- `apps/ai/src/bjk_ai/opinion.py`: 시스템 프롬프트, LLM 출력 스키마, 의견서 조립
- `apps/ai/src/bjk_ai/main.py`: `POST /v1/opinions`
- `apps/ai/src/bjk_ai/config.py`: `gemini_opinion_model`, `opinion_budget_seconds`(3초)
- `apps/ai/src/bjk_ai/gateway.py`: 이벤트 루프가 바뀌면 Gemini 클라이언트 재생성, 출력 토큰에 생각 토큰 포함
- `apps/ai/tests/conftest.py`: 가짜 게이트웨이와 클라이언트를 픽스처로 옮김. `test_app.py`는 픽스처 사용으로 바꿈
- `apps/ai/tests/test_opinion.py`, `apps/ai/tests/test_gateway.py` 추가
- `docs/ai-work-rules.md`: 의견서 설정과 `.env` 위치 추가
- worktree 루트에 `.env` 생성(키 칸만, 커밋 안 됨). 사용자가 키를 넣음

## 결정과 근거

- **ai는 문장만, 검증은 server:** 숫자 허용 목록 대조·판정 일치·누락 검증은 `CLAUDE.md` 구조상 server 검증 엔진 몫. ai는 `feedback`(틀린 항목)과 `previous_text`를 받아 재작성만 함. 양식 의견서도 server 대체 경로
- **판정 머리와 계산 시각은 코드가 붙임:** `[수정 권고]`, `[적정 · 긴급]` 같은 머리와 `계산 기준: YYYY-MM-DD HH:MM`(서울 시각)은 입력값으로 직접 씀. 판정 일치 검증이 LLM 때문에 틀리지 않게 하기 위함
- **구성 순서도 코드가 맞춤:** LLM은 요약·체크별 문장·수정안·리스크·대안을 필드로 따로 주고, ai가 F-REVIEW-08 순서(체크는 긴급 → 경고 → 정보)로 묶음
- **누락·중복·없는 체크는 재시도:** 입력 체크와 LLM 체크 문장이 1:1이 아니면 `schema_invalid`로 다시 씀. 숫자 검증과 달리 구조 검사라 ai에서 함
- **입력에 없으면 버림:** 수정안이 없는 요청(보류 등)의 수정안 문장, 대안이 없는 요청의 대안 문장은 LLM이 써도 넣지 않음
- **추정치 표시:** `data_mode: estimated`면 "추정치 기반" 문장을 코드가 붙임(정보 부족 대응 표)
- **시간 예산 3초:** 검토 10초 안에 server가 최대 2번 재작성 요청할 수 있게 한 번 호출에 3초
- **Gemini 클라이언트 재생성:** SDK 비동기 연결이 처음 쓴 이벤트 루프에 묶여 루프가 바뀌면 `Event loop is closed`로 실패함(아래 검증에서 확인). uvicorn은 루프가 하나라 영향이 없지만, 루프가 바뀌는 환경에서 첫 시도를 매번 버리지 않게 루프별로 새로 만듦
- **계약 필드 중 명세에 세부 정의가 없는 것:** `Alternative.kind`(`cheaper_supplier`/`price_tier`), `Proposal.saving` 음수 = 추가 비용, `deadline` 기호. server 담당과 맞출 대상

## 검증

- `uv run pytest`: 35개 통과(ai 34개, server 1개). `ruff check`·`ruff format --check` 통과
- **실제 Gemini 호출(사용자 키, 모델 기본값):**
  - 채팅 해석 8문장(F-CHAT 예시 포함) 모두 의도·품목·수량·설비·공급사 표현·단가 기대대로 추출. "1만 8천원" → 18000, "볼트 200개, 너트 200개" → 품목 2개, "오늘 점심 뭐임" → `OTHER`
  - 채팅 지연 0.8~1.4초(예산 2.5초 안), 클라이언트 재생성 수정 후 모두 1회 시도로 성공
  - 임베딩 1536차원, 노름² 1.0000. 코사인: "육각볼트 M8-20" ↔ "헥사볼트 M8×20" 0.964, 볼트 ↔ "볼베어링 6205ZZ" 0.76. 검색용 "헥사 볼트 m8 20" → 볼트 두 개 0.86·0.87, 베어링 0.66
  - 의견서(F-REVIEW-10 V벨트 A-42) 1.4초. 입력에 있는 숫자만 쓰고 체크 5개 모두 언급, 머리 `[수정 권고]`, 끝줄 `계산 기준: 2026-11-04 03:00`
  - 수정 전에는 첫 호출 다음부터 매번 첫 시도가 `RuntimeError`(Event loop is closed)로 실패 후 재시도 성공. 원인 확인 후 수정
- 남은 경고: 루프가 바뀔 때 이전 클라이언트 정리에서 "Task exception was never retrieved" 로그가 남음. 요청 결과에는 영향 없음, uvicorn에서는 발생하지 않음

## 남은 일·확인 필요

- server 담당과 의견서 계약 합의(특히 `feedback` 재작성 방식, `Alternative`·`Risk` 필드)
- 숫자 검증기(server)가 ai 의견서의 숫자 표기("540,000원", "11월 8일", "1.5개", "20개월 치")를 정규화할 수 있는지 확인
- 엑셀 이관 규격·카테고리 제안(F-SETUP-02)이 남은 LLM 사용처
