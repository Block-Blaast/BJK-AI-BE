# 부품 API

## SET-03 GET /api/v1/parts

- 권한: 로그인한 모든 사용자.
- 정렬: 이름순(같은 이름은 ID순), 커서 목록. DB 로케일과 관계없이 C(코드포인트) 정렬로 고정해 한글은 가나다순, 영문·숫자가 한글보다 앞선다.
- 재고(`stock`)는 원장 이벤트 합산이다. 병합된 부품(`merged_into` 있음)은 목록에서 뺀다.

| Query | 설명 |
| --- | --- |
| `q` | 이름·별칭·규격 값 부분 일치, 대소문자 무시. 규격 키는 검색하지 않는다. `%`·`_`는 글자로 취급 |
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
- 현재 구현 범위: 장부 검증 전이라 `ledger_status`는 모두 `normal`이고 `ledger_status=suspect`는 결과가 없다.
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

- 현재 구현 범위: 발주 테이블 전이라 `stock.incoming`은 빈 목록, 실사 전이라 `last_counted_at`은 `null`, 장부 검증 전이라 `ledger_status`는 `normal`. 숨은 재고 부품 목록 `hidden.parts`는 빈 목록.
