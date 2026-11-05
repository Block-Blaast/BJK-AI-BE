# AI PR 스택을 최신 dev에 맞추기

- 날짜: 2026-11-05
- 영역: AI
- 관련: PR #63 #70 #72 #74 #78 #80 #82 #86 #90, `2026-11-05-12-ai-status-review.md` 문제 1·4

## 목적

- server 스택이 dev에 머지되며 PR #63이 dev와 충돌(`CONFLICTING`)해 스택 전체를 머지할 수 없던 문제 해결
- 미뤄 둔 compose·`.env.example`의 ai 설정 추가

## 한 일

- 브랜치 9개에 차례로 merge: #61 ← `origin/dev`, 그 뒤 각 브랜치 ← 바로 앞 브랜치. 이미 push된 브랜치라 rebase 대신 merge 커밋(`merge: dev`, `merge: <앞 브랜치>`)
- 충돌 해결
  - `history/README.md`: server와 AI가 같은 색인을 씀. 양쪽 표 행을 모두 살리고 파일명 역순으로 정렬, 머리말은 dev 것("AI·server 영역 작업 기록 색인")
  - `uv.lock`: 브랜치 쪽을 두고 `uv lock`으로 다시 생성
  - 그 밖의 충돌 없음
- `feat/ai-bedrock/#89`에 커밋 추가: `compose.yaml` ai 서비스에 `AWS_REGION`(기본 `ap-northeast-3`)·`GEMINI_API_KEY`(빈 값 허용) 전달, `.env.example`에 ai 설정 안내
- 9개 브랜치 push

## 검증

- 브랜치마다 merge 직후 `uv run pytest`(DB 테스트 제외)와 `ruff check`·`ruff format --check` 통과
- 9개 브랜치 모두 `origin/dev`를 포함함(`git merge-base --is-ancestor`)
- 스택 끝(`#89`)에서 DB 테스트 포함 **385개 통과**(`pgvector/pgvector:pg16` 임시 컨테이너, `REQUIRE_DB_TESTS=1`, 끝난 뒤 정리)
- `docker compose config` 통과

## 알아둘 점

- server는 임베딩 차원을 자기 상수(`EMBEDDING_DIM = 1536`, 마이그레이션 0012)로 두고 있어 계약의 1024와 아직 다름. server 테스트는 계약 상수를 쓰지 않아 깨지지 않지만, 실제 저장은 server가 `vector(1024)`로 바꾼 뒤에 맞음(사용자가 server에 전달함)
- history 순번은 server와 AI가 따로 매겨 04~07이 겹침. 파일명이 달라 충돌은 없음

## 남은 일

- 각 PR CI 재실행 결과 확인, #63부터 차례로 Ready 전환·머지(server 담당 계약 확인 후)
- EC2에서 Bedrock 확인(`apps/ai/scripts/smoke.py`)
