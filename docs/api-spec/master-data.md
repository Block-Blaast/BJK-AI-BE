# 기준 정보 API

기능명세서 F-SETUP 기준. 쓰기는 모두 manager 이상이고, 바꾼 값은 다음 새벽 배치(근거 지표)부터 반영된다.

## SET-06 카테고리

| API | 설명 |
| --- | --- |
| `GET /api/v1/categories` | 목록 (보조). 이름순(C 정렬), 커서 목록 |
| `POST /api/v1/categories` | 등록. 201 |
| `PATCH /api/v1/categories/{id}` | 보낸 항목만 수정 |

```json
// POST Request
{ "name": "베어링", "import_dependency": "high", "lead_factors": ["FREIGHT", "HOLIDAY_CN"], "price_factors": ["USDKRW"], "hs_code": "8482" }

// 201 Response
{ "id": "...", "name": "베어링", "import_dependency": "high", "lead_factors": ["FREIGHT", "HOLIDAY_CN"], "price_factors": ["USDKRW"], "hs_code": "8482" }
```

- `import_dependency`: `high`, `medium`, `low`(기본). `high`·`medium`이면 수입 의존 부품으로 보고 납기에 외부 가중치를 곱한다.
- `lead_factors`: `FREIGHT`(해상운임), `HOLIDAY_KR`(국내 명절), `HOLIDAY_CN`(춘절). `price_factors`: `USDKRW`(환율). 그 밖의 코드는 400. 중복 코드는 하나로 합친다.
- 이름은 앞뒤 공백을 빼고 회사 안에서 유일하다. 이미 있으면 409 `NAME_TAKEN`. `name`·`import_dependency`·요인 목록에 `null`은 400, `hs_code`는 `null`로 지울 수 있다.
- worker는 조회·쓰기 모두 403.

## SET-10 공급사

| API | 설명 |
| --- | --- |
| `GET /api/v1/suppliers` | 목록. 이름순(C 정렬), 커서 목록, 거래 부품 수 `part_count` |
| `GET /api/v1/suppliers/{id}` | 상세와 부품별 거래 조건 `parts` |
| `POST /api/v1/suppliers` | 등록. 201, 응답은 상세 |
| `PATCH /api/v1/suppliers/{id}` | 보낸 항목만 수정 |
| `PUT /api/v1/suppliers/{id}/parts/{part_id}` | 부품별 거래 조건 등록·수정 (통째로 바꿈) |
| `DELETE /api/v1/suppliers/{id}/parts/{part_id}` | 부품별 거래 조건 삭제. 204 |

```json
// POST Request
{ "name": "공급사 C", "contact": "010-0000-0003", "default_lead_time_days": 10, "holidays": ["2026-12-25"] }

// PUT /suppliers/{id}/parts/{part_id} Request
{ "unit_price": 18000, "moq": 10, "price_tiers": [ { "min_qty": 20, "unit_price": 16500 } ], "shipping_fee": 4000 }

// GET /suppliers/{id} Response
{
  "id": "...", "name": "공급사 A", "contact": "010-0000-0001", "default_lead_time_days": 7, "holidays": [], "part_count": 5,
  "parts": [ { "part_id": "...", "name": "볼베어링 6205ZZ", "unit_price": 18000, "moq": 10, "price_tiers": [ { "min_qty": 20, "unit_price": 16500 } ], "shipping_fee": 4000 } ]
}
```

- `default_lead_time_days`는 1~365일. 비어 있으면 납기 계산에 7일을 쓴다. 휴무일은 중복을 빼고 날짜순으로 저장하며 납기 구간과 겹치면 하루씩 더한다.
- `price_tiers`는 `min_qty`(1 이상)가 겹치지 않는 오름차순이어야 한다. 아니면 400. `moq` 기본 1, `shipping_fee` 기본 0.
- 이름은 회사 안에서 유일하다(409 `NAME_TAKEN`). `name`·`holidays`에 `null`은 400, `contact`·`default_lead_time_days`는 `null`로 지울 수 있다.
- 공급사는 발주·납기 이력의 기준이라 삭제 API를 두지 않는다. 거래를 끊으면 부품별 거래 조건을 지운다. 병합된 부품에는 조건을 등록할 수 없다(404).
