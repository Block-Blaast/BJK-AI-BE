# 오늘 활동 목록 (명세 밖, #275)

화면 W-01 기준. 기능명세서에는 "오늘 활동" 요소만 있고 형식이 없어, 프론트 목업 형식으로 정했다.

## GET /api/v1/activity/today

- 권한: manager 이상. worker는 403 `FORBIDDEN_ROLE`.
- Asia/Seoul 오늘 0시부터의 기록을 최신 순으로 최대 100개 준다. 하루치라 커서는 없다. 건수 기준은 DSH-02 `today`와 같다.
- 저장하지 않고 조회할 때 원장·검토·실사 요청에서 만든다.

```json
{
  "date": "2026-11-04",
  "items": [
    { "id": "ar-...", "kind": "audit_resolved", "text": "오링 P-20 실사 종료 — 이상 없음", "at": "2026-11-04T01:00:00Z", "href": "/audit" },
    { "id": "...", "kind": "movement", "text": "볼베어링 6205ZZ 출고 -2개 — \"베어링 2개 씀\"", "at": "2026-11-04T00:50:00Z", "href": "/parts/..." }
  ]
}
```

| `kind` | 출처 | `id` | `href` |
| --- | --- | --- | --- |
| `movement` | 원장 기록(`occurred_at`). `ADJUST`는 사유(`실사조정` 등)를 이름으로 쓴다 | 원장 ID | `/parts/{part_id}` |
| `review_created` | 검토 생성. 입구·판정·표시를 붙인다. 판정 전이면 `검토 중` | `rc-{review_id}` | `/reviews/{id}` |
| `review_decided` | 검토 결정(`decided_at`). 행동과 반려 사유 | `rd-{review_id}` | `/reviews/{id}` |
| `audit_requested` | 실사 요청 생성. 담당자 이름 | `aq-{count_request_id}` | `/audit` |
| `audit_resolved` | 실사 종료(`closed_at`). 차이 또는 `이상 없음` | `ar-{count_request_id}` | `/audit` |

- `href`는 프론트 화면 경로다.
