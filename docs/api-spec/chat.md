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

### 부품 매칭 (기능명세서 F-MATCH-01)

1. 정규화: 대소문자·전각·공백·기호 통일, 규격 구분자 통일(`M8-20`, `M8*20`, `M8 x 20` → `m8x20`)
2. 별칭 일치: 모호하지 않은 확정 별칭이 한 부품과 정확히 일치하면 확정
3. 규격 필터: 표현에서 규격(베어링 형번·실드, 볼트 지름·길이, V벨트 형·길이, 오링 호칭, 용량)을 뽑아 `parts.spec`과 비교. 같은 키의 값이 다르면 이름이 비슷해도 후보에서 뺀다(6205ZZ ≠ 6205-2RS, M8x20 ≠ M8x30). 뽑은 규격이 모두 같은 후보가 하나면 확정
4. 의미 유사도: 부품 표현을 ai `/v1/embeddings`(`task: query`)로 벡터로 바꿔 이름·별칭 벡터(같은 모델, 모호 별칭 제외)와 코사인 거리 상위 10개
5. 철자 유사도: 자모 분해 3-gram Jaccard(이름·별칭 중 최댓값). 0.2 미만이거나 1위 점수의 절반 미만인 후보는 뺀다
6. 결합: 4와 5의 순위를 RRF(k = 60)로 합친다. 규격 일치 후보가 먼저다. 철자 기준에 들지 않은 후보는 코사인 0.5 이상일 때만 넣는다(`reason: semantic`)

- 확정: 별칭 일치, 규격 일치 후보 1개, 또는 RRF 1위의 코사인 ≥ `system.match_confirm_cosine`(0.85)이면서 2위보다 `match_confirm_gap`(0.05) 이상 높을 때
- 의미 유사도 후보 기준 0.5는 명세에 없는 초깃값이다(F-SIM 조정 대상).
- ai 미설정·실패·시간 초과(2초)면 4·6단계 없이 규격 일치 → 철자 유사도 순으로 정한다.

### 해석과 단위

- `AI_BASE_URL`이 있으면 ai `/v1/chat/parse`로 해석한다. 품목이 여럿이면 첫 품목만 쓴다(여러 품목 카드는 후속).
- 단위가 박스(`박스`, `box`, `상자`)면 부품 입수량(`pack_qty`)을 곱한다. 입수량이 없으면 수량을 비워 확인할 때 입력받는다. 선택 카드는 고른 부품의 입수량으로 바꾼다.
- ai 호출마다 `llm_calls`에 용도·모델·토큰·지연·시도 횟수·성공 여부를 남긴다.

### 카드 결정 (`OUT`, `IN`)

| 조건 | 카드 |
| --- | --- |
| 확정(별칭 일치, 규격 일치 후보 1개, 또는 코사인 확정) | `confirm` (`part_id`, `name`, `stock`, `unit`) |
| 위 조건에서 1회 수량 > 같은 부품·같은 방향 과거 1회 최대 × 5 | `warning` |
| 확정은 아니지만 후보가 있음 (하나여도) | `select` (`candidates`, 설비에 연결된 부품 먼저, 최대 3개) |
| 후보 없음 | `unregistered` |
| 해석 실패 | `form` (`ai.fallback: true`, `ai.reason`) |

### 의도별 답변

| `intent` | 처리 |
| --- | --- |
| `OUT`, `IN` | 위 카드 |
| `QUERY` | 카드 없음. 부품이 하나면 현재 재고·소진 예상일과 각 기준 시각, 여럿이면 후보 이름 |
| `OTHER` | 카드 없음. "기록, 조회, 발주 요청을 도와드려요." |
| `COUNT` | 카드 없음. 담당자 본인의 응답 대기 실사 요청에 AUD-03과 같은 처리. 응답의 `count_request_id`로 차이 사유(AUD-04)를 보낸다 |
| `PURCHASE_REQUEST`, `MAINTENANCE_DONE` | 현재 구현 범위: `OTHER`와 같은 안내. 검토·정비 기능에서 연결 |

- `COUNT`: 응답 대기 요청이 없으면 "답할 실사 요청이 없어요.", 수량이 없으면 "센 수량을 숫자로 알려 주세요.". 요청이 여럿이면 부품 표현으로 고르고, 고르지 못하면 후보 이름을 되묻는다. 응답 전에는 원장을 바꾸지 않는다.
- `count_request_id`는 `COUNT`로 실사 요청에 응답했을 때만 담기고 그 밖에는 `null`이다.
- 출고 수량이 장부 재고보다 많아도 기록은 허용한다. 음수 재고는 장부 검증에서 의심 항목으로 다룬다.
- 현재 구현 범위: ai 채팅 해석 연동 전이라 기본 해석기(`UnconfiguredInterpreter`)가 항상 실패를 알리고, 모든 메시지는 `form` 카드(`reason: "error"`)로 대체된다. 별칭 후보 순위(ai)도 연동 후 매칭에 더한다.
- `QUERY` 답변 예: "V벨트 A-42 현재 재고 2개예요. 소진 예상일은 11/18이에요. (재고 기준 11/04 10:00, 예상 계산 11/04 03:00)". 재고는 원장 합산(요청 시각), 소진 예상일은 최신 새벽 계산(`part_metrics.t_out`) 값이다.
- 새벽 계산 전이면 "소진 예상일은 새벽 계산 뒤에 알려 드려요", 8주 경로 시뮬레이션 안에 소진되지 않으면 "앞으로 8주 안에는 다 쓰지 않을 것으로 보여요"라고 답한다.
- 현재 구현 범위: `QUERY` 답변의 입고 예정은 발주 기능 이후 채운다.

| 상황 | 응답 |
| --- | --- |
| 500자 초과, 빈 본문 | 400 `VALIDATION_ERROR` |
| 분당 20회 초과 | 429 `RATE_LIMITED` |

## CHAT-03 POST /api/v1/chat/entries/{id}/confirm

- 권한: 카드 작성자. 다른 사람의 카드는 404.
- 선택·수정한 값(`part_id`, `qty`, `equipment_id`)만 보낸다. 비우면 카드의 값을 쓴다.
- `select` 카드는 후보 중 하나를 골라야 한다.
- 설비가 있는 출고는 그 설비의 정비에 자동 연결한다(`maintenance_id`, F-LEDGER-03). 예정일 ±1일(Asia/Seoul 날짜) 안이거나 완료 후 48시간 안인 정비 중 가장 가까운 것. 폼 입력(CHAT-05)도 같다.
- 원장 기록(`movements.message_id`)에 원본 채팅 메시지를 연결한다. 폼 입력(CHAT-05)은 메시지가 없어 `null`.
- 확정한 표현(`part_text`)이 부품 이름과 다르면 별칭으로 남긴다(`alias_learned`). 같은 표현이 가장 많이 확정된 부품이 아닌 다른 부품으로 2회 이상 확정되면 그 표현의 별칭을 모두 모호로 표시해 자동 확정에서 뺀다(F-MATCH-02). 모호 표시 전이라도 같은 표현의 별칭이 두 부품 이상이면 자동 확정하지 않고 선택 카드를 띄운다.

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

- `triggered.audit_flag_id`: 이 기록으로 재고가 0 이상에서 0 미만이 되면 만든(또는 묶은) 장부 의심 항목 ID ([audit.md](audit.md)).
- 현재 구현 범위: `OUT`·`IN`만 처리한다. `triggered.draft_review_id`(재고 부족 초안), `IN`의 `po_match`·`actual_lead_time_days`는 검토·발주 기능에서 채운다.

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

## CHAT-02 GET /api/v1/chat/messages

- 권한: 본인 이력만. 최신순 커서 목록(`?cursor=&limit=`).
- 카드 상태: `open`, `confirmed`, `cancelled`, `expired`(열린 채 10분이 지난 카드).

```json
{
  "items": [
    {
      "message_id": "...", "client_message_id": "m-20261104-0007",
      "text": "3호기 베어링 두 개 씀", "intent": "OUT", "reply": "어떤 베어링인가요?",
      "created_at": "2026-11-04T10:10:00+09:00",
      "cards": [ { "entry_id": "...", "type": "select", "status": "confirmed", "expires_at": "2026-11-04T10:20:00+09:00" } ]
    }
  ],
  "next_cursor": null
}
```

- 폼 입력(CHAT-05)은 메시지가 없어 이 목록에 나오지 않는다.
