# 배치 (HTTP API 아님)

API 명세서 14장 기준. 예약은 API 서버와 분리된 APScheduler 프로세스(`python -m bjk_server.jobs.scheduler`, compose `scheduler` 서비스)가 하고, 실행·잠금·기록은 `run_job`이 맡는다. 수동 실행은 CLI를 쓴다. CLI 실행도 `job_runs.trigger`는 `schedule`로 남고, `manual`은 DEV-01 실행뿐이다.

```bash
python -m bjk_server.jobs nightly
```

| 이름 | 시각 (Asia/Seoul) | 구현 |
| --- | --- | --- |
| `nightly` | 매일 03:00 | 외부 지표 위험도 → 부품 근거 지표 → 장부 검증 → 빈 임베딩 채우기 |
| `missed-scan` | 매일 07:00 | 놓친 발주 초안 생성 → 검토 |
| `order-check` | 매일 07:00 | 승인 후 24시간 지나도 주문 전인 발주 → 승인자(없으면 관리자·사장님)에게 `order_check` 알림, 주문 후 기본 공급사 LT90(근거 지표, 없으면 공급사 기본 납기, 그것도 없으면 7일)을 넘겨 다 들어오지 않은 발주 → 관리자·사장님에게 `receipt_check` 알림. 배치 알림은 발주마다 한 번만. 요약 `{ "order_check": n, "receipt_check": n }`의 n은 새로 만든 알림 수(받는 사람 수 합)이고 이미 알린 발주는 세지 않는다. 입고 수량이 잔량보다 많을 때(CHAT-03 `po_match: mismatch`)도 `receipt_check`를 보내며 이 알림은 입고마다 나간다 |
| `briefing` | 매일 07:30 | 결정 대기 검토 만료(요청자 알림) → 브리핑 계산, 확인할 일이 있으면 사장님·관리자 알림(하루 1회) |
| `weekly-merge` | 월요일 03:30 | 중복 부품 후보 저장, 한쪽이 병합된 열린 후보 종료([merge.md](merge.md)) |
| `cleanup` | 매일 04:00 | 만료 행 삭제: `rate_limits` 창 종료 1시간 뒤, `pin_attempts` 잠금 해제·마지막 실패 1일 뒤, `idempotency_keys` 7일 뒤 (명세 밖, #185) |
| `push` | 10분마다 | 보낼 시각이 된 웹 푸시 발송(조용한 시간으로 미룬 알림 포함, NOT-04). VAPID 키가 없으면 실행 상태는 `ok`, 요약은 `{ "skipped": "vapid_not_configured" }` |

- 플랫폼 cron을 쓰는 환경이면 스케줄러 대신 `infra/cron/crontab`처럼 CLI를 예약해도 된다. 단 현재 `infra/cron/crontab`에는 `push`가 없어, cron만 쓰면 미룬 웹 푸시와 커밋 직후 발송에 실패한 푸시가 나가지 않는다. 둘을 같이 켜도 advisory lock으로 한 번만 실행된다.
- RLS가 적용되는 앱 계정(`DATABASE_URL`)으로 실행한다. 회사 ID 목록만 `system_company_ids()` 함수로 받고, 회사마다 `app.company_id`를 지정한 뒤 그 회사 데이터만 읽고 쓴다.
- 같은 작업은 advisory lock으로 한 번에 하나만 돈다. 겹치면 `skipped`(`already_running`)로 기록한다.
- 실패하면 작업 트랜잭션을 롤백하고 `job_runs`에 `error`로 남긴다. CLI 종료 코드 1.
- 실행 기록(`job_runs`)은 `GET /api/v1/health`의 마지막 배치 상태에 쓴다.

## 스케줄러 스레드 풀

| 설정 | 값 | 이유 |
| --- | --- | --- |
| 실행기 | `ThreadPoolExecutor(max_workers=SCHEDULER_WORKERS)`, 기본 2 | 같은 시각에 겹치는 작업이 최대 2개(07:00 `missed-scan`·`order-check`, nightly가 길어질 때 월요일 03:30 `weekly-merge`) |
| DB 연결 풀 | `pool_size` = 워커 수, `max_overflow` 0 | `run_job`은 작업당 연결을 하나씩만 쓰므로 워커가 연결을 기다리며 막히지 않고, DB 연결 수도 워커 수를 넘지 않는다 |
| 같은 작업 동시 실행 | `max_instances` 1 | 앞 실행이 안 끝났으면 이번 실행은 건너뛰고 경고 로그 |
| 밀린 실행 | `coalesce` true, `misfire_grace_time` 30분 | 여러 번 밀려도 1회만, 30분 넘게 늦으면 건너뜀 |
| 종료 | SIGTERM·SIGINT → 새 실행 중단, 실행 중 작업 완료 대기, 엔진 정리 | compose `stop_grace_period` 5분. 그 안에 못 끝나면 강제 종료되고 작업 트랜잭션은 롤백 |

- 워커 수를 늘리면 DB 연결 풀도 같이 늘어난다(`SCHEDULER_WORKERS` 하나로 조절).
- 작업 목록은 코드에 있고 메모리에만 둔다. 스케줄러가 꺼져 있던 동안의 실행은 다시 하지 않는다(필요하면 DEV-01·CLI로 수동 실행).

## nightly: 외부 지표 위험도 → 부품 근거 지표

기능명세서 F-EXT-02, F-ANAL 기준. 계산은 `bjk_server.domain`의 순수 함수(numpy)이고 LLM을 쓰지 않는다. 난수 시드는 hash(회사, 부품, 날짜)라 같은 날 다시 돌려도 같은 값이 나오며, 같은 날짜 스냅샷은 덮어쓴다.

| 단계 | 방법 | 저장 |
| --- | --- | --- |
| 외부 지표 | CSV(`seed/data/external_indicators.csv`, 주간) 적재. z = 최근 13주 변화율 ÷ 과거 13주 변화율의 표준편차, r = min(max(0, z), 4). 상승(운임 상승, 원화 약세)만 위험 | `external_indicators` |
| 카테고리 위험도 | r_lead = 카테고리 `lead_factors` 지표 r 최대, r_price = `price_factors` 지표 r 최대 | `part_metrics.r_lead`, `r_price` |
| 납기 | 기본 납기 × (1 + k × r_lead, 수입 의존 부품만)에 납기 구간과 겹치는 연휴만큼 연장. 연휴 = 공급사 휴무일 + 공급사 범위 캘린더 + 카테고리 납기 요인(`HOLIDAY_KR` → 국내, `HOLIDAY_CN` → 중국)의 캘린더. 같은 날은 한 번만, 늘어난 구간에 걸린 연휴도 센다 | `part_supplier_metrics` |
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
- 숨은 재고: 같은 카테고리·같은 규격 부품의 재고를 H_u로 기록한다. 실사 기록 전이라 H_c는 항상 0이다.
- 입고 예정 O: 열린 발주 전이라 0이다.
- 수입 의존: 카테고리(또는 부품 예외)의 수입 의존도가 `high`·`medium`이면 수입 의존으로 본다.
- 근거 지표 계산 뒤 장부 검증 규칙 5종을 실행한다([audit.md](audit.md)). 요약의 `audit_flags_created`는 새로 만든 의심 항목 수다.
- `AI_BASE_URL`이 있으면 임베딩이 없는 부품(병합 제외)·별칭을 100개씩 묶어 채운다. 요약의 `embeddings_filled`는 채운 행 수다.
- 재고 요약 대조(F-LEDGER-02)는 요약 도입 시 더한다.

## missed-scan: 놓친 발주 스캔

기능명세서 F-MISSED-01 기준. 회사마다 최신 근거 지표(`part_metrics`)에서 대상 부품을 골라 시스템 초안 검토(`entry: missed_draft`, 요청자 없음)를 만든다.

| 조건 | 값 |
| --- | --- |
| 결품 확률 | `p_out` ≥ `system.missed_p_out_min`(기본 0.3) |
| 발주 마감 | `t_deadline` ≤ 오늘 + `review.c08_days`(기본 5일, C-08과 같은 기준) |
| 권장 발주량 | R > 0 (R = 0이면 초안을 만들지 않음) |
| 중복 방지 | 같은 부품의 열린 발주(`approved`, `ordered`, `partially_received`)·열린 검토(`reviewing`, `reviewed`, `held`)가 있거나, 오늘(Asia/Seoul) `accept_no_order`로 닫힌 검토가 있으면 제외. 재고 부족 초안과 같은 규칙(`reviews.drafts.BLOCKERS`) |

- 초안 원안: 수량 R, 공급사는 기본 공급사, 단가는 비움(등록 단가 사용). 우선순위(P_out × L) 높은 순으로 만든다.
- 초안은 작업 트랜잭션과 함께 커밋되고, 검토([reviews.md](reviews.md) 검토 실행)는 커밋 직후 같은 프로세스에서 하나씩 끝까지 돈다. 요약 `{"companies", "drafts_created"}`.
