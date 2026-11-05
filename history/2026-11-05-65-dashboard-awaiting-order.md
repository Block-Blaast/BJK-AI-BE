# 대시보드 주문 대기 발주 연결과 권한·격리 테스트

- 날짜: 2026-11-05
- 영역: server
- 관련: #180, DSH-02, W-01, F-APPROVAL-02

## 목적

- 0으로 고정돼 있던 `awaiting_order`를 발주 테이블에 연결하고 #180의 남은 테스트 항목 마무리

## 한 일

- `api/dashboard.py`: `awaiting_order` = `purchase_orders.status = 'approved'` 건수
- `tests/test_dashboard.py`: 주문 대기 건수(approved만), owner 허용, 다른 회사 발주·검토·의심 항목·원장 미포함 테스트 추가

## 결정과 근거

- 주문 대기는 승인 후 [주문 완료]를 누르지 않은 발주(`approved`)만. 기능명세서 F-APPROVAL-02 "승인됨 (주문 대기)". 조정 세션 안내의 "approved·ordered"와 다르므로 확인 필요
- worker 403 테스트는 기존에 있음

## 검증

- `tests/test_dashboard.py` 7개 통과, `make lint` 통과 (전체 테스트는 main 배포 CI 대상)

## 남은 일·확인 필요

- `awaiting_order`에 `ordered`(주문 완료, 입고 대기)까지 넣을지 확인 필요
