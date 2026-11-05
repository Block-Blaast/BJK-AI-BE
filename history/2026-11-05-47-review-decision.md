# 발주 검토 결정과 발주 생성

- 날짜: 2026-11-05
- 영역: server
- 관련: #162, REV-05, F-APPROVAL-01·02·03, F-REVIEW-09

## 목적

- 검토완료 건의 승인·불필요 수용·반려를 받고, 승인이면 `approved` 발주를 만든다

## 한 일

- `purchasing/decision.py`: 행동 6종, 결정 직전 스냅샷 갱신, 발주 생성, 결정 기록, `review.decided`, 요청자 알림
- `api/review_decision.py`: `Idempotency-Key` 필수, 승인 201·종료 200·갱신 409 응답 저장
- `domain/purchase_order.py`에 `order_message` 순수 함수 추가
- `docs/api-spec/reviews.md` REV-05 절, 테스트 13개

## 결정과 근거

- 검토 행 `FOR UPDATE` 후 상태 확인. 동시 결정의 두 번째는 `REVIEW_ALREADY_DECIDED`(F-APPROVAL-02)
- 스냅샷 갱신 판단·판정 비교는 `bjk_review.needs_refresh`·`decision_changed`. 바뀐 경우 409를 돌리되 새 스냅샷·결과는 저장해야 해서 예외 대신 응답을 만들어 커밋
- 갱신 후 의견서는 양식 의견서로 바꿈. LLM 호출은 결정 요청 안에서 하지 않음
- 본인 요청 결정은 사장님만(F-AUTH-03)
- `snapshot_hash`가 현재와 다르면 갱신과 같은 409로 다시 확인받음
- 새 파일에 두어 A 레인 `reviews/`·`api/review_actions.py`는 고치지 않음

## 검증

- `tests/test_review_decision.py` 13개 통과
- `REQUIRE_DB_TESTS=1 make test` 802개 통과, `make lint` 통과

## 남은 일·확인 필요

- REV-07 PDF 생성은 없음. `pdf_url`만 반환
- 요청자 채팅 메시지 전달은 알림(`chat` 채널) 기록까지. 채팅 화면 표시는 채팅 기능 범위
