# 검토 완료·긴급·보류·실사 요청 알림 생성

- 날짜: 2026-11-05
- 영역: server
- 관련: #272, F-NOTI-01·03·04, F-AUDIT-06, F-SETUP-04, REV, AUD-02, NOT-01

## 목적

- 정의만 있고 만드는 곳이 없던 알림 종류(`review_completed`, `review_urgent`, `count_request`)와 보류 결과 알림 연결

## 한 일

- `reviews/notices.py`: 검토 결과 저장 트랜잭션에서 알림 생성. 긴급 직원 요청·재고 부족 초안은 `review_urgent`, 그 밖의 직원 요청은 `review_completed`, 보류는 요청자 `decision_result`(채팅)
- `audit/counts.py`: 실사 요청 시 담당자 `count_request`(채팅·웹 푸시). 예약 요청은 예약 시각부터 노출
- `notify/service.py`: 보낼 시각 `at` 인자 추가
- 테스트: `test_review_notices.py` 6개, `test_count_requests.py` 2개 추가, `test_review_decision.py` 알림 조회 조건을 `decision_result`로 한정

## 결정과 근거

- 놓친 발주는 즉시 알리지 않음: F-NOTI-01이 07:30 브리핑으로 정함. 정의상 대부분 긴급이라 즉시 보내면 07:00 스캔 직후 몰림
- 일반 재고 부족 초안도 브리핑으로 대체(F-NOTI-01 "다음 날 아침 브리핑")
- 긴급이면 `review_completed` 대신 `review_urgent` 한 건만 생성
- 요청자 본인은 manager·owner 알림에서 제외. 본인 요청은 본인이 결정하지 못하는 경우가 많고(F-AUTH-03), 요청자는 결정 결과로 따로 받음
- 보류 알림 키에 스냅샷 해시 포함: 보완 뒤 다시 보류되면 새로 알림
- `maintenance_check`는 만들지 않음: 명세상 정비 완료 확인은 브리핑 표시만(F-SETUP-04, F-NOTI-02)

## 남은 일·확인 필요

- 마감 2일 전 재알림(F-NOTI-03) 미구현
