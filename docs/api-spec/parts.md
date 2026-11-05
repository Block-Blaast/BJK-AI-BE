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
