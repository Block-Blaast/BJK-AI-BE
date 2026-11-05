# 외부 요인 API

기능명세서 F-EXT 기준. 위험도는 새벽 배치가 계산한 값([jobs.md](jobs.md) nightly)이고 LLM을 쓰지 않는다.

## DSH-03 GET /api/v1/external/status

- 권한: manager 이상. worker는 403.

```json
{
  "indicators": [
    { "code": "FREIGHT", "name": "컨테이너 운임지수", "series": "lead", "value": 2140, "as_of": "2026-10-31", "z": 1.4, "r": 1.4, "level": "caution" }
  ],
  "upcoming_holidays": [ { "name": "공급사 A 휴무", "start": "2026-11-10", "end": "2026-11-10", "scope": "supplier" } ],
  "categories": [ { "id": "...", "name": "베어링", "r_lead": 1.4, "r_price": 0.6, "level": "caution" } ],
  "updated_at": "2026-11-04T03:00:00+09:00",
  "stale": false
}
```

- `indicators`: 지표별 최신 값. r = min(max(0, z), 4), 등급은 r 1 미만 `normal`, 2 미만 `caution`, 그 이상 `high`.
- `categories`: 이름순. `r_lead`·`r_price`는 카테고리 납기·가격 요인 지표 r의 최대값, 등급은 둘 중 큰 값 기준.
- 외부 충격(DEV-02)이 켜져 있으면 해상운임 r과 이를 쓰는 카테고리 위험도가 고정값 3으로 나온다.
- `updated_at`은 외부 지표 마지막 갱신 시각, 24시간을 넘기면 `stale: true`(지표가 없을 때도 `true`).
- 현재 구현 범위: 연휴 캘린더(SET-11) 전이라 `upcoming_holidays`는 오늘부터 90일 안의 공급사 휴무일(`scope: supplier`)만 담는다.
