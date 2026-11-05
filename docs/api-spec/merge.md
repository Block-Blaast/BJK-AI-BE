# 중복 부품 병합 API

기능명세서 F-MATCH-03, F-LEDGER-02. 후보는 주간 배치 `weekly-merge`(월요일 03:30)가 만든다.

## 후보 탐지 (`weekly-merge`)

- 같은 카테고리, 규격(`parts.spec`)이 키·값 모두 같고 비어 있지 않은 부품끼리 비교한다. 규격 값은 매칭과 같이 공백·`-`를 빼고 대문자로 맞춘다.
- 이름 유사: 두 부품 모두 같은 모델의 이름 임베딩이 있으면 코사인 ≥ 0.8, 아니면 자모 3-gram 유사도(양방향 최댓값) ≥ 0.3. 두 기준은 명세에 없는 초깃값이다(F-SIM 조정 대상).
- 병합된 부품은 비교하지 않는다. 이미 저장한 쌍은 상태와 관계없이 다시 만들지 않는다(다른 부품으로 정한 쌍이 매주 다시 뜨지 않음).
- 한쪽이 병합된 열린 후보는 `closed`로 닫는다.
- 요약: `{ "created": 1, "closed": 0 }`

## MAT-01 GET /api/v1/merge-candidates

- 권한: manager 이상. 점수 높은 순 커서 목록(`?cursor=&limit=`).
- Query `status`: `open`, `count_requested`, `merged`, `different`, `closed`. 생략하면 결정 대기(`open`·`count_requested`)만.

```json
{
  "items": [
    {
      "id": "...", "score": 0.91, "reason": "spec_exact+name_similar", "status": "open",
      "part_a": { "id": "...", "name": "육각볼트 M8-20", "stock": 40, "last_counted_at": "2026-10-28" },
      "part_b": { "id": "...", "name": "헥사볼트 M8x20", "stock": 800, "last_counted_at": null },
      "representative_part_id": null,
      "created_at": "2026-11-09T18:30:00Z"
    }
  ],
  "next_cursor": null
}
```

- `last_counted_at`: 그 부품의 가장 최근 실사 응답(AUD-03) 날짜(Asia/Seoul). 없으면 `null`.

## MAT-02 POST /api/v1/merge-candidates/{id}/decision

- 권한: manager 이상.

```json
// Request
{ "action": "merge", "representative_part_id": "..." }

// 200 Response: MAT-01 항목 형식 (status: merged)
```

- `action`
  - `merge`: 대표 부품(후보 두 부품 중 하나, 아니면 400 `detail.field: representative_part_id`)을 정하고 다른 쪽에 `merged_into`를 둔다. 흡수되는 부품에 이미 병합돼 있던 부품도 대표 부품으로 바로 연결한다.
  - `different`: 다른 부품으로 닫는다.
  - `request_count`: 실사 후 결정(`count_requested`). 목록에 남고 다시 결정할 수 있다.
- 병합: 원장은 고치지 않는다. 별칭은 대표 부품으로 옮기고, 대표 부품에 같은 호칭이 있으면 확정 횟수를 더하고 모호 표시를 합친다. 흡수된 부품이 들어간 다른 열린 후보는 `closed`.
- 이미 결정한 후보(`merged`, `different`, `closed`)는 409 `ALREADY_CONFIRMED`(`detail.status`). 두 부품 중 하나가 이미 병합됐으면 409(`detail.status: merged`). 없으면 404.
- 현재 구현 범위: `request_count`는 상태만 바꾼다. 실사 요청 생성(AUD-02)은 의심 항목 기준이라 연결하지 않았다.

## 재고 합산 (F-LEDGER-02)

- 현재 재고 = 원장 합계이며, 병합된 부품의 원장을 대표 부품 재고에 더한다(`inventory.stock_of`, `stock_subquery`). 부품 목록·상세·채팅 조회·확인 카드 재고가 모두 대표 기준이다.
- 현재 구현 범위: 발주 검토 스냅샷(S)에 병합 부품 재고를 연결하는 것은 검토 서비스(#146) 반영 후 따로 한다.
