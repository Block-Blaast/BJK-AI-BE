# 검토 목록 항목에 요청 수량과 결정 추가

- 날짜: 2026-11-05
- 영역: server(REV-01 응답)
- 관련: #297, REV-01, M-03, BJKFE #22

## 목적

- 폰 "내 요청"이 모든 줄을 "0개 요청"으로 보이고 승인·반려 결과를 못 보여 줌. 목록 항목에 요청 수량과 결정이 없었음

## 한 일

- REV-01 항목에 `qty`(요청 원안 수량)와 `decision`(`action`, `reason`, `decided_at`) 추가
- 명세 `docs/api-spec/review-queries.md` 갱신, 테스트(항목 모양, 결정 담기)

## 검증

- `test_review_list.py` 16개 통과, 전체 `REQUIRE_DB_TESTS=1 uv run pytest` 967개 통과·1개 건너뜀(로컬 PostgreSQL)

## 남은 일·확인 필요

- 운영 배포 후 폰 내 요청 화면 확인(프론트 BJKFE #22와 함께)
