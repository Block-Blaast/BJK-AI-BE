# 배치 (HTTP API 아님)

API 명세서 14장 기준. 플랫폼 cron이 서버 이미지에서 CLI를 호출한다. 서버 프로세스 안에서 예약하지 않아 서버를 여러 대 띄워도 중복 실행되지 않는다.

```bash
python -m bjk_server.jobs nightly
```

| 이름 | 시각 (Asia/Seoul) | 구현 |
| --- | --- | --- |
| `nightly` | 매일 03:00 | 외부 지표 위험도 → 부품 근거 지표 |
| `missed-scan` | 매일 07:00 | 미구현 |
| `order-check` | 매일 07:00 | 미구현 |
| `briefing` | 매일 07:30 | 미구현 |
| `weekly-merge` | 월요일 03:30 | 미구현 |

- 예약 예시: `infra/cron/crontab`
- 소유자 DB 계정(`ADMIN_DATABASE_URL`)으로 회사 전체를 대상으로 실행한다.
- 같은 작업은 advisory lock으로 한 번에 하나만 돈다. 겹치면 `skipped`(`already_running`)로 기록한다.
- 실패하면 작업 트랜잭션을 롤백하고 `job_runs`에 `error`로 남긴다. CLI 종료 코드 1.
- 실행 기록(`job_runs`)은 `GET /health`의 마지막 배치 상태에 쓴다.

## nightly: 외부 지표 위험도 → 부품 근거 지표

기능명세서 F-EXT-02, F-ANAL 기준. 계산은 `bjk_server.domain`의 순수 함수(numpy)이고 LLM을 쓰지 않는다. 난수 시드는 hash(회사, 부품, 날짜)라 같은 날 다시 돌려도 같은 값이 나오며, 같은 날짜 스냅샷은 덮어쓴다.

| 단계 | 방법 | 저장 |
| --- | --- | --- |
| 외부 지표 | CSV(`seed/data/external_indicators.csv`, 주간) 적재. z = 최근 13주 변화율 ÷ 과거 13주 변화율의 표준편차, r = min(max(0, z), 4). 상승(운임 상승, 원화 약세)만 위험 | `external_indicators` |
| 카테고리 위험도 | r_lead = 카테고리 `lead_factors` 지표 r 최대, r_price = `price_factors` 지표 r 최대 | `part_metrics.r_lead`, `r_price` |
| 납기 | 기본 납기 × (1 + k × r_lead, 수입 의존 부품만) + 납기 구간에 겹치는 공급사 휴무일 | `part_supplier_metrics` |
| ABC | 최근 12개월 사용 금액 누적 80% A, 95% B, 나머지 C. 단가 없는 부품이 있으면 사용량 기준(`abc_basis: qty`) | `abc` |
| 수요 분류 | 정비 연결 출고를 뺀 주간 수요(최대 52주)의 ADI·CV² (1.32 / 0.49), 8주 미만 `insufficient` | `demand_class` |
| 예측 | smooth·erratic 단순 지수평활, intermittent·lumpy SBA (α = 0.1). m = 주간 예측 × 52 ÷ 12 | `forecast_weekly`, `m` |
| D95·D99 | 기간 T = LT90 + 다음 발주까지(기본 4주) 동안 부트스트랩 10,000회 + 정비 확정 필요량 F. 데이터 부족이면 포아송(월 사용 추정치) | `d95`, `d99`, `f_items` |
| 재주문점 | LT90 동안 수요 분포의 서비스 수준 분위수 (A 98%, B 95%, C 90%) + 그 기간 F | `reorder_point` |
| 소진일·결품 확률 | 8주 경로 시뮬레이션. 재고 0 이하 첫날의 중앙값 t_out, 오늘 + LT50까지 결품 확률 P_out. t_deadline = t_out − LT90 | `t_out`, `p_out`, `t_deadline` |
| 손실·우선순위 | L = Σ(시간당 손실 × 가동 시간) × LT50, 우선순위 = P_out × L | `loss`, `priority` |
| 권장 발주량 | R = max(0, D95 − S − O − H_c) → MOQ 배수 올림 | `recommended_qty` |

현재 구현 범위와 명세 차이:

- 납기 표본: 발주 테이블 전이라 모든 공급사가 기본 납기 하나(표본 0건)로 계산되어 LT50 = LT90이다.
- 캘린더: `calendar_events`(국내 명절·춘절) 전이라 공급사 휴무일만 납기에 더한다.
- 숨은 재고: 같은 카테고리·같은 규격 부품의 재고를 H_u로 기록한다. 실사 기록 전이라 H_c는 항상 0이다.
- 입고 예정 O: 열린 발주 전이라 0이다.
- 수입 의존: 카테고리(또는 부품 예외)의 수입 의존도가 `high`·`medium`이면 수입 의존으로 본다.
- 장부 검증(F-AUDIT)과 재고 요약 대조(F-LEDGER-02)는 해당 기능에서 이 작업에 더한다.
