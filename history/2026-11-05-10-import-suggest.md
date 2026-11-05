# 엑셀 이관 규격 추출·카테고리 제안

- 날짜: 2026-11-05
- 영역: AI (contracts 포함)
- 관련: Issue #81, 브랜치 `feat/ai-import-suggest/#81`(#79 브랜치 위에 쌓음), F-SETUP-01·02, SET-01

## 목적

- MVP LLM 사용처 중 마지막 하나(F-SETUP-02) 구현: 엑셀 줄마다 부품 이름에서 규격을 뽑고 등록 카테고리 중 하나를 확신도와 함께 제안

## 한 일

- `packages/contracts/src/bjk_contracts/import_suggest.py`: `SPEC_KEYS`(규격 키와 설명), `CategoryOption`, `ImportRow`, `ImportSuggestRequest`(최대 200줄, row 번호 중복 금지), `RowSuggestion`(모르는 규격 키 거부), `ImportSuggestResponse`
- `apps/ai/src/bjk_ai/import_suggest.py`: 시스템 프롬프트, Gemini 응답 스키마(규격 키는 열거형), 규격 값 정규화, 50줄 묶음 동시 호출
- `apps/ai/src/bjk_ai/main.py`: `POST /v1/imports/suggest`
- `apps/ai/src/bjk_ai/config.py`: `gemini_import_model`, `import_budget_seconds`(30초)
- `apps/ai/tests/test_import_suggest.py`: 정상, 목록 밖 카테고리, 모르는 규격 키, 줄 누락 재시도, 묶음 나눔·순서, 한 묶음 실패, 키 미설정, row 중복
- `docs/ai-work-rules.md` 실행 설정 표에 두 항목 추가

## 결정과 근거

- **규격 키는 server와 같게:** server 매칭(`bjk_server.domain.matching`의 `_SPEC_PATTERNS`, `feat/health-status/#53` 기준)과 시드의 `parts.spec` 키(`bearing_no`, `shield`, `thread`, `length_mm`, `type`, `length`, `size`, `volume_l`). 규격 필터(F-MATCH-01 3단계)가 같은 키로 비교하기 때문. 계약에 `SPEC_KEYS`로 두어 server도 같은 목록을 쓸 수 있게 함
- **값 정규화도 server와 같게:** 공백·하이픈 제거, 대문자("P-20" → "P20", "m8" → "M8")
- **카테고리는 목록 안에서만:** 목록 밖 id는 버리고 `category_id: null`, 확신도 0. 명세 "제안은 등록된 카테고리 목록 안에서만"
- **확신도는 LLM이 매긴 값:** 화면에서 낮은 줄을 위로 올리는 정렬용. 판정에는 쓰지 않음
- **50줄 묶음 동시 호출, 하나라도 실패하면 전체 대체:** 줄마다 출처(LLM·정규식)가 섞이면 관리자가 어느 줄을 더 봐야 할지 헷갈림. 실패 시 server는 정규식 규격만, 카테고리는 직접 선택(F-SETUP-02 3번)
- **줄 누락·중복이면 재시도:** 응답 줄 집합이 요청과 다르면 `schema_invalid`
- **규격 병합은 server 몫:** ai는 LLM 규격만 돌려줌. server의 정규식 규격과 합칠지·어긋나면 어떻게 할지는 server와 맞출 대상

## 검증

- `uv run pytest`: 120개 통과(이관 제안 8개 추가). `ruff check`, `ruff format --check` 통과
- **실제 Gemini(13줄, 1회 시도, 1.8초, 입력 947·출력 477 토큰):**
  - 시드 6종: 규격·카테고리 모두 시드와 같음(오링 제외)
  - 변형: "헥사볼트 M8×20" → M8·20, "베어링 6205 2RS" → 6205·2RS, "6204ZZ 베어링(NSK)" → 6204·ZZ, "V-벨트 B53" → B·53, "M10 너트" → M10, 볼트·너트
  - "작업용 장갑" → 카테고리 없음·확신도 0, "그리스 400g" → 절삭유·윤활유 0.6
  - "오링 P-20" → 규격 P20, 카테고리 없음. 시드는 오링을 볼트·너트로 둠. 목록에 맞는 카테고리가 없어 비운 것으로 보이며, 관리자가 고를 줄로 위에 올라감

## 남은 일·확인 필요

- server 연동: SET-01에서 줄과 등록 카테고리를 보내고, 실패 시 정규식 규격 + `suggested_category: null`
- 규격 병합 규칙(LLM 규격과 정규식 규격이 다를 때) server 담당과 합의
- 이것으로 MVP LLM 사용처 3곳(채팅 해석, 이관 제안, 의견서)과 임베딩, 검토 엔진 구현 완료. 남은 것은 server 연동 합의와 PR 머지
