# 3D 창고 배치·예측 (명세 밖, #281)

화면 W-11 기준. 기능명세서·API 명세서에 없는 화면이라 프론트 제안 형식(`packages/api/src/types/twin.ts`)을 따른다. 3D는 계산하지 않고 그리기만 하므로 색·숫자는 모두 이 응답에서 온다.

- 권한: 두 API 모두 manager 이상. worker는 403 `FORBIDDEN_ROLE`.

## GET /api/v1/twin/layout

- 회사별 `twin_layouts` 한 줄에 저장한 배치를 준다. 지금은 시연 시드(`make seed`)의 더미 배치(선반 5개, 설비 3대, 부품 6개)만 있고 편집 API는 없다.
- 설비 이름과 연결 부품(`part_ids`)은 설비 테이블(SET-07)에서 읽는다. 배치에 좌표가 있는 설비만 나온다.
- 병합된 부품의 칸은 대표 부품으로 바꾸고, 없는 부품은 뺀다.
- 배치가 없는 회사는 `size: {width: 20, depth: 16}`과 빈 목록.

```json
{
  "size": { "width": 22, "depth": 18 },
  "zones": [ { "id": "zone-a", "kind": "storage", "label": "A  베어링", "x": -6.5, "z": -3, "width": 5, "depth": 6 } ],
  "racks": [ { "id": "A-01", "label": "A-01", "levels": 4, "slots": 4, "x": -6.5, "z": -3, "rotation": 0, "purpose": "베어링" } ],
  "equipment": [ { "id": "...", "name": "3호기", "kind": "press", "x": 5, "z": 4.5, "part_ids": ["..."] } ],
  "placements": [ { "part_id": "...", "rack_id": "A-01", "level": 2, "slot": 1 } ]
}
```

- 좌표 단위는 m, 바닥 중심이 원점. `rotation`은 라디안(y축). `level`·`slot`은 1부터(아래·왼쪽부터). `zones[].kind`: `storage`, `machines`, `dock`. `equipment[].kind`: `lathe`, `mill`, `press`, `compressor`, `conveyor`.

## GET /api/v1/twin/projection?with_orders=

- 병합되지 않은 모든 부품의 오늘(Asia/Seoul)부터 8주(57개 점) 날짜별 예측. 조회할 때 계산하고 저장하지 않는다. 같은 데이터면 같은 결과(난수·LLM 없음).
- `with_orders=true`면 결정 대기(`reviewed`) 검토의 수정안을 지금 발주한 것으로 보고 입고 예정에 더한다.

```json
{
  "base_date": "2026-11-04", "horizon_days": 56, "with_orders": false,
  "computed_at": "2026-11-04T03:00:00+09:00", "is_mock": false,
  "bins": [
    {
      "part_id": "...", "reorder_point": 1,
      "qty": [3.0, 2.9, "... 57개"], "status": ["risk", "... 57개"], "p_out": [0.65, "... 57개"],
      "same_spec_group": null,
      "audit": { "id": "...", "reason": "COUNT_OVERDUE", "grade": "low" },
      "maintenance": [ { "date": "2026-11-20", "qty": 4, "equipment": "3호기" } ]
    }
  ],
  "equipment": [ { "equipment_id": "...", "status": ["warn", "... 57개"], "loss": [null, "... 57개"], "cause_part_ids": [["..."], "... 57개"] } ],
  "arrivals": [ { "part_id": "...", "qty": 10, "eta": "2026-11-08", "kind": "ordered", "review_id": null } ]
}
```

| 값 | 계산 |
| --- | --- |
| `qty[d]` | 현재 재고(원장, 병합 포함) + d일까지 도착분 − 하루 소모(최신 근거 지표 m ÷ 30) × d − d일까지 정비 확정 필요량. 소수 첫째 자리, 0 미만은 0 |
| `p_out[d]` | d일부터 (기본 공급사 LT90 + 7일) 동안 수요(하루 소모 × 기간 + 그 기간 정비 필요량)가 가진 재고 + 그 기간 도착분을 넘을 확률. 정규 근사, 표준편차 = 수요 × 변동계수(smooth 0.25, erratic 0.6, intermittent 0.8, lumpy 1.2, 그 밖 1.0). 0.01~0.99, 소모가 없는 부품은 0 |
| `status[d]` | 소모가 있고 재고 0 이하면 `out`, `p_out` 0.3 이상이면 `risk`, 재주문점 이하면 `low`, 그 밖은 `normal` |
| `same_spec_group` | 같은 카테고리·같은 규격으로 등록된 다른 부품이 있으면 그 묶음 키(숨은 재고, F-MATCH-03) |
| `audit` | 열린 장부 의심 항목(`open`·`count_requested`)의 규칙(`reason`)과 등급(`grade`) |
| `maintenance` | 끝나지 않은 오늘 이후 정비의 이 부품 필요량. 일정의 필요 부품, 없으면 설비 기준(SET-08) |
| `equipment[].status[d]` | 쓰는 부품 중 하나라도 `out`이면 `down`, `risk`면 `warn`, 그 밖은 `normal`. `cause_part_ids`는 그 부품들 |
| `equipment[].loss[d]` | `down`인 날 시간당 손실 × 가동 시간 × 바닥난 부품 중 가장 긴 LT50(F-ANAL-08). 시간당 손실이 0이면 `null` |
| `arrivals` | `ordered`: 열린 발주 미입고분, 도착 예상일은 주문 완료(없으면 승인) 시각 + 공급사 LT50, 지났으면 오늘. `proposal`: 수정안 수량, 오늘 + 수정안 공급사 LT50 |

- `computed_at`은 최신 근거 지표 계산 시각, 계산 전이면 `null`. `is_mock`은 항상 `false`.
- 근거 지표가 없는 부품은 소모 0, LT90 7일, 재주문점 `null`로 계산한다.
- 이 결품 확률은 화면 색칠용 근사이고, 부품 지표·검토의 `p_out`(경로 시뮬레이션, F-ANAL-07)과 값이 다를 수 있다.
