# 발주 검토 API

기능명세서 F-REVIEW 기준. 체크·수정안·판정은 검토 엔진 `bjk_review`(순수 함수)가 만들고, server는 근거 스냅샷 수집·저장·상태·이벤트를 맡는다(`bjk_server.reviews`). LLM은 의견서 문장만 쓴다.

## 검토 실행

HTTP API가 아니라 채팅 발주 요청(CHAT-03 확정, CHAT-05 폼), 재고 부족 초안, 놓친 발주 초안이 부르는 서비스다.

1. `create_review`: `reviewing` 검토를 만들고 같은 트랜잭션에 `review.created`를 남긴다. 원안은 `request`(`qty`, `supplier_id`, `unit_price`, `text`).
2. 커밋 뒤 `run_review`(요청 처리 중이면 `ReviewRunner.start_after_commit`로 백그라운드 실행): 근거 고정 → 보류 판단 → 체크 9개 → 수정안 → 판정 → 의견서 → 검증.
3. 단계마다 `review.progress`(`interpret`, `snapshot`, `hold_check`, `checks`, `proposal`, `verdict`, `opinion`, `verify`)를 짧은 트랜잭션으로 남긴다. 보류면 `checks`·`proposal`이 빠지고, 의견서를 다시 쓰면 `opinion`·`verify`가 반복된다.
4. 결과 저장과 `done` 단계는 한 트랜잭션이다. `done`을 받은 화면은 저장된 결과를 조회할 수 있다.

| 판정 | 상태 | 만료 시각 |
| --- | --- | --- |
| `ok`, `revise` | `reviewed` | 저장 시각 + `system.review_expire_days`(기본 7일) |
| `hold` | `held` | 저장 시각 + `system.review_expire_days` |

- 저장: `reviews`에 판정·표시·보류 사유·결과(`checks`, `original`, `proposal`, `alternatives`, `risk_if_not_ordered`, `count_requests`)·의견서(`text`, `source`, `verified`)·원안 총액·절감액·미발주 예상 손실, `review_snapshots`에 스냅샷 값·검토 기준값·해시(`sha256:…`)·계산 시각.
- 의견서: ai(`AI_BASE_URL`)가 없거나 실패·시간 초과(8초)·숫자 검증 실패면 양식 의견서(`source: template`). ai 호출 사용량은 `llm_calls`(`purpose: opinion`)에 남긴다.
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
| O, 열린 발주 | 같은 부품(병합 포함)의 열린 발주 잔량. 도착 예정일은 주문 완료 시각(없으면 승인 시각) + 공급사 LT50(계산 전이면 공급사 기본 납기, 없으면 7일). 필요 시점(t_out) 전 도착분만 O에 더하고, t_out이 없으면 전부 더한다 |
| p̄, σ_p, n | 같은 부품(병합 포함)의 최근 구매 단가 통계(`price_stats`) |
| 연휴 | 오늘부터 기본 공급사 LT90 사이에 걸치는 연휴(카테고리 납기 요인의 국내·중국 명절, 기본 공급사 휴무) |

- 현재 구현 범위: 병합 부품 재고는 S에 더하지 않는다. 미확인 숨은 재고의 실사 요청은 결과 `count_requests`에만 담고 `count_requests` 행은 만들지 않는다.

## REV-04 POST /api/v1/reviews/{id}/recheck

- 권한: manager 이상. worker는 403 `FORBIDDEN_ROLE`.
- 저장한 최근 스냅샷과 검토 기준값으로 직접 수정 값을 다시 판정한다(F-REVIEW-09). 저장하지 않는다.

```json
// Request
{ "qty": 10, "supplier_id": "...", "unit_price": 18000 }

// 200 Response
{
  "verdict": "ok",
  "flags": ["urgent", "alternative"],
  "checks": [ { "code": "C-08", "level": "urgent", "facts": { "LT90": 10, "cause": "deadline", "t_need": "2026-11-17", "deadline": "2026-11-07", "days_left": 3 } } ],
  "proposal": { "qty": 10, "supplier": { "id": "...", "name": "공급사 A" }, "unit_price": 18000, "total": 180000, "saving": 0, "no_order": false, "basis": [] },
  "recheck_hash": "sha256:..."
}
```

- `qty`는 0 이상, `supplier_id`·`unit_price`는 생략 가능(기본 공급사·등록 단가). 결정(REV-05)의 `edited.qty`는 1 이상이라 수량 0으로 재검토한 값은 `approve_edited`로 승인할 수 없다.
- 같은 스냅샷·수정 값이면 같은 `recheck_hash`. 원안 값 그대로면 저장된 스냅샷 해시와 같다. 결정(`approve_edited`)에서 이 값을 대조한다.
- `proposal` 모양은 REV-02와 같다.

| 상황 | 응답 |
| --- | --- |
| `reviewed`가 아닌 검토(검토중·보류·결정됨) | 409 `REVIEW_NOT_DECIDABLE`, `detail.status` |
| 없는 검토, 다른 회사 검토 | 404 `NOT_FOUND` |
| 수량 음수 등 형식 오류 | 400 `VALIDATION_ERROR` |

## REV-03 POST /api/v1/reviews/{id}/clarify

- 권한: 요청자 본인 또는 manager 이상. 다른 작업자의 검토는 404.
- 보류(`held`) 검토에 부품·공급사를 보완하고 같은 검토를 `reviewing`으로 되돌려 다시 실행한다(F-REVIEW-03). 결과는 새 스냅샷 행으로 쌓인다.

```json
// Request (보류 사유에 맞는 값만)
{ "part_id": "...", "supplier_id": "..." }

// 202 Response
{ "review_id": "...", "status": "reviewing" }
```

- 실행은 응답 커밋 뒤 백그라운드에서 한다. 화면은 `review.progress`의 `done`을 받으면 다시 조회한다.
- 보완하지 않은 보류 건은 `expires_at`(보류 시각 + 7일) 뒤 만료 대상이다.

| 상황 | 응답 |
| --- | --- |
| `held`가 아닌 검토 | 409 `REVIEW_NOT_DECIDABLE`, `detail.status` |
| 부품·공급사 둘 다 없음 | 400 `VALIDATION_ERROR`, `detail.fields` |
| 없는 부품(병합된 부품, 다른 회사 부품 포함)·공급사 | 400 `VALIDATION_ERROR`, `detail.field` |
| 없는 검토, 다른 회사 검토, 다른 작업자의 검토 | 404 `NOT_FOUND` |

## REV-06 POST /api/v1/reviews/{id}/questions

- 권한: manager 이상. worker는 403 `FORBIDDEN_ROLE`.
- 질문을 주제(`qty`, `supplier`, `price`, `urgency`, `risk`)로 분류하고, 저장한 판정 결과와 최근 스냅샷의 숫자로 양식 문장을 채운다(`bjk_review.answer_question`). LLM 자유 답변은 확장.

```json
// Request (1~500자)
{ "question": "왜 10개야?" }

// 200 Response
{ "topic": "qty", "answer": "권장 발주량이 10개입니다. ...", "source": "template", "evidence_refs": ["R", "S", "O", "D95"] }
```

- 분류되지 않거나 근거가 없으면(보류 건 포함) `answer: "근거 데이터에 없습니다."`, `evidence_refs: []`.

| 상황 | 응답 |
| --- | --- |
| 검토가 아직 끝나지 않음(`reviewing`) | 409 `REVIEW_NOT_DECIDABLE`, `detail.status` |
| 없는 검토, 다른 회사 검토 | 404 `NOT_FOUND` |
| 빈 질문, 500자 초과 | 400 `VALIDATION_ERROR` |

## REV-07 GET /api/v1/reviews/{id}/pdf

- 권한: manager 이상. worker는 403 `FORBIDDEN_ROLE`.
- 200 `application/pdf`. 저장한 판정 결과·최근 스냅샷·의견서·승인 기록만 써서(생성 시각 없음) 다시 받아도 같은 바이트다.
- 구성: 발주 요약(원안·수정안), 판정·검토 의견, 근거 수치 표와 체크별 근거, 재고 추이 예측 그래프(발주 시·미발주 시), 미발주 리스크, 외부 요인, 승인자·승인 시각·계산 기준 시각.
- 재고 추이는 S + O + H_c에서 월 소모량 m을 하루씩 고르게 빼는 단순 추정이고, 발주 시 선은 공급사 LT90 날에 수량이 들어온다. 정비 확정 필요량은 넣지 않는다.
- 구현: HTML → WeasyPrint, 그래프 matplotlib SVG. 서버 이미지에 pango와 `fonts-noto-cjk`를 설치한다. macOS 로컬은 `brew install pango` 후 `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib`가 필요하고, pango가 없으면 PDF 테스트는 건너뛴다.

| 상황 | 응답 |
| --- | --- |
| 승인(`approved`) 전 | 409 `PDF_NOT_READY`, `detail.status` |
| 없는 검토, 다른 회사 검토 | 404 `NOT_FOUND` |

## REV-05 POST /api/v1/reviews/{id}/decision

manager 이상. 헤더 `Idempotency-Key` 필수(없으면 400). 같은 키·같은 본문이면 처음 응답을 그대로 돌려준다. 409 `SNAPSHOT_REFRESHED` 응답도 저장되므로, 다시 확인한 뒤에는 새 키로 보낸다. 같은 키를 다른 검토·다른 본문에 쓰면 409 `IDEMPOTENCY_CONFLICT`.

| `action` | 결과 | 필수 |
| --- | --- | --- |
| `approve_proposal` | 수정안으로 `approved` 발주, 201 | 수정안이 있고 `no_order`가 아님 |
| `approve_original` | 원안으로 발주, 201 | |
| `approve_edited` | 직접 수정 값으로 발주, 201 | `edited`, `recheck_hash`(REV-04와 같은 값) |
| `approve_alternative` | 대안으로 발주, 201 | `alternative_id` |
| `accept_no_order` | 검토 `closed`, 발주 없음, 200 | |
| `reject` | 검토 `closed`, 200 | `reason`(없으면 422 `REASON_REQUIRED`) |

- `snapshot_hash`는 선택. 보내면 현재 스냅샷과 대조해 다르면 409 `SNAPSHOT_REFRESHED`.
- 결정 직전 스냅샷이 24시간을 넘었거나 검토 후 같은 부품(병합 포함) 입출고가 있으면 근거를 다시 모아 판정한다. 새 스냅샷 행은 항상 저장하고, 판정·수정안이 바뀌었으면 검토 결과·양식 의견서를 갱신한 뒤 409 `SNAPSHOT_REFRESHED`(`detail`: `verdict`, `flags`, `snapshot_hash`, `proposal`). 이때 결정은 하지 않는다. 이 `proposal`은 `{qty, supplier_id, unit_price, total}`로, REV-02·REV-04의 `proposal`보다 필드가 적다.
- `approve_edited`의 `recheck_hash`가 현재 스냅샷으로 다시 계산한 값과 다르면 409 `SNAPSHOT_REFRESHED`(`detail`: `recheck_hash`, `verdict`). REV-04를 다시 불러 새 해시로 보낸다.
- 응답 `purchase_order`: `id`, `status: approved`, `part_id`, `qty`, `supplier {id, name}`, `unit_price`, `total`, `saving`(원안 총액 대비), `order_message`(필요 시점이 있으면 희망 납기 포함), `pdf_url`.
- 기록: `reviews.decision`(행동·사유·스냅샷 해시·수정 값·대안·발주 ID), `decided_by`, `decided_at`. SSE `review.decided` 발행.
- 요청자가 있으면 `decision_result` 알림(채널 `chat`, `in_app`). `requester_notified`는 알림을 만들었는지.
| 상황 | 응답 |
| --- | --- |
| 행동별 필수 값(`edited`, `recheck_hash`, `alternative_id`) 없음 | 400 `VALIDATION_ERROR`, `detail.fields` |
| 없는 `alternative_id` | 400 `VALIDATION_ERROR`, `detail.alternative_id` |
| 사장님이 아닌 사람이 본인 요청을 결정 | 403 `SELF_APPROVAL_NOT_ALLOWED` |
| 없는 검토, 다른 회사 검토 | 404 `NOT_FOUND` |
| `reviewed`가 아님, `approve_proposal`인데 수정안이 없거나 `no_order`, 고른 줄의 공급사·단가·수량이 정해지지 않음 | 409 `REVIEW_NOT_DECIDABLE` |
| `approved`·`closed`(동시 결정의 두 번째 포함) | 409 `REVIEW_ALREADY_DECIDED` |

- `pdf_url`은 REV-07 경로다.

## 재고 예측선 GET /api/v1/reviews/{id}/forecast (명세 밖, #258)

- 권한: REV-02와 같다(manager 이상, worker는 본인 요청). 검토 상세(W-03) 재고 예측 그래프용.
- Notion API 명세서에 없어 사용자 결정(2026-11-05)으로 이 레포에서 정했다. 판정에는 쓰지 않는다.
- 저장한 최근 스냅샷 기준이라 다시 받아도 같고, 결재용 PDF 그래프와 같은 값이다.

```json
{
  "as_of": "2026-11-04", "computed_at": "2026-11-04T03:00:00+09:00",
  "start_stock": 2, "monthly_use": 3.3, "order_qty": 10, "lead_days": 8,
  "reorder_point": null, "t_out": "2026-11-17",
  "days": [ { "date": "2026-11-04", "with_order": 2.0, "without_order": 2.0 }, "... 57일" ]
}
```

- `start_stock` = S + O + H_c, 하루 소모 = m ÷ 30, 정비 확정 필요량은 넣지 않는다. 8주(57개 점).
- `with_order`는 수정안 수량(수정안이 없으면 원안)이 그 공급사 LT90 날에 들어온다.
- 검토가 끝나지 않았으면 409 `REVIEW_NOT_DECIDABLE`, 없거나 볼 수 없는 검토는 404.
