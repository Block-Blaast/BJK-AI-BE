# 입고와 발주 대조

- 날짜: 2026-11-05
- 영역: server
- 관련: #164, F-LEDGER-04, F-ANAL-04, CHAT-03·05

## 목적

- 입고 기록을 열린 발주와 맞춰 발주 상태와 실제 납기를 남기고, 응답에 `po_match` 제공

## 한 일

- `purchasing/receipt.py`: `match_receipt`(complete·partial·mismatch·no_order), `lead_time_days`
- `chat/records.py`: `IN` 기록 때 대조, `movements.po_id` 저장, 응답 `po_match`·`actual_lead_time_days`, `movement.po_id`
- `docs/api-spec/chat.md` CHAT-03 설명 갱신
- `tests/test_receipt_po_match.py` 9개

## 결정과 근거

- 발주 고르기: 잔량이 입고 수량과 같은 발주 우선, 없으면 가장 오래된 승인. 같은 부품 발주가 여럿일 때 수량이 맞는 건이 그 입고일 가능성이 높음
- 잔량보다 많이 들어오면 발주는 `received`로 닫고 `mismatch` + 관리자 알림(`receipt_check`). 수량 불일치는 기록하고 알림(F-LEDGER-04)
- 공급사·단가가 다르면 같은 발주로 단정하지 않고 발주는 그대로, 알림만. 현재 채팅 `IN` 경로는 공급사·단가를 넘기지 않아 함수 인자로만 지원
- 대조는 원장 기록과 같은 트랜잭션, 부품 재고 잠금 뒤 발주 행 `FOR UPDATE`(#69 잠금 순서 유지)
- 응답 필드는 C 레인 파일(`api/chat.py`)을 고치지 않도록 `RecordResponse` 검증기에서 채움

## 검증

- `tests/test_receipt_po_match.py` 9개 통과
- `REQUIRE_DB_TESTS=1 make test` 714개 통과, `make lint` 통과 (#161 브랜치 기준)

## 남은 일·확인 필요

- 확인 카드(CHAT-01) `po_match` 미리 보기는 C 레인 카드 코드(`chat/intents`, `chat/schemas.py`)에 붙일 일. C 레인과 조율 필요
- #207 머지 후 dev 기준으로 다시 맞춤
