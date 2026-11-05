# 임베딩 1024 마이그레이션을 main 배포 DB에 맞춤

- 날짜: 2026-11-05
- 영역: AI(사용자 지시로 server 마이그레이션 수정)
- 관련: Issue #166, PR #157, PR #159, `2026-11-05-18-embedding-dim-check.md`

## 목적

- 사용자 지시: "main에 1024로 차원 이미 배포 됐거든? dev 쪽에서 수정해서 main에다 일단 해줘"
- main은 0012를 1024로 직접 고쳐 배포했고(#157), dev는 0012를 1536으로 두고 0019에서 바꿈(#159). 그대로면 dev를 main에 올릴 때 충돌하고, 배포 DB에서 0019가 기존 임베딩을 지움

## 한 일

- `fix/embedding-migration-main/#166`(dev 기준)에 `origin/main` merge
  - `0012_part_embeddings.py`: main 쪽(1024)을 따름, 주석만 고침
  - `models.py`: dev 쪽(`bjk_contracts.EMBEDDING_DIM` 사용)을 따름
- 0019 수정: 열의 차원(`atttypmod`)이 이미 1024면 건너뜀. 1536 열만 벡터를 비우고 1024로 바꿈. 0012가 1024로 만들므로 downgrade는 하지 않음
- 테스트 2개 추가: 0018까지 올린 DB에 1024 벡터를 넣고 head로 올리면 그대로 남음, 1536 열로 만든 DB는 1024로 바뀌고 벡터가 비워짐

## 검증

- DB 포함 `pytest` 554개 통과, `ruff check`·`ruff format --check` 통과
- 빈 DB `alembic upgrade head`, `alembic check` 차이 없음, `downgrade base` 통과
- 브랜치가 `origin/main`을 포함함(dev를 main에 충돌 없이 올릴 수 있음)

## 알아둘 점

- main 배포 DB는 alembic 0012까지 적용된 상태. main에 올리면 0013~0019가 차례로 적용되고, 0019는 1024 열이라 아무것도 바꾸지 않음
- 운영 server가 ai를 부르려면 배포 서버(`/opt/bjk`) 설정에 `AI_BASE_URL`(server·scheduler)과 ai의 `AWS_REGION`이 있어야 함. 레포 `compose.yaml`은 배포에 쓰이지 않음

## 남은 일

- dev 머지 후 main 배포 PR 머지, 배포 결과 확인
- 배포 서버 설정의 `AI_BASE_URL`·`AWS_REGION`·마이그레이션 실행 여부 확인(클라우드 담당)
