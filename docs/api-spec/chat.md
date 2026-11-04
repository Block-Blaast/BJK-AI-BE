# 채팅 기록 API

## CHAT-01 POST /api/v1/chat/messages

- 권한: 로그인한 모든 사용자. 사용자당 분당 20회, 본문 500자 이하.
- 처리: 해석(`Interpreter`) → 부품 매칭(server 규칙) → 확인 카드. 카드는 10분 뒤 만료된다.
- 같은 `client_message_id`로 다시 보내면 처음 응답을 그대로 돌려준다.

```json
// Request
{ "client_message_id": "m-20261104-0007", "text": "3호기 베어링 두 개 씀" }

// 200 Response
{
  "message_id": "...",
  "intent": "OUT",
  "reply": "어떤 베어링인가요?",
  "cards": [
    {
      "type": "select", "entry_id": "...", "intent": "OUT",
      "part_text": "베어링", "qty": 2, "equipment": { "id": "...", "name": "3호기" },
      "part_id": null, "name": null, "stock": null, "unit": null,
      "candidates": [
        { "part_id": "...", "name": "볼베어링 6205ZZ", "stock": 3, "reason": "equipment_part" },
        { "part_id": "...", "name": "볼베어링 6204ZZ", "stock": 12, "reason": "name" }
      ],
      "expires_at": "2026-11-04T10:20:00+09:00"
    }
  ],
  "ai": { "used": true, "fallback": false, "reason": null }
}
```

### 카드 결정 (`OUT`, `IN`)

| 조건 | 카드 |
| --- | --- |
| 확정 별칭이 한 부품과 일치, 또는 이름 일치 부품이 하나 | `confirm` (`part_id`, `name`, `stock`, `unit`) |
| 위 조건에서 출고 수량 > 장부 재고 | `warning` |
| 이름 일치 부품이 여럿 | `select` (`candidates`, 설비에 연결된 부품 먼저, 최대 5개) |
| 일치 부품 없음 | `unregistered` |
| 해석 실패 | `form` (`ai.fallback: true`, `ai.reason`) |

### 의도별 답변

| `intent` | 처리 |
| --- | --- |
| `OUT`, `IN` | 위 카드 |
| `QUERY` | 카드 없음. 부품이 하나면 재고와 계산 기준 시각, 여럿이면 후보 이름 |
| `OTHER` | 카드 없음. "기록, 조회, 발주 요청을 도와드려요." |
| `PURCHASE_REQUEST`, `MAINTENANCE_DONE`, `COUNT` | 현재 구현 범위: `OTHER`와 같은 안내. 검토·정비·실사 기능에서 연결 |

- 현재 구현 범위: ai 채팅 해석 연동 전이라 기본 해석기(`UnconfiguredInterpreter`)가 항상 실패를 알리고, 모든 메시지는 `form` 카드(`reason: "error"`)로 대체된다. 별칭 후보 순위(ai)도 연동 후 매칭에 더한다.
- `QUERY` 답변의 입고 예정·소진 예상일은 발주·지표 계산 기능 이후 채운다.

| 상황 | 응답 |
| --- | --- |
| 500자 초과, 빈 본문 | 400 `VALIDATION_ERROR` |
| 분당 20회 초과 | 429 `RATE_LIMITED` |
