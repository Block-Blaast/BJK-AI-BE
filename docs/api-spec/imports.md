# 부품 엑셀 이관 (SET-01·02)

정본: Notion「API 명세서」SET-01·02, 기능명세서 F-SETUP-01·02. 권한은 manager 이상.

## SET-01 POST /api/v1/imports/parts

multipart 필드 `file`(xlsx, csv, 5MB·1,000줄 이하). 첫 번째 비어 있지 않은 줄이 머리글이다.

| 항목 | 열 이름 (공백 무시) | 필수 |
| --- | --- | --- |
| 부품 이름 | 부품 이름, 부품명, 품명, 이름 | 필수 |
| 현재 재고 | 현재 재고, 재고, 재고수량 | 필수 |
| 단위 | 단위 | 필수 |
| 규격 | 규격 | 권장 |
| 기본 공급사·단가 | 기본 공급사, 공급사, 거래처 / 단가, 기본 단가 | 권장 |
| 월 사용 추정치 | 월 사용 추정치, 월 사용량, 월 사용 | 선택 |
| 보관 위치 | 보관 위치, 위치 | 선택 |

- 응답 모양은 명세서와 같다(`import_id`, `is_reimport`, `rows[]`, `ai`). `rows[].warnings`를 더했다.
- 정렬: 오류 줄 → 확신도 낮은 줄(제안 없음은 0) → 파일 순서.
- 규격: 정규식(`extract_spec`)이 찾은 키는 정규식 값, 나머지 키만 ai 값. 둘이 다르면 확신도 × 0.5.
- `existing_part_id`: 부품명(정규화)과 규격이 같은 기존 부품. `is_reimport`: 이 회사에 확정한 이관이 있음.
- `duplicate_suspects`: 규격 일치(`spec_exact`), 또는 규격이 겹치지 않고 이름 자모 유사도 0.6 이상(`name_similar`). 최대 3개.
- `errors`(확정 불가): `name_required`, `unit_required`, `stock_required`, `stock_invalid`, `unit_price_invalid`, `monthly_estimate_invalid`.
- `warnings`(확정 가능, 값 미반영): `supplier_unknown`(등록되지 않은 공급사 이름).
- 필수 열 없음·빈 파일·xlsx·csv 외 형식·크기 초과는 400 `VALIDATION_ERROR`.

### ai 대체 경로

ai `/v1/imports/suggest`(200줄 묶음)가 시간 초과·오류·대체 응답이거나 ai가 설정되지 않으면 200으로 아래처럼 응답한다.

- `spec`: 정규식 값만
- `suggested_category`: 모든 줄 `null`(관리자가 직접 고름)
- `ai`: `{"used": true, "fallback": true, "reason": "timeout|error|schema_invalid|quota_exceeded"}`. ai 미설정, 회사에 카테고리가 없음, 이름 있는 줄이 없음은 `used: false`, `reason: "error"`

## SET-02 POST /api/v1/imports/parts/{id}/confirm

요청에 넣은 줄만 반영한다. `category_id`·`spec`을 비우면 SET-01 제안 값을 쓰고, `merge_with_part_id`나 `existing_part_id`가 있으면 그 부품을 갱신한다. 병합 대상의 이름이 다르면 별칭으로 남긴다.

| `stock_mode` | 새 부품 | 기존 부품 |
| --- | --- | --- |
| `initial` (첫 이관 기본값) | 시작 재고 ADJUST(`초기 재고`) | 정보만 갱신 |
| `ignore` (재이관 기본값) | 시작 재고 ADJUST(`초기 재고`) | 정보만 갱신 |
| `preview` | 저장 안 함, 차이 목록에 포함(`part_id: null`, `ledger_stock: 0`) | 차이 목록만 (`stock_diffs`) |
| `apply` | 시작 재고 ADJUST(`초기 재고`) | 차이만 ADJUST(`엑셀 재이관`) |

- 응답 200: `{created, updated, adjust_movements, stock_diffs}`. `stock_diffs` 원소는 `{row, part_id, name, ledger_stock, file_stock, diff}`이고 차이가 0인 줄은 뺀다. `preview`는 `created`·`updated`·`adjust_movements`가 0이다.
- 요청의 `spec` 값은 공백과 `-`를 빼고 대문자로 바꿔 저장한다.
- 재이관에 `initial`, `preview` 전의 `apply`는 400 `VALIDATION_ERROR`. 오류가 있는 줄·파일에 없는 줄, 회사에 없는 `category_id`도 400(SET-05와 달리 404가 아님).
- 이미 확정한 이관은 409 `ALREADY_CONFIRMED`. 없는 이관·병합 대상은 404.
- 재고 ADJUST 전에 부품 재고 잠금을 잡는다(#69).
- 공급사가 등록돼 있으면 기본 공급사로 두고, 단가가 있으면 `supplier_parts.unit_price`를 넣거나 갱신한다.
- 새 부품 임베딩은 ai로 만들고, 실패하면 비워 두어 nightly가 채운다.
