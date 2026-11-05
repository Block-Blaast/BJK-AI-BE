# server 임베딩 1024차원 변경 대조

- 날짜: 2026-11-05
- 영역: AI
- 관련: PR #157(Issue #156), PR #159(Issue #154), 닫힌 PR #155, `2026-11-05-17-ai-stack-merge.md`

## 목적

- "클라우드 쪽에서 1024로 맞췄다"는 전달을 받고, server 쪽 변경이 AI 계약과 맞는지 확인

## 한 일

- 머지된 dev 최종 확인(앞 기록에 넣지 못한 결과): DB 포함 `pytest` 510개 통과
- 1024 변경이 두 곳에서 따로 진행 중인 것을 확인
  - PR #157(`fix/embedding-dim/#156`, base `main`): 이미 있는 마이그레이션 0012의 차원을 1024로 직접 고침
  - PR #159(`feat/server-ai-integration/#154`, base `dev`, Draft): 새 마이그레이션 0019로 기존 벡터를 지우고 `vector(1024)`로 바꿈, ORM은 `bjk_contracts.EMBEDDING_DIM`을 그대로 씀
- #159의 ai 연동 코드를 계약과 대조: `AiClient`(타임아웃, 대체 응답, `schema_invalid`), 채팅 어댑터, 임베딩 저장·검색(같은 모델끼리만 비교), `llm_calls` 기록
- 클라우드 레포(`BJK-Cloud`) 확인: Terraform VPC 기본 구성만 있음. EC2·IAM·메타데이터 홉 제한 설정은 레포에 없음

## 검증

- `fix/embedding-dim-1024`를 dev에 합쳐 차원 대조: 계약·ORM·마이그레이션 모두 1024, DB 포함 510개 통과
- #159 브랜치
  - DB 포함 `pytest` 552개 통과, `ruff check` 통과
  - 실제 HTTP 확인: 빈 DB에 `alembic upgrade head`(0018·0019 적용), ai 앱을 1024차원 가짜 provider로 띄우고 server `AiClient`로 호출
    - `/health` ok
    - 채팅 해석이 `Interpretation`으로 바뀌고 `usage` 받음
    - 임베딩 2×1024 받음, `parts.embedding`은 `vector(1024)`, 1024 벡터 저장·코사인 1.0, `vector(1536)`는 거부
- #157과 #159를 합치면 `0012_part_embeddings.py`·`models.py`가 충돌함(`git merge-tree`)

## 알아둘 점

- #157 방식(0012 직접 수정)은 이미 0012를 적용한 DB에는 반영되지 않음(alembic이 다시 적용하지 않음). #159의 0019가 기존 DB와 빈 DB 모두에서 1024로 맞춤
- #157은 dev를 거치지 않고 `main`으로 감. 둘 다 머지되면 충돌하고 차원 변경이 두 번 정의됨. #159로 하나로 정하는 것을 server·클라우드 담당에게 제안
- Bedrock Titan 실제 벡터로 정한 코사인 기준(후보 0.5, 확정 0.85)은 아직 미검증. EC2에서 실제 벡터로 확인 필요
- 검토 흐름(`bjk_review`) 연동과 회사별 토큰 상한은 #159 범위 밖(후속)

## 남은 일

- #157 정리 여부 결정(server·클라우드 담당)
- #159 CI 통과 후 머지
- EC2에서 `apps/ai/scripts/smoke.py`로 Bedrock 실제 호출, 실제 Titan 벡터로 코사인 기준 확인
