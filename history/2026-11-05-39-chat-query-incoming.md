# 재고 조회 답변의 입고 예정

- 날짜: 2026-11-05
- 영역: server
- 관련: Issue #22, F-CHAT-03, CHAT-01

## 목적

- 채팅 QUERY 답변에 입고 예정 추가(#22 남은 항목)

## 한 일

- `chat/intents/incoming.py`: 열린 발주 미입고 수량 합과 가장 이른 도착 예상일 문장
- `chat/intents/query.py`에서 재고 문장 뒤에 입고 예정 연결
- `docs/api-spec/chat.md` 갱신

## 결정과 근거

- 발주 조회는 #161의 `purchasing/orders.open_orders`, `remaining_qty` 사용
- 예상일 = 주문 완료 시각(주문 전이면 승인 시각) + 공급사 LT50, 납기 기록이 없으면 기본 납기, 없으면 7일(기능명세서 '정보가 부족할 때의 대응')

## 검증

- `REQUIRE_DB_TESTS=1 make test` 792개 통과(입고 예정 테스트 3개 포함)
- `make lint` 통과

## 남은 일·확인 필요

- 없음
