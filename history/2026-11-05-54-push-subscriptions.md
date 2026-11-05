# 웹 푸시 구독 저장

- 날짜: 2026-11-05
- 영역: server
- 관련: #184, NOT-04

## 목적

- 발송(G4 이후) 전에 브라우저 구독을 저장해 두기

## 한 일

- `push_subscriptions` 테이블·RLS (마이그레이션 0028)
- `api/push.py`: `GET /push/vapid-key`, `POST·GET /push/subscriptions`, `DELETE /push/subscriptions/{id}`
- `config.py`·`.env.example`: `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT`
- `docs/api-spec/push.md`, `tests/test_push_subscriptions.py`

## 결정과 근거

- 같은 회사·같은 endpoint는 한 줄, 다시 등록하면 키·사용자 갱신(명세에 중복 규칙 없음)
- 조회·해지와 공개 키 API는 명세 밖 추가. 구독 해지·키 전달에 필요

## 검증

- `REQUIRE_DB_TESTS=1 uv run pytest apps/server/tests/test_push_subscriptions.py`: 9개 통과
- `alembic check` 차이 없음
- `REQUIRE_DB_TESTS=1 make test`: 833개 통과(1개 생략), `make lint` 통과

## 남은 일·확인 필요

- 발송(VAPID 서명, 만료 구독 404·410 정리)은 G4 이후 후속 PR
- 명세 밖 API 3개 Notion 반영 여부 확인
