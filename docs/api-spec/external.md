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
- 출처: 환율 Frankfurter API(ECB 기준 환율), 해상운임 한국해양진흥공사 KCCI 종합지수(주간), 연휴 Nager.Date 공휴일 API. 새벽 배치가 받는다([jobs.md](jobs.md) nightly). 받지 못하면 직전 값, 처음이면 시드 CSV.
- `updated_at`은 외부 지표 마지막 갱신 시각, 24시간을 넘기면 `stale: true`(지표가 없을 때도 `true`).
- `upcoming_holidays`: 오늘부터 90일 안에 걸치는 연휴 캘린더(SET-11) 일정과 공급사 휴무일(`scope: supplier`, 이름 `<공급사> 휴무`). 시작일 순.
