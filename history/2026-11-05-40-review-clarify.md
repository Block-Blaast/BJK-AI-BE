# 보류 검토 보완 API

- 날짜: 2026-11-05
- 영역: server
- 관련: #151, F-REVIEW-03, REV-03

## 목적

- 보류 검토에 부품·공급사를 보완하고 같은 검토를 다시 실행

## 한 일

- `api/review_actions.py`: `POST /reviews/{id}/clarify`, `held`만 허용, 같은 회사 부품·공급사 검증, `reviewing`으로 되돌린 뒤 커밋 후 백그라운드 재실행
- 테스트 `test_review_clarify.py` 8개, 문서 `docs/api-spec/reviews.md` REV-03

## 결정과 근거

- 요청자 본인 또는 manager 이상, 다른 작업자의 검토는 404
- 부품·공급사 둘 다 없거나 없는 값이면 400 `VALIDATION_ERROR`

## 검증

- 로컬 PostgreSQL 16 `REQUIRE_DB_TESTS=1 make test` 741개 통과, `make lint` 통과

## 남은 일·확인 필요

- 보류 7일 만료 처리는 정리 배치 쪽
