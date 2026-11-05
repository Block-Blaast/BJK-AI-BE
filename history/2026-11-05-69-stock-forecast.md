# 재고 추이 예측선 API

- 날짜: 2026-11-05
- 영역: server
- 관련: #258, W-03·W-05, REV-07

## 목적

- 검토 상세·부품 상세 화면의 재고 예측 그래프 데이터 제공 (프론트 `reviews/{id}/forecast`, `parts/{id}/forecast`)

## 한 일

- `domain/forecast.py`: 결재용 PDF에 있던 일별 예측 계산을 공용 순수 함수로 이동, PDF도 같은 함수 사용
- `GET /reviews/{id}/forecast`(스냅샷 기준), `GET /parts/{id}/forecast`(최신 새벽 계산 기준), 응답 `api/schemas.Forecast`
- 테스트 `test_stock_forecast.py` 5개, 문서 `reviews.md`·`parts.md`

## 결정과 근거

- 명세에 없어 사용자 결정: 새 API 2개, 계산은 결재용 PDF 그래프와 같은 단순 추정(m ÷ 30, 발주 수량은 LT90 날 입고)
- 판정에 쓰지 않는 표시용 값

## 검증

- `test_stock_forecast.py`·`test_review_pdf.py` 등 관련 테스트 통과, `make lint` 통과. 전체 테스트는 지시에 따라 생략
- dev(e25cc14)에서 이번 변경과 무관하게 `test_part_detail.py::test_detail_after_nightly_shows_latest_metrics`, `test_review_detail.py::test_detail_reads_review_saved_by_run_service`, `test_review_run.py`의 2개가 이미 실패(새벽 계산 납기 값 변화로 보임)

## 남은 일·확인 필요

- Notion API 명세서 반영(사용자 확인 후)
- 위 dev 기존 실패 4개 원인 확인
