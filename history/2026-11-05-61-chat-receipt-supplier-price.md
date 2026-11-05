# 채팅 입고 공급사·단가 발주 대조 전달

- 날짜: 2026-11-05
- 영역: server
- 관련: #244, #164, F-LEDGER-04, CHAT-01·03·05

## 목적

- 입고 대조 함수가 지원하던 공급사·단가 불일치를 채팅 입고 경로에서 실제로 쓰게 함

## 한 일

- `chat/records.py`: `record_movement`에 `supplier_id`·`unit_price` 인자, `match_receipt`로 전달
- `chat/intents/record.py`(C): IN 확인 카드 payload에 메시지 공급사·단가 저장
- `chat/intents/po_preview.py`(C): 미리 보기도 공급사·단가 비교
- `api/chat.py`(C): 확정·폼 입력에서 공급사·단가 전달
- `tests/test_chat_receipt_supplier_price.py` 4개

## 결정과 근거

- 공급사는 메시지에 이름(`named`)이나 최근 발주처 표현(`last_order`)이 있을 때만 넘김. 기본 공급사로 채우면 실제로 받은 곳이 아닌데 불일치를 만들 수 있음
- C 레인 파일은 인자 전달만 최소로 추가(조정 세션 배정)

## 검증

- 채팅·입고 관련 테스트 59개 통과(바뀐 부분 위주, 사용자 지시), `make lint` 통과

## 남은 일·확인 필요

- 없음
