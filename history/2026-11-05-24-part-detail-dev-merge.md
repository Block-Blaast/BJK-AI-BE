# 부품 상세 통합 PR #137 dev 반영

- 날짜: 2026-11-05
- 영역: server
- 관련: #137, #111~#118, SET-04

## 목적

- 박진욱님 통합 PR #137(#111~#118)을 최신 dev에 맞춰 머지 가능 상태로 정리

## 한 일

- `feat/part-detail/#111`에 `origin/dev`를 네 번 머지(리베이스·강제 푸시 없음). 충돌은 모두 양쪽 유지: `.env.example`(`AI_BASE_URL`·`WEB_BASE_URL`), `config.py`(`ai_base_url`·`web_base_url`), `db/models.py`(`LlmCall`·`ServerEvent`·`Review`·`ReviewSnapshot`), `tests/conftest.py`(`get_ai_client`·`get_session_scope` 오버라이드), `chat/records.py`(`publish`·`lock_part_stock` import)
- 병합 때 공통 꼬리 줄로 빠진 `ReviewSnapshot.created_at` 복원
- 브랜치 마이그레이션 `0018_invites`·`0019_events`·`0020_reviews`를 `0021_invites`·`0022_events`·`0023_reviews`로 변경, 첫 `down_revision`을 dev `0020`(`idempotency_request_owner`)으로. `test_review_tables.py`의 downgrade 대상을 `0022`로 변경
- 자동 병합된 `api/parts.py`(임베딩 저장), `chat/records.py`(박스 단위 환산), `test_migrations.py`(0019 검증), `docs/api-spec/parts.md`·`system.md` 확인

## 결정과 근거

- dev가 먼저 0018~0020을 썼으므로 나중에 머지하는 브랜치 쪽 번호를 올림

## 검증

- 로컬 PostgreSQL 16 `REQUIRE_DB_TESTS=1 make test` 660개 통과, `make lint` 통과
- 빈 DB `alembic upgrade head` → `downgrade 0020` → `upgrade head` 왕복, `alembic heads`는 `0023` 하나

## 남은 일·확인 필요

- 머지 후 개별 Draft PR #138~#144 종료
