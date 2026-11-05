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

## SET-07 설비

| API | 설명 |
| --- | --- |
| `GET /api/v1/equipment` | 목록과 연결 부품. 이름순(C 정렬), 커서 목록 |
| `GET /api/v1/equipment/{id}` | 상세 |
| `POST /api/v1/equipment` | 등록. 201 |
| `PATCH /api/v1/equipment/{id}` | 보낸 항목만 수정. `parts`를 보내면 연결 부품 전체를 바꾼다 |

```json
// POST Request
{ "name": "3호기", "loss_per_hour": 50000, "loss_is_estimate": true, "operating_hours": 16,
  "parts": [ { "part_id": "...", "qty_per_maintenance": 4 } ] }

// 201 Response
{ "id": "...", "name": "3호기", "loss_per_hour": 50000, "loss_is_estimate": true, "operating_hours": 16,
  "parts": [ { "part_id": "...", "name": "볼베어링 6205ZZ", "qty_per_maintenance": 4 } ] }
```

- `loss_per_hour`(기본 0, 0이면 손실액 미입력이라 금액 대신 "멈추는 설비"만 표시), `operating_hours` 1~24(기본 8).
- `parts`: 정비 1회당 부품·수량(1 이상). 같은 부품 두 번은 400, 없거나 병합된 부품은 404. 정비 일정에 필요 부품이 없으면 이 수량을 확정 필요량 F로 쓴다.
- 채팅이 설비를 이름(대소문자 무시)으로 찾으므로 이름은 회사 안에서 대소문자 무시 유일이다(409 `NAME_TAKEN`).
- PATCH에서 `null`은 400. 설비는 출고·정비 원장에 연결되어 삭제 API를 두지 않는다.

## SET-08 정비 일정

| API | 설명 |
| --- | --- |
| `GET /api/v1/maintenance` | 목록. 예정일 순, 커서 목록. Query `from`, `to`(예정일 범위), `equipment_id`, `completed`(true·false) |
| `GET /api/v1/maintenance/{id}` | 상세 |
| `POST /api/v1/maintenance` | 등록. 201 |
| `PATCH /api/v1/maintenance/{id}` | 보낸 항목만 수정 |
| `DELETE /api/v1/maintenance/{id}` | 취소한 일정 삭제. 204 |

```json
// POST Request (required_parts를 비우면 설비의 정비 1회당 부품·수량을 쓴다)
{ "equipment_id": "...", "scheduled_date": "2026-11-20", "required_parts": [ { "part_id": "...", "qty": 4 } ] }

// 201 Response
{
  "id": "...", "equipment": { "id": "...", "name": "3호기" }, "scheduled_date": "2026-11-20",
  "required_parts": [ { "part_id": "...", "qty": 4 } ],
  "parts": [ { "part_id": "...", "name": "볼베어링 6205ZZ", "qty": 4 } ], "parts_source": "schedule",
  "completed_at": null
}
```

- `parts`는 확정 필요량 F에 실제로 쓰는 부품이다. 정비 일정의 `required_parts`가 있으면 그것(`parts_source: schedule`), 없으면 설비 기준(`equipment`). 둘을 더하지 않는다.
- `required_parts`의 같은 부품 두 번·수량 0 이하는 400, 없거나 병합된 부품은 404. PATCH에서 `required_parts: null`이면 설비 기준으로 돌아간다. `equipment_id`·`scheduled_date`에 `null`은 400.
- 완료된 정비는 수정·삭제할 수 없다(409 `ALREADY_CONFIRMED`, `detail.status: completed`). 출고가 연결된 정비도 삭제할 수 없다(`detail.status: linked`).

## SET-09 POST /api/v1/maintenance/{id}/complete

- 권한: 로그인한 모든 사용자(작업자 포함). 완료자(`completed_by`)와 완료 시각을 남긴다.

```json
// Request (본문 생략 가능. 비우면 지금)
{ "completed_at": "2026-11-20T10:00:00+09:00" }

// 200 Response
{ "maintenance_id": "...", "completed_at": "2026-11-20T01:00:00Z" }
```

- `completed_at`은 시간대를 포함해야 하고 미래 시각은 400.
- 이미 완료된 정비는 409 `ALREADY_CONFIRMED`(`detail.status: completed`). 없으면 404.
- 완료 후 48시간 안의 같은 설비 출고는 이 정비에 연결되고(F-LEDGER-03), 완료 48시간이 지나도 필요 부품 출고가 절반 미만이면 장부 검증 `MAINTENANCE_OUT_MISMATCH`가 된다.
- 정비 목록·상세 응답에 `completed_by`(사용자 ID)가 담긴다.
- 현재 구현 범위: 채팅 정비 완료(의도 `MAINTENANCE_DONE`) 연결은 ai 해석 연동 후 추가한다.

## SET-11 연휴 캘린더

| API | 설명 |
| --- | --- |
| `GET /api/v1/calendar` | 목록. 시작일 순, 커서 목록. Query `from`·`to`(기간과 겹치는 일정), `scope` |
| `POST /api/v1/calendar` | 등록. 201 |
| `PATCH /api/v1/calendar/{id}` | 보낸 항목만 수정 |
| `DELETE /api/v1/calendar/{id}` | 삭제. 204 |

```json
// POST Request
{ "name": "춘절", "start": "2027-02-05", "end": "2027-02-13", "scope": "CN" }

// 201 Response
{ "id": "...", "name": "춘절", "start": "2027-02-05", "end": "2027-02-13", "scope": "CN", "supplier_id": null }
```

- `scope`: `KR`(국내 명절), `CN`(중국, 춘절 등), `supplier`(특정 공급사 휴무, `supplier_id` 필수). `supplier`가 아닌데 `supplier_id`가 있거나, `supplier`인데 없으면 400. 없는 공급사는 404.
- `end`가 `start`보다 빠르면 400(수정 후 값으로도 검사). `name`·`start`·`end`·`scope`에 `null`은 400.
- 시연 시드에 2027년 춘절(CN)·설날 연휴(KR)가 들어 있다.
- 현재 구현 범위: 새벽 배치 납기 연장과 외부 요인 현황 연결은 #108에서 반영한다. 공급사 상세의 `holidays`(날짜 목록)는 그대로 쓴다.
