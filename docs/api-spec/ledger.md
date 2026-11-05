# 원장 정정 API

기능명세서 F-LEDGER-01 기준. 원장은 추가 전용이며(앱 계정에 UPDATE·DELETE 권한 없음, 트리거로도 차단) 잘못된 기록은 정정 기록(`ADJUST`)을 더해 바로잡는다.

## LED-02 POST /api/v1/movements/{id}/correction

- 권한: manager 이상. worker는 403.
- 원장 행이 없거나 다른 회사 행이면 404.

```json
// Request
{ "reason": "수량 오기, 실제 1개 출고", "corrected_qty": -1 }

// 201 Response (원본은 그대로, 차이만큼 ADJUST 추가)
{ "movement": { "id": "...", "type": "ADJUST", "qty": 1, "reason": "수량 오기, 실제 1개 출고", "corrects": "..." }, "stock_after": 2 }
```

- `corrected_qty`는 원본이 원래 가져야 했던 부호 있는 수량이다. 출고 원본은 0 이하, 입고 원본은 0 이상(0은 기록이 없었던 것으로 정정). 부호가 맞지 않으면 400.
- 같은 원본을 다시 정정하면 앞선 정정까지 합친 현재 수량과의 차이만 더한다. 차이가 없으면 400(`detail.current_qty`).
- 정정 기록 자체는 정정할 수 없다. 원본을 정정한다(400, `detail.corrects`).
- `reason`은 필수(공백만은 400), 500자 이하. 작성자는 요청한 관리자다.
- 같은 원본의 동시 정정은 원본별 advisory lock으로 순서대로 처리한다.
