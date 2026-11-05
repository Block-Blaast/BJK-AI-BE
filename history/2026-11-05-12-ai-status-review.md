# AI 영역 전체 점검 (동작·server 연결성)

- 날짜: 2026-11-05
- 영역: AI
- 관련: PR #63 #70 #72 #74 #78 #80 #82 #86, server 기록 `2026-11-05-06-server-deferred.md`·`2026-11-05-07-server-todo.md`(dev)

## 목적

- 지금까지 만든 AI 영역이 실제로 동작하는지, server(dev 최신)와 어긋나는 곳이 없는지 다시 확인

## 한 일

- 스택 끝(`feat/review-langgraph/#85`)에서 테스트·lint 재실행, PR 8개 상태·CI 확인
- 실제 Gemini 재확인: 채팅 8문장, 임베딩, 의견서, 이관 제안 13줄, 검토 그래프 예시 6건. uvicorn으로 띄워 HTTP로도 확인
- dev 최신(server 스택 머지됨)과 대조: 채팅 해석 포트, DB 모델, 스냅샷에 필요한 데이터, compose, 의존성, server 기록
- 임시 worktree에서 dev + 스택 끝을 시험 머지하고 DB 포함 전체 테스트 실행(push 안 함, 정리함)

## 검증 결과

- 스택 끝: 137개 통과, `ruff` 통과. PR 8개 CI 모두 통과
- 실제 Gemini: 전 호출 대체 경로 없이 1회 시도 성공. 채팅 0.8~1.4초, 이관 13줄 3.4초, 검토 그래프 6건 모두 `llm` 의견서 검증 통과
- uvicorn 실행: `/health` `llm: ok`, 채팅 해석 0.8~1.1초, 이벤트 루프 경고 없음
- **dev + 스택 시험 머지: 374개 전부 통과**(DB 테스트 포함, `pgvector/pgvector:pg16` 임시 컨테이너, `REQUIRE_DB_TESTS=1`). `ruff` 통과
- 머지 충돌은 `uv.lock`(다시 생성하면 됨), `history/README.md`(server도 같은 색인을 씀) 두 파일뿐

## 찾은 문제와 어긋남

| # | 내용 | 영향 | 조치 |
| --- | --- | --- | --- |
| 1 | PR #63이 dev와 `CONFLICTING` | 스택 전체 머지 불가 | dev를 #61 브랜치에 합치고 위 브랜치로 차례로 전파, `uv.lock` 재생성, 색인 합치기 |
| 2 | **server 할 일 7번이 "검토 엔진과 REV-02(스냅샷, 체크 9개, 수정안, 판정, 양식 의견서)"** | `bjk_review`와 중복 개발 위험 | 사용자 결정 필요. server는 `bjk_review` 사용, 스냅샷 수집·저장·REV API만 만들도록 전달 |
| 3 | server 기록이 #21 별칭 후보 순위를 ai 파트로 남김 | 명세상 LLM 순위 없음(#21 종료) | server에 전달 |
| 4 | `compose.yaml` ai 서비스에 `GEMINI_API_KEY` 없음, `.env.example`에도 없음 | compose로 띄우면 ai가 항상 대체 응답 | 추가 필요(server 스택이 머지돼 이제 충돌 위험 낮음) |
| 5 | server 채팅 해석 포트는 품목 1개(`Interpretation`), ai는 `items` 배열 | 연결 시 어댑터 필요 | 첫 품목 사용으로 시작, 여러 품목은 후속 |
| 6 | server 의존성에 `bjk-review` 없음 | 검토 엔진 사용 불가 | server가 연동 때 추가 |
| 7 | 검토·발주·`llm_calls` 테이블이 dev에 없음 | 검토 결과 저장, 열린 발주(O·C-03), 단가 통계(C-05) 불가 | server 할 일 7~13번 |
| 8 | 스냅샷 데이터 부족: 숨은 재고는 합계만(부품별 목록 없음, H_c 항상 0), `f_12m` 없음, 연휴 미반영, LT50 = LT90 | C-02 정확도, 실사 요청 대상, C-09 연휴 | server 모델 보강 필요. 엔진은 이 값들이 없으면 해당 체크를 건너뜀 |
| 9 | server와 AI가 같은 `history/`에 번호를 따로 매김(04~07 겹침) | 파일명은 달라 충돌 없음, 순번 혼동 | 색인 합칠 때 영역 열 추가 제안 |

## 남은 일

- 사용자 결정: 문제 2(검토 엔진 담당)
- AI가 할 수 있는 것: 문제 1(스택을 dev에 맞추기), 문제 4(compose·`.env.example`), 서버용 연동 안내 문서
- server가 할 것: 문제 5~8
