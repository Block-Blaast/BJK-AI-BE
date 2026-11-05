# 장부 검증·실사 API

기능명세서 F-AUDIT 기준. 판정은 `bjk_server.domain.audit`의 순수 함수(규칙 기반)이고 LLM을 쓰지 않는다.

## 장부 검증 규칙

새벽 배치(`nightly`)가 근거 지표 계산 뒤에 회사별로 실행한다. 음수 재고는 기록 직후에도 바로 검사한다(F-LEDGER-03).

| 규칙 `rule` | 등급 | 조건 | 근거 `evidence` |
| --- | --- | --- | --- |
| `NEGATIVE_STOCK` | `high` | 발생 순 원장 누적이 0 이상에서 0 미만으로 넘어간 행 | `movement_id`, `occurred_at`, `stock_after` |
| `MAINTENANCE_OUT_MISMATCH` | `high` | 완료 후 48시간이 지난 정비(최근 14일 완료분)의 필요 부품 연결 출고가 없거나 필요량의 절반 미만. 필요량은 정비 일정의 `required_parts`, 없으면 설비의 정비 1회당 수량 | `maintenance_id`, `completed_at`, `required_qty`, `linked_out_qty` |
| `PATTERN_DEVIATION` | `medium` | smooth 부품의 최근 연속 출고 없는 n주가 우연일 확률 exp(−λn) 1% 미만. λ는 그 전 기간의 주당 출고 횟수(정비 연결 출고 제외) | `zero_weeks`, `weekly_rate`, `probability` |
| `SPIKE` | `medium` | 최근 7일 출고 중 1회 수량이 그 전 출고 최대의 5배 초과 (확인 카드에서 확인한 건 포함) | `movement_id`, `occurred_at`, `qty`, `past_max_qty` |
| `COUNT_OVERDUE` | `low` | 마지막 실사 후 입출고 50건 이상 또는 90일 경과 | `last_counted_at`, `days_since`, `movements_since` |

- 같은 부품의 열린 항목(`open`, `count_requested`)은 하나다. 대표 규칙은 등급이 높은 것(같으면 규칙 번호 순)이고, 함께 걸린 규칙은 `related`에 담는다.
- 사건(원장 행·정비)을 가리키는 규칙(`NEGATIVE_STOCK`, `MAINTENANCE_OUT_MISMATCH`, `SPIKE`)은 같은 사건으로 한 번만 뜬다. 기록 직후 검사와 새벽 배치가 같은 원장 행을 가리켜 중복되지 않는다.
- `PATTERN_DEVIATION`, `COUNT_OVERDUE`는 닫힌 뒤 `system.count_suppress_days`(기본 30일) 동안 다시 뜨지 않는다.
- 근거의 시각은 Asia/Seoul 기준 ISO 8601이다.
- `COUNT_OVERDUE`의 마지막 실사는 가장 최근 실사 응답(AUD-03) 시각이다. 실사 기록이 없으면 원장 첫 기록일부터 센다(`last_counted_at: null`).

## AUD-01 GET /api/v1/audit-flags

- 권한: manager 이상. worker는 403 `FORBIDDEN_ROLE`.
- 정렬: 등급 높은 순(`high` → `medium` → `low`), 같은 등급은 최근 생성 순. 커서 목록.

| Query | 설명 |
| --- | --- |
| `status` | `open`, `count_requested`, `closed` |
| `level` | `high`, `medium`, `low` |
| `rule` | 위 규칙 코드 |
| `cursor`, `limit` | 공통 커서 규칙 |

```json
{
  "items": [
    {
      "id": "...",
      "part": { "id": "...", "name": "오링 P-20" },
      "rule": "MAINTENANCE_OUT_MISMATCH", "level": "high", "status": "open",
      "evidence": { "maintenance_id": "...", "completed_at": "2026-11-01T15:00:00+09:00", "required_qty": 100, "linked_out_qty": 0 },
      "related": [ { "rule": "COUNT_OVERDUE", "level": "low", "evidence": { "last_counted_at": null, "days_since": 91, "movements_since": 9 } } ],
      "created_at": "2026-11-04T03:00:00+09:00",
      "updated_at": "2026-11-04T03:00:00+09:00"
    }
  ],
  "next_cursor": null
}
```

- 열린 항목이 있는 부품은 부품 목록(SET-03)에서 `ledger_status: suspect`다.
- 기록 직후 음수 재고가 되면 CHAT-03·CHAT-05 응답의 `triggered.audit_flag_id`에 항목 ID가 담긴다.

## AUD-02 POST /api/v1/audit-flags/{id}/count-request

- 권한: manager 이상.
- 상태가 `open`인 의심 항목만 요청할 수 있다. 이미 요청했거나 닫힌 항목은 409 `ALREADY_CONFIRMED`(`detail.status`). 항목·담당자(같은 회사 활성 직원)가 없으면 404.
- 요청하면 의심 항목은 `count_requested`가 된다.

```json
// Request
{ "assignee_id": "..." }

// 201 Response
{
  "count_request_id": "...",
  "status": "sent",
  "scheduled_for": null,
  "message_preview": "오링 P-20 지금 몇 개 있나요? 세어서 숫자만 보내 주세요."
}
```

- 문구에 장부 수량을 넣지 않는다(블라인드 실사).
- 담당자 한 명에게 하루(Asia/Seoul) `system.count_per_worker_per_day`(기본 2)건까지 보낸다. 넘으면 `status: scheduled`이고, 한도가 남은 첫 날의 `notify.briefing_time`(기본 07:30)이 `scheduled_for`에 담긴다. 보낸 건과 예약한 건을 모두 그날 몫으로 센다.
- 현재 구현 범위: 담당자 채팅·웹 푸시 전달은 알림(NOT) 기능에서 연결한다. 예약 건은 `scheduled_for`가 지나면 응답할 수 있다.

## AUD-03 POST /api/v1/count-requests/{id}/answer

- 권한: 담당자 본인. 남의 요청과 예약 시각(`scheduled_for`) 전인 요청은 404.
- 이미 응답한 요청은 409 `ALREADY_CONFIRMED`(`detail.status`). `counted_qty`가 0 미만이면 400.

```json
// Request
{ "counted_qty": 940 }

// 200 Response (응답 후에야 차이를 보여줌)
{
  "adjust_movement_id": "...",
  "book_qty_before": 1040, "counted_qty": 940, "diff": -100,
  "reason_required": true,
  "reply": "장부보다 100개 적어요. 이유를 골라 주세요."
}
```

- 차이가 있으면 차이만큼 `ADJUST`(사유 `실사조정`, 작성자 담당자)를 원장에 더한다. 요청은 `answered`, 의심 항목은 사유(AUD-04)를 받을 때까지 `count_requested`로 둔다.
- 차이가 0이면 원장은 그대로(`adjust_movement_id: null`), 요청과 의심 항목을 닫는다(`resolution: no_diff`). 같은 규칙은 억제 기간 동안 다시 뜨지 않는다.
- 현재 구현 범위: 폼 경로만 구현했다. 채팅 답(의도 `COUNT`) 연결은 ai 해석 연동 후 추가한다.

## AUD-04 PATCH /api/v1/count-requests/{id}

- 권한: 담당자 본인(남의 요청은 404).
- 차이가 있어 사유를 기다리는 요청(`answered`)에만 쓴다. 응답 전·차이 0으로 닫힌 요청은 409 `ALREADY_CONFIRMED`(`detail.status`).

```json
// Request
{ "reason": "missing_record", "note": "정비 때 쓰고 기록 안 함" }

// 200 Response
{ "count_request_id": "...", "status": "closed", "audit_flag_status": "closed" }
```

- `reason`: `lost` 분실, `missing_record` 기록 누락, `damaged` 파손, `other` 기타. `note`는 선택, 500자 이하.
- 원장은 추가 전용이라 실사조정 행(사유 `실사조정`)은 그대로 두고 차이 사유는 실사 요청에 남긴다. 의심 항목은 `resolution: adjusted`로 닫힌다.
