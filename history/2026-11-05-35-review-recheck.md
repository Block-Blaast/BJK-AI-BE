# 재검토 미리 보기 API

- 날짜: 2026-11-05
- 영역: server
- 관련: #152, F-REVIEW-09, REV-04

## 목적

- 승인자가 직접 고친 수량·공급사·단가로 같은 스냅샷을 다시 판정해 보여줌 (저장 안 함)

## 한 일

- `api/review_actions.py`: `POST /reviews/{id}/recheck`, 최근 스냅샷·검토 기준값으로 `bjk_review.recheck`
- 테스트 `test_review_recheck.py` 7개, 문서 `docs/api-spec/reviews.md` REV-04

## 결정과 근거

- 조회·결정 API(#147·#162)와 파일 충돌을 피하려고 별도 라우터 파일 사용
- `reviewed`가 아니면 409 `REVIEW_NOT_DECIDABLE`

## 검증

- 로컬 PostgreSQL 16 `REQUIRE_DB_TESTS=1 make test` 733개 통과, `make lint` 통과

## 남은 일·확인 필요

- 결정 API(#162)의 `approve_edited`에서 `recheck_hash` 대조
