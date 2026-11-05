# 부품 API

## SET-03 GET /api/v1/parts

- 권한: 로그인한 모든 사용자.
- 정렬: 이름순(같은 이름은 ID순), 커서 목록. DB 로케일과 관계없이 C(코드포인트) 정렬로 고정해 한글은 가나다순, 영문·숫자가 한글보다 앞선다.
- 재고(`stock`)는 원장 이벤트 합산이다. 병합된 부품(`merged_into` 있음)은 목록에서 빼고, 그 원장은 대표 부품 재고에 더한다([merge.md](merge.md)).

| Query | 설명 |
| --- | --- |
| `q` | 이름·별칭·규격 값 부분 일치, 대소문자 무시. 최대 100자(넘으면 400). 규격 키는 검색하지 않는다. `%`·`_`는 글자로 취급 |
| `category_id` | 카테고리 |
| `abc` | `A`, `B`, `C` |
| `demand_class` | `smooth`, `erratic`, `intermittent`, `lumpy`, `insufficient` |
| `risk` | `caution`, `high` |
| `ledger_status` | `normal`, `suspect` |
| `cursor`, `limit` | 공통 커서 규칙 |

```json
{
  "items": [
    {
      "id": "...", "name": "볼베어링 6205ZZ", "category": "베어링", "unit": "개",
      "stock": 3, "abc": null, "demand_class": null, "ledger_status": "normal",
      "t_out": null, "p_out": null, "risk_level": null, "computed_at": null
    }
  ],
  "next_cursor": null
}
```

- 지표(`abc`, `demand_class`, `t_out`, `p_out`, `risk_level`, `computed_at`)는 부품별 최신 새벽 계산(`part_metrics`) 값이다. 계산 전에는 `null`이고 지표 필터에 걸리지 않는다.
- `risk_level`과 `risk` 필터는 카테고리 외부 위험 등급(r_lead·r_price 중 큰 값의 등급)이다.
- `ledger_status`는 열린 장부 의심 항목(AUD-01)이 있으면 `suspect`, 없으면 `normal`이다.
- 허용 값 밖의 필터는 400 `VALIDATION_ERROR`, 토큰 없음은 401.

## SET-04 GET /api/v1/parts/{id}

- 권한: 로그인한 모든 사용자.
- 부품 정보, 원장 합산 재고, 숨은 재고, 최신 새벽 계산 지표, 공급사별 단가·납기, 별칭을 한 번에 준다.

```json
{
  "id": "...", "name": "볼베어링 6205ZZ", "spec": { "bearing_no": "6205", "shield": "ZZ" }, "unit": "개",
  "category": { "id": "...", "name": "베어링", "import_dependency": "high" },
  "stock": {
    "S": 3, "incoming": [], "hidden": { "H_c": 0, "H_u": 0, "parts": [] },
    "ledger_status": "normal", "last_counted_at": null
  },
  "metrics": {
    "abc": "A", "demand_class": "intermittent", "data_mode": "statistical",
    "forecast_weekly": 0.3, "m": 1.3,
    "F": [ { "maintenance_id": "...", "equipment": "3호기", "date": "2026-11-20", "qty": 4 } ],
    "default_supplier": { "id": "...", "name": "공급사 A", "LT50": 6, "LT90": 10 },
    "D95": 11, "D99": 13, "reorder_point": 6,
    "t_out": "2026-11-20", "t_deadline": "2026-11-10", "p_out": 0.62,
    "loss": { "L": 4800000, "equipment": [ "3호기" ], "is_estimate": true },
    "priority": 2976000, "R": 10, "r_lead": 1.4, "r_price": 0.6, "external_level": "caution",
    "computed_at": "2026-11-04T03:00:00+09:00"
  },
  "supplier_metrics": [
    { "supplier_id": "...", "name": "공급사 A", "LT50": 6, "LT90": 10, "samples": 5, "unit_price": 18000, "moq": 10 }
  ],
  "aliases": [ { "text": "베어링 작은 거", "confirmed_count": 3, "ambiguous": false } ]
}
```

- `metrics`는 부품의 최신 `part_metrics`. 새벽 계산 전에는 `null`이고, 숨은 재고 `H_c`·`H_u`는 0.
- `supplier_metrics`는 부품을 공급하는 공급사(`supplier_parts`)를 이름순으로 나열한다. 납기·표본 수는 최신 `part_supplier_metrics` 값이고 계산 전에는 `null`.
- `R`은 새벽 계산의 권장 발주량(`recommended_qty`, MOQ 반영).
- 별칭은 확정 횟수가 많은 순.

| 상황 | 응답 |
| --- | --- |
| 없는 부품, 다른 회사 부품, 병합된 부품 | 404 `NOT_FOUND` |
| 토큰 없음 | 401 `UNAUTHORIZED` |

- 현재 구현 범위: `stock.incoming`·`hidden.parts`는 빈 목록, `last_counted_at`은 `null`, `stock.ledger_status`는 항상 `normal`로 고정돼 있다. 목록(SET-03)의 `ledger_status`는 열린 의심 항목으로 `suspect`를 계산하므로, 같은 부품이 목록에서는 `suspect`이고 상세에서는 `normal`일 수 있다. 열린 발주 잔량은 재고 예측선(forecast)에만 반영된다.

## 재고 예측선 GET /api/v1/parts/{id}/forecast (명세 밖, #258)

- 권한: 로그인한 모든 사용자. 부품 상세(W-05) 재고 추이 예측선용. 응답 모양은 검토 예측선([reviews.md](reviews.md))과 같다.
- 시작 재고는 지금 원장 합계 S + 열린 발주 미입고 O + 확인된 숨은 재고 H_c, 하루 소모는 최신 새벽 계산 m ÷ 30.
- `with_order`는 권장 발주량 R이 기본 공급사 LT90 날에 들어온다. `reorder_point`, `t_out`은 최신 새벽 계산값.
- 새벽 계산 전이면 `computed_at: null`, `days: []`. 없는 부품·병합된 부품·다른 회사 부품은 404.

## LED-01 GET /api/v1/parts/{id}/movements

- 권한: 로그인한 모든 사용자. 부품이 없거나 다른 회사 부품이면 404.
- 정렬: 발생 시각 최근 순(같은 시각은 ID 역순), 커서 목록.

```json
{
  "items": [
    {
      "id": "...", "type": "OUT", "qty": -2, "occurred_at": "2026-11-04T01:12:00Z",
      "author": "이현장", "source_text": "3호기 베어링 두 개 씀",
      "equipment_id": "...", "maintenance_id": null, "po_id": null,
      "reason": null, "corrects": null
    }
  ],
  "next_cursor": null
}
```

- `author`는 작성자 이름이다. 초기 이관처럼 작성자가 없는 기록은 `null`.
- `corrects`는 정정 기록([LED-02](ledger.md))일 때 정정 대상 원장 행 ID다.
- 병합된 부품도 자기 이력을 볼 수 있다. 대표 부품 이력에 병합 부품 이력을 합치는 것은 병합(MAT) 기능에서 정한다.

## SET-05 POST /api/v1/parts, PATCH /api/v1/parts/{id}

- 권한: manager 이상. worker는 403.

```json
// POST Request
{
  "name": "볼베어링 6206ZZ", "unit": "개",
  "category_id": "...", "default_supplier_id": "...",
  "spec": { "bearing_no": "6206", "shield": "ZZ" },
  "pack_qty": null, "monthly_estimate": 2, "import_override": null, "location": "A선반 2칸",
  "initial_stock": 5
}

// 201 Response (PATCH 200도 같은 형식)
{
  "id": "...", "name": "볼베어링 6206ZZ", "unit": "개", "category_id": "...", "default_supplier_id": "...",
  "spec": { "bearing_no": "6206", "shield": "ZZ" }, "pack_qty": null, "monthly_estimate": 2,
  "import_override": null, "location": "A선반 2칸", "stock": 5
}
```

- 필수: `name`(1~200자), `unit`(1~16자). 앞뒤 공백은 뺀다. `spec` 값은 문자열·숫자만.
- 범위: `pack_qty` 1 이상, `monthly_estimate`·`initial_stock` 0 이상, `location` 100자 이하. 벗어나면 400.
- `initial_stock`(기본 0)이 있으면 원장에 `ADJUST`(사유 `초기 재고`, 작성자 등록한 관리자)로 넣는다. 재고 열은 저장하지 않는다.
- `import_override`: 카테고리와 다른 수입 의존도(`high`, `medium`, `low`).
- 없는 `category_id`·`default_supplier_id`는 404(`detail`에 필드).
- PATCH는 보낸 항목만 고친다. 재고는 바꾸지 않는다(LED-02 정정, AUD-03 실사로 맞춘다). `name`·`unit`·`spec`에 `null`은 400, 나머지는 `null`로 지운다.
- 병합된 부품은 404(`detail.merged_into`)이며 대표 부품을 고친다.
- 등록·이름 변경 때 이름 임베딩(ai `/v1/embeddings`, `task: document`)을 저장한다. ai가 실패해도 등록은 되고, 빈 임베딩은 nightly가 채운다.
- 현재 구현 범위: 등록 시 중복 후보 제안(F-SETUP-02 4단계)은 병합 기능에서 더한다.
