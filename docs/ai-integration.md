# server ↔ AI 연동 안내

server에서 AI 기능(ai 서비스 HTTP 엔드포인트 4개, 검토 엔진 `bjk_review`)을 붙이는 방법이다. 계약은 `packages/contracts`(`bjk_contracts`), 검토 엔진은 `packages/review`(`bjk_review`)가 정본이고, 이 문서는 그 사용법이다. 기능 규칙은 `about_project/01-functional-spec.md`, API는 `02-api-spec.md`를 따른다.

## 0. 역할 나눔

| 하는 쪽 | 일 |
| --- | --- |
| ai 서비스 (`apps/ai`, HTTP) | LLM 3곳(채팅 해석, 엑셀 규격·카테고리 제안, 의견서 문장)과 부품 이름 임베딩. Bedrock(Claude, Titan V2) 우선, Gemini는 LLM 폴백 |
| 검토 엔진 (`bjk_review`, server 프로세스 안) | LangGraph 검토 흐름, 보류·체크 9개·수정안·판정, 의견서 검증·양식 의견서, 재검토, 후속 질문 양식 답변 |
| server | DB 조회·저장, 매칭(규격·철자·임베딩 결합), 확인 카드, 원장, 스냅샷 수집, 검토 저장·상태·승인, SSE, `llm_calls` 기록, 회사별 토큰 상한 |

결정 사항:

- **검토 엔진은 `bjk_review`를 쓴다.** server에서 체크·수정안·판정을 다시 만들지 않는다(server 할 일 7번의 엔진 부분). server는 스냅샷 수집과 저장, REV API를 만든다.
- **LLM은 매칭 순위를 매기지 않는다**(F-MATCH-01, #21 종료). `CLAUDE.md`의 "별칭 후보 순위"는 옛 문구다.
- **임베딩은 1024차원**(`bjk_contracts.EMBEDDING_DIM`). server DB `vector(1536)`(마이그레이션 0012)을 `vector(1024)`로 바꿔야 한다.

## 1. 공통

### 연결

- 주소: compose 안에서는 `http://ai:8001`, 로컬은 `http://localhost:8001`. server 설정에 `AI_BASE_URL`을 추가해 넣는다.
- server는 동기라 `httpx.Client`를 쓴다(`httpx`를 `apps/server` 런타임 의존성에 추가). 클라이언트 타임아웃은 ai 쪽 예산보다 조금 길게: 채팅 3초, 임베딩 12초, 의견서 4초, 이관 제안 35초.
- ai는 LLM이 실패해도 **200**과 대체 응답을 준다. 오류 응답은 입력 형식 오류(422)뿐이다. HTTP 자체가 실패(연결 거부, 타임아웃)하면 server가 같은 대체 경로로 간다.

### 응답 공통 필드

```json
"ai": { "used": true, "fallback": false, "reason": null },
"usage": { "purpose": "chat_parse", "model": "anthropic.claude-haiku-4-5", "input_tokens": 450,
           "output_tokens": 60, "latency_ms": 980, "attempts": 1, "success": true }
```

- `ai`는 API 명세서 1-6의 `ai` 객체와 같다. 클라이언트 응답에 그대로 붙인다. `reason`: `timeout`, `error`, `schema_invalid`, `quota_exceeded`, `verify_failed`.
- `usage`는 `llm_calls`에 한 줄로 저장한다(용도, 모델, 토큰, 지연, 시도 횟수, 성공). 호출하지 못했으면 `null`.
- 회사별 일일 토큰 상한은 server가 `llm_calls` 합계로 판단한다. 넘었으면 ai를 부르지 않고 `{"used": false, "fallback": true, "reason": "quota_exceeded"}`로 대체한다.

### 상태 확인

`GET /health` → `{"status": "ok", "llm": "ok" | "not_configured"}`. server `/api/v1/health`의 `llm`은 이 값을 쓴다(연결 실패면 `not_configured`나 `error`로).

## 2. 채팅 해석 `POST /v1/chat/parse` (F-CHAT-01, CHAT-01)

```json
// 요청
{ "company_id": "uuid", "text": "3호기 베어링 두 개 씀" }        // 500자 이하
// 응답
{ "intent": "OUT",
  "items": [ { "part_text": "베어링", "qty": 2, "unit": "개", "equipment_text": "3호기",
               "supplier_text": null, "unit_price": null, "note": null } ],
  "ai": {...}, "usage": {...} }
```

- `intent`: `OUT`, `IN`, `COUNT`, `QUERY`, `PURCHASE_REQUEST`, `MAINTENANCE_DONE`, `OTHER`. 실패면 `intent: null`, `items: []`, `ai.fallback: true` → 폼 입력 카드(F-CHAT-07).
- 표현만 뽑는다. 부품 매칭, "저번 데" 공급사 해석, 박스 → 개 환산, 되묻기는 server.
- 품목이 여럿이면 `items`에 나뉘어 온다("볼트 200개, 너트 200개 씀"). server의 `Interpretation`이 품목 하나라 처음에는 첫 품목만 쓰고, 여러 품목 카드는 후속으로 한다.

server 포트(`bjk_server/chat/interpreter.py`)에 붙이는 예:

```python
import httpx
from bjk_contracts import ChatParseRequest, ChatParseResponse


class AiInterpreter:
    def __init__(self, client: httpx.Client, company_id: uuid.UUID) -> None:
        self._client, self._company_id = client, company_id

    def interpret(self, text: str) -> Interpretation:
        body = ChatParseRequest(company_id=self._company_id, text=text).model_dump(mode="json")
        try:
            response = self._client.post("/v1/chat/parse", json=body, timeout=3.0)
            response.raise_for_status()
        except httpx.TimeoutException:
            raise InterpreterUnavailable("timeout") from None
        except httpx.HTTPError:
            raise InterpreterUnavailable("error") from None
        parsed = ChatParseResponse.model_validate(response.json())
        if parsed.ai.fallback or parsed.intent is None:
            raise InterpreterUnavailable(parsed.ai.reason or "error")
        first = parsed.items[0] if parsed.items else None
        return Interpretation(
            intent=parsed.intent.value,
            part_text=first and first.part_text,
            qty=first and first.qty,
            equipment_text=first and first.equipment_text,
            supplier_text=first and first.supplier_text,
        )
```

- `get_interpreter`는 요청 사용자 회사(`company_id`)를 넣어 만든다. `usage`를 `llm_calls`에 남기려면 `Interpretation`에 `usage`를 더하거나 포트가 함께 돌려주게 한다.
- `FailureReason`에는 `verify_failed`가 없지만 채팅 해석은 그 값을 쓰지 않는다.

## 3. 임베딩 `POST /v1/embeddings` (F-SETUP-02 5단계, F-MATCH-01 4단계, F-MATCH-03)

```json
// 요청: 한 번에 1~100개, 텍스트 하나 500자 이하
{ "company_id": "uuid", "task": "document", "texts": ["육각볼트 M8-20", "헥사볼트 M8×20"] }
// 응답: vectors[i]는 texts[i]의 1024차원 L2 정규화 벡터
{ "model": "amazon.titan-embed-text-v2:0", "vectors": [[...], [...]], "ai": {...}, "usage": {...} }
```

- `task`: 부품 이름·별칭을 저장할 때 `document`, 채팅 부품 표현으로 찾을 때 `query`.
- 저장: `parts.embedding`, `part_aliases.embedding`에 벡터를, `embedding_model`에 응답의 `model`을 함께 넣는다.
- **모델이 다른 벡터끼리 비교하지 않는다.** 검색 때 `embedding_model = <질의 벡터의 model>`인 행만 본다. ai는 임베딩을 다른 제공자로 대신하지 않는다(실패하면 `vectors: null`, 대체 응답). 그때 server는 규격 필터 + 철자 유사도만으로 매칭한다.
- 벡터가 정규화돼 있어 코사인 유사도 = 내적. pgvector는 `embedding <=> :query`(코사인 거리 = 1 − 유사도)로 상위 10개(F-MATCH-01 4단계), 이후 철자 유사도와 RRF 결합, 확정은 코사인 ≥ `match_confirm_cosine`(0.85)·차이 ≥ `match_confirm_gap`(0.05).
- 등록·엑셀 확정·별칭 학습 때 저장용으로 묶어 부르고, 주간 `weekly-merge`는 저장된 벡터로 비교한다.

## 4. 엑셀 이관 제안 `POST /v1/imports/suggest` (F-SETUP-02, SET-01)

```json
// 요청: 최대 200줄, row 번호 중복 불가. categories는 그 회사 등록 카테고리
{ "company_id": "uuid",
  "categories": [ { "id": "cat-bolt", "name": "볼트·너트" } ],
  "rows": [ { "row": 2, "name": "육각볼트 M8-20", "spec_text": null } ] }
// 응답: 요청 줄 순서대로
{ "suggestions": [ { "row": 2, "spec": { "thread": "M8", "length_mm": "20" },
                     "category_id": "cat-bolt", "confidence": 0.95 } ],
  "ai": {...}, "usage": {...} }
```

- `spec` 키는 `bjk_contracts.SPEC_KEYS`(server `domain/matching.py`의 `_SPEC_PATTERNS`와 같은 키), 값은 공백·하이픈을 뺀 대문자.
- 목록에 없는 카테고리는 제안하지 않는다(`category_id: null`, `confidence: 0`). SET-01 `suggested_category`는 `{id, name, confidence}`로 만들고, 확신도 낮은 줄을 위로 정렬한다.
- 실패면 `suggestions: null` → 규격은 정규식(`extract_spec`)만, `suggested_category: null`(F-SETUP-02 3번).
- 정규식 규격과 합치는 규칙은 server가 정한다. 제안: 정규식이 찾은 키는 정규식 값, 나머지 키는 ai 값. 둘이 다르면 그 줄 확신도를 낮춰 위로 올린다.

## 5. 검토 (F-REVIEW-01~10, REV-01~06)

### 5-1. 준비

- `apps/server/pyproject.toml` 의존성에 `bjk-review` 추가(워크스페이스 소스는 루트에 등록돼 있음). Docker 이미지는 `COPY packages`로 이미 포함한다.
- 검토 한 건은 아래 한 번의 호출로 끝난다. 동기 함수라 server 요청 처리 안에서 바로 부르거나, 응답을 먼저 주고(`reviewing`) 백그라운드에서 돌린다(검토 10초 이내).

```python
from bjk_review import OrderRequest, ReviewDeps, ReviewSettings, run_review_flow

deps = ReviewDeps(
    load_snapshot=lambda part_id, order: collect_snapshot(db, company_id, part_id, order),
    write_opinion=lambda request: call_ai_opinion(client, request),  # 예외 대신 실패면 None
)
outcome = run_review_flow(
    deps,
    company_id=company_id,
    entry="staff_request",  # stock_draft, missed_draft
    part_id=str(part_id),
    order=OrderRequest(qty=30, supplier_id=str(supplier_id), unit_price=18000),
    settings=review_settings(company_settings),
    on_progress=lambda step: publish_sse(review_id, step),  # review.progress {review_id, step}
)
# outcome.snapshot, outcome.result(판정), outcome.opinion(의견서)
```

- `on_progress`는 `interpret`, `snapshot`, `hold_check`, `checks`, `proposal`, `verdict`, `opinion`, `verify`, `done`을 차례로 넘긴다. 재작성하면 `opinion`·`verify`가 반복되고, 보류면 `checks`·`proposal`이 빠진다. 단계는 노드가 끝난 시점에 온다.
- `write_opinion`은 `/v1/opinions`를 부르고 `OpinionResponse`를 돌려준다. 실패·타임아웃은 `None`. 응답 `usage`는 `outcome.opinion.usages`에 모인다 → `llm_calls`.
- 확인 카드를 거친 직원 요청과 시스템 초안은 `order`·`part_id`를 넘긴다. 원문만 있으면 `text`와 `ReviewDeps(interpret=...)`를 넣는다(채팅 해석 + 매칭 + 공급사 표현 해석 결과를 `Interpreted(part_id, order)`로).

### 5-2. 스냅샷 수집 `collect_snapshot` → `bjk_review.ReviewSnapshot`

근거 고정(F-REVIEW-02). 검토 시점 값으로 모아 저장하고, 이후 재검토·질문은 저장한 스냅샷으로 한다.

| 필드 | 출처(server) | 지금 상태 |
| --- | --- | --- |
| `as_of` | 오늘(Asia/Seoul) | |
| `computed_at` | `part_metrics.computed_at`(최신) | |
| `part_id`, `part_name` | `parts` | 부품 미확정이면 `part_id=None` → 보류 |
| `stock` (S) | 원장 합계(병합 부품 포함), 검토 시점 값 | |
| `incoming` (O) | 열린 발주 중 `t_out` 전 도착분 합 | 발주 테이블 없음 → 0 |
| `open_orders` | 같은 부품(병합·같은 규격) 열린 발주 `[{qty, eta}]` | 없음 → `[]` |
| `open_requests` | 같은 부품의 다른 열린 검토(검토중·검토완료·보류) `[{review_id, qty}]`, 수정안 있으면 수정안 수량 | 검토 테이블 없음 → `[]` |
| `hidden` | 같은 규격·미병합 다른 부품 `[{part_id, name, qty, confirmed}]`, `confirmed` = 최근 실사 30일 이내 + 의심 아님 | `part_metrics`는 합계만 있음, 부품별 목록 필요 |
| `m`, `d95`, `d99`, `t_out`, `t_deadline` | `part_metrics` | |
| `f_period` | `part_metrics.f_items` 수량 합 | |
| `f_12m` | 향후 12개월 정비 일정 필요 수량 | 없음 → 0이면 C-02가 m만으로 판단 |
| `default_supplier_id` | `parts.default_supplier_id` | |
| `suppliers` | `supplier_parts`(단가, `moq`, `price_tiers`, `shipping_fee`) + `part_supplier_metrics.lt90`(없으면 공급사 기본 납기) | LT50 = LT90(표본 없음) |
| `price_stats` | 같은 부품 최근 구매 단가 평균·표준편차·건수 | 발주 없음 → `n=0`이면 C-05 건너뜀 |
| `import_dependent` | `parts.import_override` 또는 카테고리 `import_dependency`가 `high`·`medium` | 기준은 팀 확인 |
| `r_lead`, `r_price` | `part_metrics` | |
| `holidays_in_lead` | 오늘 ~ 오늘 + LT90 사이 연휴 이름 | 캘린더 없음 → `[]` |
| `loss`, `loss_equipment`, `loss_is_estimate`, `data_mode` | `part_metrics` | |
| `has_usage_history` | 출고 기록 있음(또는 `data_mode == "statistical"`) | |
| `has_maintenance_plan` | 정비 일정의 필요 수량 있음 | |
| `has_usage_estimate` | `parts.monthly_estimate is not None` | |

비어 있는 값은 오류가 아니라 해당 체크를 건너뛰는 쪽으로 동작한다. 그만큼 판정이 덜 정확하니 채워지는 대로 넣는다.

설정값(`company_settings`, SYS-01) → `ReviewSettings`: `review.c02_months`, `review.c05_sigma`, `review.c06_ratio`, `review.c08_days`, `system.c05_min_ratio`, `system.c05_small_n_ratio`. 스냅샷과 함께 저장한다(설정이 바뀌어도 이미 만든 판정은 그대로).

### 5-3. 저장과 REV-02 응답

| REV-02 필드 | 값 |
| --- | --- |
| `verdict`, `flags`, `hold_reasons`, `checks` | `outcome.result`의 같은 이름(코드값은 API 명세서 2장과 같음) |
| `original`, `proposal`, `alternatives` | `outcome.result`의 같은 이름. 공급사는 `supplier_id`·`supplier_name` → `{id, name}` |
| `risk_if_not_ordered` | `outcome.result.risk_if_not_ordered` |
| `count_requests` | `outcome.result.count_requests`(미확인 숨은 재고 부품)로 실사 요청 행을 만든 뒤 그 목록 |
| `opinion` | `{text, source, verified}` = `outcome.opinion`의 같은 이름 |
| `snapshot` | `{id, hash: outcome.result.review_hash, values: outcome.snapshot.model_dump(mode="json")}` |
| `computed_at` | `outcome.snapshot.computed_at` |

`review_requests`에 스냅샷·설정값·결과·의견서를 JSON으로 저장한다(`model_dump(mode="json")`, 다시 읽을 때 `model_validate`).

### 5-4. 그 밖의 REV API

| API | 함수 |
| --- | --- |
| REV-03 보류 보완 | 보완 값으로 `run_review_flow`를 다시 부른다 |
| REV-04 재검토 미리 보기 | `recheck(저장한 스냅샷, OrderRequest(수정 값), 설정값)` → `checks`, `proposal`, `verdict`, `flags`, `recheck_hash = .review_hash`. 저장 안 함 |
| REV-05 결정 | `snapshot_hash`는 저장한 `review_hash`와 대조. `approve_edited`는 `recheck`를 다시 계산해 `recheck_hash` 대조. 결정 직전 `needs_refresh(스냅샷, now=..., part_moved_since=...)`가 참이면 새 스냅샷으로 `run_review` → `decision_changed(전, 후)`가 참이면 409 `SNAPSHOT_REFRESHED` |
| REV-06 후속 질문 | `answer_question(질문, 결과, 스냅샷)` → `{topic, answer, source, evidence_refs}` 그대로 응답 |

의견서만 다시 써야 하면(예: 직접 수정 후 확정) `to_opinion_request(결과, 스냅샷, company_id=...)` + `finalize_opinion(요청, write_opinion)`.

## 6. server 연동 순서 (server 할 일 목록과 맞춤)

1. ai 연결 공통: `AI_BASE_URL`, `httpx` 의존성, `/health` 연결 점검(할 일 23)
2. 채팅 해석 포트 교체(할 일 21): 2장 어댑터, `usage` → `llm_calls`
3. 임베딩(할 일 22): `vector(1024)` 마이그레이션, 등록 시 저장, 매칭에 의미 유사도·RRF·코사인 확정
4. 검토(할 일 7~10): `bjk-review` 의존성, `collect_snapshot`, `review_requests` 저장, REV-01·02·05·06, 채팅 `PURCHASE_REQUEST`·재고 부족 초안 연결
5. SSE(할 일 20): `on_progress` → `review.progress`
6. 엑셀 이관(할 일 28): 4장
7. 스냅샷 보강: 부품별 숨은 재고, `f_12m`, 연휴, 발주·검토 테이블이 생기면 O·열린 발주·열린 요청·단가 통계

## 7. 알아둘 점

- **Bedrock 실제 호출은 EC2에서 확인 필요**(`uv run --package bjk-ai python apps/ai/scripts/smoke.py`). ai 컨테이너가 IAM Role을 쓰려면 EC2 메타데이터 응답 홉 제한이 2 이상이어야 한다.
- 의견서 숫자 검증은 숫자가 허용 목록에 있는지만 본다. 어떤 숫자를 무엇이라고 불렀는지까지는 보지 못한다.
- 의견서 재작성은 최대 3번 ai 호출(첫 작성 + 2회)이고, 그래도 틀리면 양식 의견서(`source: "template"`). ai가 멈춰도 검토는 판정과 양식 의견서로 끝난다.
