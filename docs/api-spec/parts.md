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
- `ledger_status`는 열린 장부 의심 항목(AUD-01)이 있으면 `suspect`, 없으면 `normal`이다.
- 허용 값 밖의 필터는 400 `VALIDATION_ERROR`, 토큰 없음은 401.

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
- `initial_stock`(기본 0)이 있으면 원장에 `ADJUST`(사유 `초기 재고`, 작성자 등록한 관리자)로 넣는다. 재고 열은 저장하지 않는다.
- `import_override`: 카테고리와 다른 수입 의존도(`high`, `medium`, `low`).
- 없는 `category_id`·`default_supplier_id`는 404(`detail`에 필드).
- PATCH는 보낸 항목만 고친다. 재고는 바꾸지 않는다(LED-02 정정, AUD-03 실사로 맞춘다). `name`·`unit`·`spec`에 `null`은 400, 나머지는 `null`로 지운다.
- 병합된 부품은 404(`detail.merged_into`)이며 대표 부품을 고친다.
- 현재 구현 범위: 등록 시 임베딩·중복 후보 제안(F-SETUP-02 4·5단계)은 ai 연동·병합 기능에서 더한다.
