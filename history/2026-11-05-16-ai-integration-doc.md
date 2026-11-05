# server ↔ AI 연동 안내 문서

- 날짜: 2026-11-05
- 영역: AI
- 관련: Issue #109, Draft PR #110(→ #89 브랜치), 브랜치 `chore/ai-integration-doc/#109`(#89 브랜치 위에 쌓음), `2026-11-05-12-ai-status-review.md` 문제 2·5~8

## 목적

- server 담당이 AI 기능을 붙일 때 필요한 것을 한 곳에 정리. 검토 엔진 중복 개발을 막고(`bjk_review` 사용으로 결정), 연동 순서를 server 할 일 목록과 맞춤

## 한 일

- `docs/ai-integration.md` 작성
  - 역할 나눔과 결정 사항(검토 엔진은 `bjk_review`, LLM 매칭 순위 없음, 임베딩 1024차원)
  - 공통: 주소(`AI_BASE_URL`), 동기 `httpx.Client`와 타임아웃, 200 대체 응답, `ai`·`usage` 처리, 토큰 상한, `/health`
  - 엔드포인트별 요청·응답과 server 처리: 채팅 해석(포트 어댑터 예시), 임베딩(저장·같은 모델끼리 검색·pgvector), 엑셀 이관 제안(정규식과 합치는 규칙 제안)
  - 검토: `run_review_flow` 호출 예시, 진행 단계, 스냅샷 필드별 server 출처와 지금 비어 있는 값, 설정값 대응, REV-02 필드 대응, REV-03~06 함수
  - server 연동 순서(server 할 일 7~10, 20~23, 28 번호와 대응)
- `docs/ai-work-rules.md`에서 연결

## 검증

- 문서의 채팅 해석 어댑터를 server의 실제 `Interpretation`·`InterpreterUnavailable`과 `httpx.MockTransport`로 실행: 정상, `OTHER`, 대체 응답(→ `timeout`), HTTP 500(→ `error`), 타임아웃(→ `timeout`) 모두 기대대로
- 문서의 검토 호출 예시를 V벨트 예시로 실행: 진행 단계 9개, REV-02 대응 필드, `recheck`·`needs_refresh`·`decision_changed`·`answer_question`·`finalize_opinion` 동작, REV-06 예시 답변 일치

## 남은 일

- server 담당 확인(특히 스냅샷 필드 출처, `import_dependent` 기준, 이관 규격 병합 규칙)
