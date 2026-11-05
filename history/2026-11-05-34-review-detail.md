# 검토 상세 조회

- 날짜: 2026-11-05
- 영역: server
- 관련: #147, REV-02, F-REVIEW-07, #146(PR #206)

## 목적

- 저장된 검토 결과를 화면에 보여 줄 상세 API

## 한 일

- `api/reviews.py`: `GET /reviews/{id}`, worker는 본인 요청만
- `docs/api-spec/review-queries.md`
- `tests/review_rows.py`(검토 엔진으로 만든 행), `tests/test_review_detail.py`

## 결정과 근거

- 저장 구조는 PR #206 `_save` 기준: `reviews.result`에 판정·표시·보류 사유·해시를 뺀 `ReviewResult`, `review_snapshots.values`에 스냅샷 전체
- 스냅샷 `values`는 명세 예시 키로 변환해 응답
- 남의 검토 접근은 404(명세에 403·404 구분 없음, 이슈 완료 기준 따름)
- `docs/api-spec/reviews.md`는 #206이 만들므로 충돌을 피해 별도 문서

## 검증

- `REQUIRE_DB_TESTS=1 uv run pytest apps/server/tests/test_review_detail.py`: 5개 통과
- `REQUIRE_DB_TESTS=1 make test`: 749개 통과, `make lint` 통과

## 남은 일·확인 필요

- #146 dev 머지 후 dev를 반영해 저장 구조 재확인
