# 입고 확인 카드의 발주 대조 미리 보기

- 날짜: 2026-11-05
- 영역: server
- 관련: Issue #164, F-LEDGER-04, CHAT-01

## 목적

- 입고 확인 카드에서 확정 전에 발주 대조 결과(`po_match`)를 보여줌(레인 D #216 후속)

## 한 일

- `chat/intents/po_preview.py`: 부작용 없는 대조 미리 보기
- `chat/intents/record.py`: `IN` 확정 대상 카드에 `po_match` 연결, `chat/schemas.py` 필드 추가
- `docs/api-spec/chat.md` 갱신

## 결정과 근거

- 발주 선택 규칙은 `purchasing/receipt.match_receipt`와 같음(남은 수량 일치 먼저, 없으면 오래된 승인)
- 카드에는 공급사·단가가 없어 수량만 비교, 확정 응답의 `po_match`가 정본
- 레인 D 파일(`purchasing/receipt.py`)은 수정하지 않음

## 검증

- `REQUIRE_DB_TESTS=1 make test` 827개 통과, 1개 건너뜀(미리 보기 테스트 3개 포함)
- `make lint` 통과

## 남은 일·확인 필요

- 없음
