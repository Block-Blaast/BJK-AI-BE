# 발주 검토 API

기능명세서 F-REVIEW 기준. 체크·수정안·판정은 검토 엔진 `bjk_review`(순수 함수)가 만들고, server는 근거 스냅샷 수집·저장·상태·이벤트를 맡는다(`bjk_server.reviews`). LLM은 의견서 문장만 쓴다.

## 검토 실행

HTTP API가 아니라 채팅 발주 요청(CHAT-04), 재고 부족 초안, 놓친 발주 초안이 부르는 서비스다.

1. `create_review`: `reviewing` 검토를 만들고 같은 트랜잭션에 `review.created`를 남긴다. 원안은 `request`(`qty`, `supplier_id`, `unit_price`, `text`).
2. 커밋 뒤 `run_review`(요청 처리 중이면 `ReviewRunner.start_after_commit`로 백그라운드 실행): 근거 고정 → 보류 판단 → 체크 9개 → 수정안 → 판정 → 의견서 → 검증.
3. 단계마다 `review.progress`(`interpret`, `snapshot`, `hold_check`, `checks`, `proposal`, `verdict`, `opinion`, `verify`)를 짧은 트랜잭션으로 남긴다. 보류면 `checks`·`proposal`이 빠지고, 의견서를 다시 쓰면 `opinion`·`verify`가 반복된다.
4. 결과 저장과 `done` 단계는 한 트랜잭션이다. `done`을 받은 화면은 저장된 결과를 조회할 수 있다.

| 판정 | 상태 | 만료 시각 |
| --- | --- | --- |
| `ok`, `revise` | `reviewed` | 저장 시각 + `system.review_expire_days`(기본 7일) |
| `hold` | `held` | 저장 시각 + `system.review_expire_days` |

- 저장: `reviews`에 판정·표시·보류 사유·결과(`checks`, `original`, `proposal`, `alternatives`, `risk_if_not_ordered`, `count_requests`)·의견서(`text`, `source`, `verified`)·원안 총액·절감액·미발주 예상 손실, `review_snapshots`에 스냅샷 값·검토 기준값·해시(`sha256:…`)·계산 시각.
- 의견서: ai(`AI_BASE_URL`)가 없거나 실패·시간 초과(4초)·숫자 검증 실패면 양식 의견서(`source: template`). ai 호출 사용량은 `llm_calls`(`purpose: opinion`)에 남긴다.
- 이미 `reviewing`이 아닌 검토는 다시 실행하지 않는다.

### 근거 스냅샷 (F-REVIEW-02)

| 값 | 출처 |
| --- | --- |
| S | 검토 시점 원장 합계 |
| H_c, H_u | 같은 카테고리·규격의 병합 전 다른 부품 재고. 마지막 실사 `system.hidden_stock_count_days`(기본 30일) 이내이고 열린 의심 항목이 없으면 확인됨 |
| P | 같은 부품의 다른 열린 검토(`reviewing`, `reviewed`, `held`). 수정안이 있으면 수정안 수량 |
| m, F, D95, D99, t_out, t_deadline, L, r_lead, r_price | 최신 새벽 계산(`part_metrics`). 계산 전이면 D95·D99는 0 |
| F_12m | 향후 365일 미완료 정비의 필요 수량(일정의 필요 부품, 없으면 설비 정비 1회당 수량) |
| 공급사 | `supplier_parts` 조건과 공급사별 최신 LT90, 계산 전이면 공급사 기본 납기(없으면 7일) |
| 연휴 | 오늘부터 기본 공급사 LT90 사이에 걸치는 연휴(카테고리 납기 요인의 국내·중국 명절, 기본 공급사 휴무) |

- 현재 구현 범위: 열린 발주(O, `open_orders`)와 최근 구매 단가 통계(`price_stats`)는 발주 테이블 연결 전이라 비어 있다(C-03 열린 발주, C-05 건너뜀). 병합 부품 재고는 S에 더하지 않는다. 미확인 숨은 재고의 실사 요청은 결과 `count_requests`에만 담고 `count_requests` 행은 만들지 않는다.
