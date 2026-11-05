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
- 현재 구현 범위: 실사 기록 전이라 `COUNT_OVERDUE`는 원장 첫 기록일부터 센다(`last_counted_at: null`).

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
