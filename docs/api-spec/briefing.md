# 아침 브리핑 (DSH-01)

API 명세서 10장·14장, 기능명세서 F-NOTI-02, F-MISSED-02, F-SETUP-04, 화면 M-04 기준. 브리핑은 저장하지 않고 조회할 때 계산한다.

## DSH-01 `GET /briefing/today`

- 권한: manager 이상. worker는 403.
- `missed_orders`: 결정을 기다리는(`reviewed`·`held`) 놓친 발주 초안. 예상 손실 큰 순, `expected_loss_total`은 합계, `t_deadline`은 검토 스냅샷 값.
- `pending_reviews`: 결정을 기다리는 직원 요청·재고 부족 초안 수(놓친 발주 제외).
- `count_needed`: 아직 실사를 요청하지 않은 열린 의심 항목(`open`) 수.
- `order_check_needed`: 승인하고 24시간이 지나도록 주문 완료 표시가 없는 발주 수. LT90을 넘긴 미입고는 order-check 배치(G4)와 함께 더한다.
- `maintenance_check_needed`: 예정일 + 2일이 지나도록 완료 기록이 없는 정비 수.
- `should_notify`: 다섯 건수 중 하나라도 0이 아니면 `true`.

## briefing 배치 (매일 07:30)

- 만료 시각이 지난 `reviewed`·`held` 검토를 `expired`로 바꾸고, 직원 요청이면 요청자에게 `decision_result` 알림(채널 `chat`).
- 브리핑에 확인할 일이 있으면 활성 사장님·관리자에게 `briefing` 알림. 키 `briefing:<날짜>`로 하루 한 번.
- 회사별 `notify.briefing_time`에 맞춘 실행 시각 조정은 아직 없다(배치는 07:30 고정).
