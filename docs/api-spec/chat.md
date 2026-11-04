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
| 위 조건에서 1회 수량 > 같은 부품·같은 방향 과거 1회 최대 × 5 | `warning` |
| 이름 일치 부품이 여럿 | `select` (`candidates`, 설비에 연결된 부품 먼저, 최대 3개) |
| 일치 부품 없음 | `unregistered` |
| 해석 실패 | `form` (`ai.fallback: true`, `ai.reason`) |

### 의도별 답변

| `intent` | 처리 |
| --- | --- |
| `OUT`, `IN` | 위 카드 |
| `QUERY` | 카드 없음. 부품이 하나면 재고와 계산 기준 시각, 여럿이면 후보 이름 |
| `OTHER` | 카드 없음. "기록, 조회, 발주 요청을 도와드려요." |
| `PURCHASE_REQUEST`, `MAINTENANCE_DONE`, `COUNT` | 현재 구현 범위: `OTHER`와 같은 안내. 검토·정비·실사 기능에서 연결 |

- 출고 수량이 장부 재고보다 많아도 기록은 허용한다. 음수 재고는 장부 검증에서 의심 항목으로 다룬다.
- 현재 구현 범위: 매칭은 별칭 정확 일치와 이름 부분 일치만 쓴다. 기능명세서 F-MATCH-01의 규격 필터·임베딩 의미 유사도·자모 철자 유사도(RRF)는 아직 없다.
- 현재 구현 범위: ai 채팅 해석 연동 전이라 기본 해석기(`UnconfiguredInterpreter`)가 항상 실패를 알리고, 모든 메시지는 `form` 카드(`reason: "error"`)로 대체된다. 별칭 후보 순위(ai)도 연동 후 매칭에 더한다.
- `QUERY` 답변의 입고 예정·소진 예상일은 발주·지표 계산 기능 이후 채운다.

| 상황 | 응답 |
| --- | --- |
| 500자 초과, 빈 본문 | 400 `VALIDATION_ERROR` |
| 분당 20회 초과 | 429 `RATE_LIMITED` |

## CHAT-03 POST /api/v1/chat/entries/{id}/confirm

- 권한: 카드 작성자. 다른 사람의 카드는 404.
- 선택·수정한 값(`part_id`, `qty`, `equipment_id`)만 보낸다. 비우면 카드의 값을 쓴다.
- `select` 카드는 후보 중 하나를 골라야 한다.
- 확정한 표현(`part_text`)이 부품 이름과 다르면 별칭으로 남긴다(`alias_learned`). 같은 표현이 여러 부품에 쓰이면 모두 모호로 표시해 자동 확정에서 뺀다.

```json
// Request
{ "part_id": "..." }

// 200 Response
{
  "intent": "OUT",
  "movement": { "id": "...", "type": "OUT", "part_id": "...", "qty": -2, "equipment_id": "...", "maintenance_id": null },
  "stock_after": 1,
  "reply": "출고 완료. 남은 재고 1개",
  "alias_learned": { "text": "베어링", "part_id": "..." },
  "triggered": { "draft_review_id": null, "audit_flag_id": null }
}
```

| 상황 | 응답 |
| --- | --- |
| 10분 지난 카드 | 410 `ENTRY_EXPIRED` |
| 이미 확정·취소된 카드 | 409 `ALREADY_CONFIRMED` (`detail.status`) |
| 부품 미선택, 후보 밖 부품 | 422 `PART_NOT_RESOLVED` |
| 수량 없음·1 미만, `form` 카드 | 400 `VALIDATION_ERROR` |
| 다른 사람의 카드, 없는 설비 | 404 `NOT_FOUND` |

- 현재 구현 범위: `OUT`·`IN`만 처리한다. `triggered`(재고 부족 초안·장부 의심), `IN`의 `po_match`·`actual_lead_time_days`는 검토·장부 검증·발주 기능에서 채운다.

## CHAT-04 POST /api/v1/chat/entries/{id}/cancel

- 권한: 카드 작성자. 원장은 바뀌지 않는다.

```json
// 200 Response
{ "entry_id": "...", "status": "cancelled" }
```

| 상황 | 응답 |
| --- | --- |
| 이미 확정·취소된 카드 | 409 `ALREADY_CONFIRMED` |
| 다른 사람의 카드 | 404 `NOT_FOUND` |

## CHAT-05 POST /api/v1/chat/entries

- 권한: 로그인한 모든 사용자. ai 해석이 실패했을 때(`form` 카드)의 대체 입력.
- 확인 카드 없이 바로 원장에 기록하고 CHAT-03과 같은 형식으로 응답한다. 기록은 `form` 유형의 확정 카드로 남는다.
- 같은 `client_message_id`로 다시 보내면 처음 응답을 돌려주고 원장에 다시 기록하지 않는다.

```json
// Request
{ "client_message_id": "f-20261104-0002", "type": "OUT", "part_id": "...", "qty": 2, "equipment_id": "..." }
```

| 상황 | 응답 |
| --- | --- |
| `type`이 `OUT`·`IN` 외, 수량 1 미만 | 400 `VALIDATION_ERROR` |
| 없는·병합된 부품 | 422 `PART_NOT_RESOLVED` |
| 없는 설비 | 404 `NOT_FOUND` |

- 현재 구현 범위: `OUT`·`IN`만. 폼 발주 요청(`PURCHASE_REQUEST`)은 검토 기능에서 추가한다.
