# 채팅 기록 API

## CHAT-01 POST /api/v1/chat/messages

- 권한: 로그인한 모든 사용자. 사용자당 분당 20회, 본문 500자 이하.
- 처리: 해석(`Interpreter`) → 부품 매칭(server 규칙) → 확인 카드. 카드는 10분 뒤 만료된다.
- 회사·작업 종류·`client_message_id`가 같은 요청은 요청자와 정규화된 본문이 같을 때만 처음 응답을 돌려준다. 요청자 또는 본문이 다르면 409를 반환한다.

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

- `AI_BASE_URL`이 있으면 ai `/v1/chat/parse`로 해석한다. 품목이 여럿이면 `OUT`·`IN`은 품목마다 카드를 하나씩 만들고(`cards` 순서 = 품목 순서) 답변은 품목별 문장을 줄바꿈으로 잇는다. 카드는 하나씩 확정·취소한다. 그 밖의 의도는 첫 품목만 쓴다.
- 단위가 박스(`박스`, `box`, `상자`)면 부품 입수량(`pack_qty`)을 곱한다. 입수량이 없으면 수량을 비워 확인할 때 입력받는다. 선택 카드는 고른 부품의 입수량으로 바꾼다.
- ai 호출마다 `llm_calls`에 용도·모델·토큰·지연·시도 횟수·성공 여부를 남긴다.

### 카드 결정 (`OUT`, `IN`)

| 조건 | 카드 |
| --- | --- |
| 확정(별칭 일치, 규격 일치 후보 1개, 또는 코사인 확정) | `confirm` (`part_id`, `name`, `stock`, `unit`) |
| 위 조건에서 1회 수량 > 같은 부품·같은 방향 과거 1회 최대 × 5 | `warning` |

- `IN`의 `confirm`·`warning` 카드는 `po_match` 미리 보기를 담는다. 확정(CHAT-03)과 같은 규칙(남은 수량이 입고 수량과 같은 열린 발주 먼저, 없으면 가장 오래된 승인)으로 고르되 발주를 바꾸거나 알림을 보내지 않는다. 카드에는 공급사·단가가 없어 수량만 비교한다. 수량이 없거나 `OUT`이면 `null`. 실제 결과는 확정 응답의 `po_match`가 정본이다.

| 확정은 아니지만 후보가 있음 (하나여도) | `select` (`candidates`, 설비에 연결된 부품 먼저, 최대 3개) |
| 후보 없음 | `unregistered` |
| 해석 실패 | `form` (`ai.fallback: true`, `ai.reason`) |

### 의도별 답변

| `intent` | 처리 |
| --- | --- |
| `OUT`, `IN` | 위 카드 |
| `QUERY` | 카드 없음. 부품이 하나면 현재 재고·입고 예정·소진 예상일과 각 기준 시각, 여럿이면 후보 이름 |
| `OTHER` | 카드 없음. "기록, 조회, 발주 요청을 도와드려요." |
| `MAINTENANCE_DONE` | 설비의 가장 가까운 미완료 정비(오늘과 예정일 차이가 가장 작은 것, 같으면 앞선 일정)를 `confirm` 카드(`maintenance: {id, scheduled_date}`)로 보여준다. 설비를 모르면 "어느 설비의 정비인지 알려 주세요.", 미완료 정비가 없으면 안내만 한다 |
| `COUNT` | 카드 없음. 담당자 본인의 응답 대기 실사 요청에 AUD-03과 같은 처리. 응답의 `count_request_id`로 차이 사유(AUD-04)를 보낸다 |
| `PURCHASE_REQUEST` | 부품이 확정되면 `confirm` 카드(`part_id`, `qty`, `unit_price`, `supplier_resolution`), 후보만 있으면 `select` 카드, 없으면 카드 없이 미등록 안내 |

- `PURCHASE_REQUEST` 공급사 해석 `supplier_resolution: { text, supplier_id, name, method }`: 공급사 이름이 표현을 포함하면(또는 그 반대) `named`(이 부품을 파는 곳 먼저), "저번 데"·"늘 사던 곳"처럼 최근 발주처를 가리키면 이 부품을 가장 최근에 승인한 발주(취소 제외)의 공급사 `last_order`, 발주 이력이 없거나 표현이 없으면 기본 공급사 `default`, 해석하지 못하면 `none`.
- 답변 예: "V벨트 A-42 30개, 공급사 A로 요청하셨나요?"

- `COUNT`: 응답 대기 요청이 없으면 "답할 실사 요청이 없어요.", 수량이 없으면 "센 수량을 숫자로 알려 주세요.". 요청이 여럿이면 부품 표현으로 고르고, 고르지 못하면 후보 이름을 되묻는다. 응답 전에는 원장을 바꾸지 않는다.
- `count_request_id`는 `COUNT`로 실사 요청에 응답했을 때만 담기고 그 밖에는 `null`이다.
- 출고 수량이 장부 재고보다 많아도 기록은 허용한다. 음수 재고는 장부 검증에서 의심 항목으로 다룬다.
- 현재 구현 범위: ai 채팅 해석 연동 전이라 기본 해석기(`UnconfiguredInterpreter`)가 항상 실패를 알리고, 모든 메시지는 `form` 카드(`reason: "error"`)로 대체된다. 별칭 후보 순위(ai)도 연동 후 매칭에 더한다.
- `QUERY` 답변 예: "V벨트 A-42 현재 재고 2개예요. 입고 예정 10개(11/08쯤). 소진 예상일은 11/18이에요. (재고 기준 11/04 10:00, 예상 계산 11/04 03:00)". 재고는 원장 합산(요청 시각), 소진 예상일은 최신 새벽 계산(`part_metrics.t_out`) 값이다.
- 새벽 계산 전이면 "소진 예상일은 새벽 계산 뒤에 알려 드려요", 8주 경로 시뮬레이션 안에 소진되지 않으면 "앞으로 8주 안에는 다 쓰지 않을 것으로 보여요"라고 답한다.
- 입고 예정: 열린 발주(승인됨·발주됨·부분입고)의 미입고 수량 합과 가장 이른 도착 예상일. 예상일은 주문 완료 시각(주문 전이면 승인 시각) + 공급사 LT50(최신 공급사별 납기, 없으면 공급사 기본 납기, 그것도 없으면 7일). 주문 전 발주가 있으면 "그중 N건은 아직 주문 전이에요."를 덧붙이고, 열린 발주가 없으면 "입고 예정은 없어요."

| 상황 | 응답 |
| --- | --- |
| 500자 초과, 빈 본문 | 400 `VALIDATION_ERROR` |
| 분당 20회 초과 | 429 `RATE_LIMITED` |
| 같은 요청 ID의 다른 요청자·본문 또는 소유자를 확인할 수 없는 기존 기록 | 409 `IDEMPOTENCY_CONFLICT` |

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
  "movement": { "id": "...", "type": "OUT", "part_id": "...", "qty": -2, "equipment_id": "...", "maintenance_id": null, "po_id": null },
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

- `triggered.draft_review_id`: 이 기록으로 재주문점을 벗어나 만든 재고 부족 초안 검토 ID(F-LEDGER-03). 조건은 S + H_c ≤ 재주문점(최신 새벽 계산), 같은 부품의 열린 발주·열린 요청 없음, 오늘 '발주 불필요'로 닫힌 검토 없음. 원안은 수량 R, 기본 공급사. 새벽 계산 전이거나 R이 0이면 만들지 않는다. 검토는 응답 커밋 뒤 백그라운드로 돈다([reviews.md](reviews.md)).
- `triggered.audit_flag_id`: 이 기록으로 재고가 0 이상에서 0 미만이 되면 만든(또는 묶은) 장부 의심 항목 ID ([audit.md](audit.md)).
- `IN`은 같은 부품의 열린 발주와 대조한다(F-LEDGER-04, #164). 잔량이 입고 수량과 같은 발주를 먼저, 없으면 가장 오래된 승인을 고르고 원장 `movement.po_id`에 연결한다.
  - `po_match`: `complete`(발주 수량 채움, `received`), `partial`(`partially_received`, 잔량 유지), `mismatch`(잔량보다 많이 들어옴, 입고는 반영하고 관리자·사장님에게 `receipt_check` 알림), `no_order`(열린 발주 없음). `OUT`은 `null`.
  - `actual_lead_time_days`: 이번 입고로 발주를 채웠을 때 주문 완료 시각부터 입고까지 일수. 주문 완료 표시 없이 입고되면 서버가 `ordered`로 바꾸고(`implicit_order`) 납기 표본에서 빼서 `null`.
- `MAINTENANCE_DONE` 카드 확정은 SET-09와 같이 완료자·완료 시각(확정 시각)을 남기고 `{ "intent": "MAINTENANCE_DONE", "maintenance_id", "equipment_id", "completed_at", "reply": "정비 완료로 기록했어요." }`를 돌려준다. 이미 완료된 정비는 409 `ALREADY_CONFIRMED`(`detail.status: completed`).
- `PURCHASE_REQUEST` 카드 확정은 직원 요청 검토(`entry: staff_request`, 요청자 본인, 원본 메시지 연결)를 만들고 `{ "intent": "PURCHASE_REQUEST", "review_id", "status": "reviewing", "reply": "검토해서 사장님께 올렸어요." }`를 돌려준다. 검토는 커밋 뒤 실행된다(`review.progress` 이벤트). 요청에서 `part_id`(선택 카드), `qty`, `supplier_id`, `unit_price`를 바꿀 수 있다. 공급사가 비면 검토가 기본 공급사를, 단가가 비면 등록 단가를 쓴다. 선택 카드는 고른 부품의 기본 공급사를 쓴다. 없는 공급사는 404.
- 현재 구현 범위: `OUT`·`IN`·`MAINTENANCE_DONE`·`PURCHASE_REQUEST`를 처리한다. `IN`은 열린 발주와 대조해 `po_match`·`actual_lead_time_days`를 채운다.
- 확인 카드 확정과 폼 입력은 같은 회사·부품의 원장 추가와 재고 합산을 트랜잭션 단위로 직렬화한다. `stock_after`는 해당 요청이 반영된 시점의 합산값이며, 이후 다른 요청이 재고를 바꿀 수 있다.

### 재고 동시성 검증 (#69)

- 격리된 PostgreSQL 16과 API 서버에서 `curl`로 폼 동시 출고 12건, 입고·출고 16건의 응답 및 원장 합계 확인.
- 테스트용 확인 카드 6건의 `curl` 동시 확정과 응답 재고 순서 확인. 실제 AI 해석을 통한 카드 생성은 검증 범위 밖.
- 한 부품의 잠금을 유지하는 동안 같은 부품 요청은 대기하고 다른 부품 요청은 처리됨을 확인.
- 원장 추가 직후 트랜잭션을 롤백했을 때 이벤트 수와 재고 합계 복원 확인. 수량 0 요청의 400 응답과 원장 합계 유지 확인.
- 기존 채팅 확정·폼 입력 테스트 21개 통과. 검증 환경은 별도 설치한 패키지를 사용했으며 `uv.lock` 고정 환경은 미검증.

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
- 회사·작업 종류·`client_message_id`가 같고 요청자와 정규화된 본문도 같으면 처음 응답을 돌려주고 원장에 다시 기록하지 않는다. 요청자 또는 본문이 다르면 409를 반환한다.

```json
// Request
{ "client_message_id": "f-20261104-0002", "type": "OUT", "part_id": "...", "qty": 2, "equipment_id": "..." }
```

| 상황 | 응답 |
| --- | --- |
| `type`이 `OUT`·`IN` 외, 수량 1 미만 | 400 `VALIDATION_ERROR` |
| 없는·병합된 부품 | 422 `PART_NOT_RESOLVED` |
| 없는 설비 | 404 `NOT_FOUND` |
| 같은 요청 ID의 다른 요청자·본문 또는 소유자를 확인할 수 없는 기존 기록 | 409 `IDEMPOTENCY_CONFLICT` |

- 폼 발주 요청: `{ "client_message_id", "type": "PURCHASE_REQUEST", "part_id", "qty", "supplier_id", "unit_price" }`(`supplier_id`·`unit_price` 선택). 응답은 CHAT-03 발주 요청과 같고, 같은 `client_message_id`로 다시 보내면 검토를 다시 만들지 않는다.

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

## 멱등성 변경 검증 (Issue #68)

- PostgreSQL 격리 DB에서 서버 테스트 139개 통과 및 동시 요청 테스트 6개 통과. 동시 요청은 채팅·폼별 동일 요청, 다른 본문, 다른 사용자를 각각 확인했다.
- 실제 HTTP `curl`로 채팅·폼 각각 최초 요청 200, 동일 요청 재시도의 동일 JSON, 다른 본문과 다른 사용자 요청의 409 `IDEMPOTENCY_CONFLICT`를 확인했다.
- Docker Compose server·ai 이미지 빌드 통과. 운영 DB 마이그레이션 및 서비스 배포는 검증하지 않았다.
- 테스트는 격리 PostgreSQL 16 Alpine의 `C` 로케일을 사용했다. 기존 멱등 기록은 요청자와 요청 본문 해시가 없어 안전하게 재생을 거부하며, 새 요청 ID가 필요하다.
