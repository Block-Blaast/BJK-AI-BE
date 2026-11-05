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
