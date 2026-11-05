# 동시 입출고 재고 정합성 이식

- 날짜: 2026-11-05
- 영역: server
- 관련: #69, F-CHAT, F-LEDGER-01, CHAT-03, LED-02, AUD-03

## 목적

- `origin/fix/inventory-concurrency/#69`에만 있던 부품 행 잠금을 dev로 옮기고 다른 재고 변경 경로에도 같은 규칙 적용

## 한 일

- `a245712`, `d7f2390`(작성자 박진욱)을 dev 기준 브랜치에 cherry-pick. `chat/records.py`는 정비 연결 조회보다 잠금을 먼저 두고, `docs/api-spec/chat.md`는 dev의 `audit_flag_id` 설명을 유지해 충돌 해결
- 잠금을 `inventory.lock_part_stock`으로 묶고 채팅 기록(CHAT-03), 원장 정정(LED-02), 실사 응답(AUD-03)에 적용
- `tests/test_stock_lock.py`: 같은 부품 대기, 다른 부품 진행, 다른 회사 부품 거부 확인

## 결정과 근거

- 잠금 순서는 요청·원본 잠금 → 부품 → 의심 항목. 채팅 기록은 부품 → 의심 항목이라 순환 없음
- 부품 등록(SET-05)의 초기 재고는 새 부품이라 경쟁 없음, A 레인 파일이라 제외
- 이후 발주 입고 대조(#164)도 `record_movement`를 거쳐 같은 잠금 사용

## 검증

- `REQUIRE_DB_TESTS=1 make test` 556개 통과, `make lint` 통과

## 남은 일·확인 필요

- 없음
