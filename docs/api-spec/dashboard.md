# 대시보드 (DSH-02)

API 명세서 10장, 화면 W-01 기준.

## DSH-02 `GET /dashboard/summary`

- 권한: manager 이상. worker는 403.
- `risk_top5`: 부품별 최신 근거 지표(nightly)의 우선순위(P_out × L) 상위 5개. `L`은 `part_metrics.loss`.
- `pending_reviews`: 상태 `reviewed`·`held` 검토 수, `urgent`는 그중 `urgent` 표시 건(2026-11-05 사용자 결정).
- `audit_flags`: 닫히지 않은 의심 항목 수(`open`·`count_requested`)와 그중 `high`.
- `awaiting_order`: 발주 테이블 연결 전이라 항상 0.
- `tied_up_stock_amount`: 최근 180일 출고가 없고 재고가 있는 부품의 재고 × 단가 합. 단가는 기본 공급사, 없으면 가장 싼 공급사, 없으면 0원(명세에 정의 없음, 2026-11-05 사용자 결정).
- `external`: 외부 지표 등급 중 가장 높은 값과 마지막 갱신 시각(DSH-03과 같은 계산).
- `today`: Asia/Seoul 오늘 0시부터의 원장 기록 수, 생성된 검토 수, 결정 수.
- `computed_at`: 최신 근거 지표 계산 시각. 아직 없으면 `null`.
