# AI PR 스택 dev 머지

- 날짜: 2026-11-05
- 영역: AI
- 관련: PR #63 #70 #72 #74 #78 #80 #82 #86 #90 #110, `2026-11-05-15-stack-sync-dev.md`

## 목적

- 사용자 지시("머지해. 그리고 서버도 다 됬다 하니까")에 따라 AI PR 10개를 dev에 머지

## 한 일

- #110 CI 실패 수정: `ruff format`이 `docs/ai-integration.md`의 코드 블록까지 검사함. 주석 앞 공백만 고침
- 머지 체크리스트의 "server 담당 … 확인" 항목은 사용자 전달("서버도 다 됬다")을 근거로 체크
- #90 체크리스트에서 실제로 확인하지 못한 두 항목(EC2 Bedrock 호출, server `vector(1024)`)을 빼고 검증 결과에 미검증·후속 작업으로 적음
- 10개 PR Ready 전환, #63부터 차례로 base를 dev로 바꾸고 merge commit(`merge: <head 브랜치>`, 본문 비움)으로 머지
- #78 머지 때 server PR이 같은 시간에 dev에 머지되며 `history/README.md` 색인 충돌. #77에 dev를 merge해 양쪽 표 행을 합치고(파일명 역순), 뒤 브랜치 #79→#81→#85→#89→#109에 앞 브랜치를 차례로 merge해 push

## 검증

- 머지 전 모든 PR CI·정책 검사 통과(lint·test, 이미지 빌드, PR 양식, 머지 준비)
- 충돌 해결 후 스택 끝에서 `uv lock --check`, `ruff check`·`ruff format --check`, DB 포함 `pytest` **500개 통과**(`pgvector/pgvector:pg16` 임시 컨테이너)
- dev 배포는 일어나지 않음(`deploy.yml`은 main push에서만 실행)

## 알아둘 점

- 사용자는 "서버도 다 됬다"고 했지만, dev와 모든 원격 브랜치에 server 쪽 AI 연동 코드는 아직 없음
  - 채팅: `get_interpreter`가 여전히 `UnconfiguredInterpreter`를 돌려줌
  - 임베딩: server DB·ORM이 `vector(1536)`, 계약은 1024
  - 검토: `bjk_review` 호출, `llm_calls` 기록 없음
- server가 ai를 아직 부르지 않으므로 지금 머지로 깨지는 동작은 없음. 연동 방법은 `docs/ai-integration.md`

## 남은 일

- server 연동(`docs/ai-integration.md` 6장 순서): `vector(1024)` 마이그레이션, 채팅 어댑터, 임베딩 매칭, 검토 흐름
- EC2(IAM Role)에서 `apps/ai/scripts/smoke.py`로 Bedrock 실제 호출 확인
