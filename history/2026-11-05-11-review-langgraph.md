# 발주 검토 처리 단계 LangGraph 그래프

- 날짜: 2026-11-05
- 영역: AI (검토 엔진)
- 관련: Issue #85, 브랜치 `feat/review-langgraph/#85`(#81 브랜치 위에 쌓음), F-REVIEW-01, 2장 기술 스택, API 명세서 11장 SSE `review.progress`

## 바로잡기

- `2026-11-05-10-import-suggest.md`의 "MVP LLM 사용처 3곳과 임베딩, 검토 엔진 구현 완료"는 틀린 보고였음. 명세 F-REVIEW-01의 LangGraph 처리 단계(규칙 노드·LLM 노드 분리, 진행 단계 스트리밍)가 빠져 있었음. 판정 규칙과 의견서 함수만 보고 처리 흐름을 명세와 대조하지 않은 것이 원인. 사용자가 지적해 이번 작업에서 구현

## 목적

- 검토 처리 단계를 명세대로 LangGraph 그래프로 구성하고, 단계마다 SSE `review.progress`로 보낼 진행 단계를 내보냄

## 한 일

- 의존성: `bjk-review`에 `langgraph`(1.2.19) 추가
- `packages/review/src/bjk_review/engine.py`: `run_review`를 단계 함수(`hold_result`, `make_context`, `original_line`, `decide`)로 나눔. `run_review`는 이 함수들을 차례로 부르며 결과는 그대로
- `packages/review/src/bjk_review/graph.py`
  - 노드 8개: `interpret` → `snapshot` → `hold_check` → (`checks` → `proposal`) → `verdict` → `opinion` → `verify`
  - 보류면 `hold_check`에서 `verdict`로 바로 감
  - `verify` 실패 시 `opinion`으로 되돌아감(최대 2회 재작성), 그래도 실패하거나 ai 무응답·예외면 양식 의견서로 끝
  - `ReviewDeps`: server가 넣는 `load_snapshot`(근거 고정), `write_opinion`(ai 호출), `interpret`(직원 요청 원문 해석, 선택)
  - `run_review_flow`: 그래프를 끝까지 돌리고 `on_progress`로 노드 이름을 차례로, 마지막에 `done`을 넘김. 결과는 `ReviewOutcome`(스냅샷, 판정 결과, 의견서)
- `packages/review/src/bjk_review/verify.py`: 숫자로 정확히 쓴 금액은 오차 없이 비교(아래 검증에서 발견)
- 테스트: `test_graph.py` 16개, `test_opinion.py`에 정확 금액 회귀 1개
- `docs/ai-work-rules.md` 담당 범위에 LangGraph 검토 흐름 추가

## 결정과 근거

- **그래프는 `bjk_review` 안:** 판정 엔진과 같은 이유(ai 서비스가 멈춰도 판정 동작, 설계 원칙 7). LLM 노드(`opinion`)는 server가 넣는 ai 호출 함수를 부를 뿐
- **노드 이름 = 진행 단계 이름:** API 명세서의 `review.progress` 단계(`interpret`, `snapshot`, `hold_check`, `checks`, `proposal`, `verdict`, `opinion`, `verify`, `done`)와 같게 해서 server가 이름 그대로 SSE로 보내면 됨. LangGraph `stream_mode=["updates", "values"]`로 노드 완료와 최종 상태를 함께 받음
- **규칙 노드는 기존 순수 함수 재사용:** 그래프 결과가 `run_review`와 같음을 예시 6건 전부 테스트로 고정
- **`interpret` 노드:** 시스템 초안과 확인 카드를 거친 직원 요청은 원안이 이미 있어 건너뜀(F-REVIEW-01 "시스템 초안은 생략"). 원문만 있으면 server의 해석 함수를 부르고, 못 하면 부품 미확정으로 보류
- **ai 예외도 대체 경로:** `write_opinion`이 예외를 던져도 양식 의견서로 끝냄
- **`finalize_opinion`은 남김:** 그래프 밖에서 의견서만 다시 쓸 때(예: 재검토 후)용. 같은 검증·양식 함수를 쓰고, 그래프 결과와 같음을 테스트로 확인
- **정확 금액은 오차 없음:** "15,000원"처럼 숫자로 쓴 금액은 정확히 같아야 함. 천 원 미만 오차는 "1만 5천 원"처럼 만·천 단위로 어림한 표기에만 허용

## 검증

- `uv run pytest`: 137개 통과(그래프 16개 추가). `ruff check`, `ruff format --check` 통과
- 그래프 노드 목록이 진행 단계 순서와 같음, 예시 6건의 그래프 결과 = `run_review` 결과, 재작성 시 진행 단계가 `opinion → verify`를 반복, 보류는 `checks`·`proposal`을 건너뜀
- **실제 Gemini로 그래프 끝까지 실행(예시 6건):**
  - 1차: 6건 모두 `llm` 의견서로 검증 통과, 검토 한 건 1.2~2.5초(명세 10초 이내). 진행 단계가 명세 순서대로 나옴
  - 1차에서 검증 구멍 발견: 6204 의견서가 실제 평균 단가 15,500원을 "15,000원"으로 썼는데 천 원 미만 오차 허용 때문에 통과. 정확 금액은 오차 없이 비교하도록 수정
  - 2차: 6204는 첫 의견서가 검증에 걸려 `opinion`으로 되돌아가 다시 썼고(진행: `… opinion → verify → opinion → verify → done`), 다시 쓴 의견서는 "평균 단가 15,500원"으로 맞음. 나머지 5건은 첫 시도 통과. 모두 2.3초 이내
- LangGraph가 쓰는 langsmith가 Python 3.14에서 사용 중단 경고(`asyncio.iscoroutinefunction`)를 냄. 동작 영향 없음

## 남은 일·확인 필요

- server 연동: 검토 요청이 생기면 `run_review_flow(ReviewDeps(load_snapshot, write_opinion), …, on_progress=SSE 전송)` 호출 후 `ReviewOutcome` 저장
- 진행 단계는 노드가 끝난 시점에 나옴. 의견서 노드가 가장 오래 걸리므로(1~2초) 화면은 `verdict` 다음에 "의견서 작성 중"으로 보이게 하는 것을 server·화면 담당과 맞출 것
- 확인 필요: 숫자 검증은 "어떤 숫자를 무엇이라고 불렀는지"까지는 보지 못함(`2026-11-05-08` 기록과 같음)
