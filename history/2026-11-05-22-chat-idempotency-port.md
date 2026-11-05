# 채팅·폼 멱등 요청 검증 dev 이식

- 날짜: 2026-11-05
- 영역: server
- 관련: Issue #68, CHAT-01, CHAT-05

## 목적

- `origin/fix/chat-idempotency/#68`에만 있던 멱등 요청 사용자·본문 검증을 dev에 반영

## 한 일

- `5a54b2c`(코드), `34c5750`(문서)을 작성자 유지로 cherry-pick
- 마이그레이션 `0008_idempotency_request_owner`를 `0020`(down_revision `0019`)으로 변경
- 기존 기록 보존 마이그레이션 테스트의 시작 리비전을 `0019`로 변경
- `docs/api-spec/chat.md`는 dev의 CHAT-02 절과 #68 검증 절을 모두 유지

## 결정과 근거

- 원 브랜치는 dev와 히스토리가 갈라져 머지하지 않고 cherry-pick
- 마이그레이션 번호는 머지 직전 dev 최신 번호 다음으로 재확정

## 검증

- `REQUIRE_DB_TESTS=1 make test` 566개 통과
- `make lint` 통과

## 남은 일·확인 필요

- A의 #137(0020~0022 예정)과 번호 충돌 시 나중에 머지하는 쪽이 번호 변경
