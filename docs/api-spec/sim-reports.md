# 검증 리포트 (명세 밖, #260)

기능명세서 F-SIM-03·04, 화면 W-09 기준. Notion API 명세서에 없어 사용자 결정(2026-11-05)으로 이 레포에서 정했다.

## GET /api/v1/sim-reports

- 권한: manager 이상. worker는 403 `FORBIDDEN_ROLE`.
- 최신 순 커서 목록(`?cursor=&limit=`, 공통 규칙).

```json
{
  "items": [
    { "id": "...", "title": "[시연용] 현장 방식 대비 정책 재생 (결품·재고 금액)", "source": "sample", "created_at": "2026-11-04T10:00:00+09:00", "pdf_url": null }
  ],
  "next_cursor": null
}
```

- 원소는 프론트 목업 형식(`id`, `title`, `created_at`, `pdf_url`)에 `source`를 더했다. 프론트 목업은 배열을 돌려줬지만 서버는 공통 커서 목록(`items`)으로 준다.
- `source`: `sample`(시연 시드 더미), `harness`(검증 하네스 실행 결과).
- 현재 구현 범위: 검증 하네스가 없어 시연 시드(`make seed`)가 넣는 `sample` 2건만 있다. 결과 수치는 넣지 않는다(F-SIM: 리포트에는 실제 실행한 값만). PDF가 없어 `pdf_url`은 항상 `null`.
- 하네스를 붙일 때 `sim_reports`에 `harness` 행을 쌓고 수치는 `summary`(JSONB)에 둔다. PDF 저장·조회 경로는 그때 정한다.
