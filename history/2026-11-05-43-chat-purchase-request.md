# 채팅 발주 요청으로 검토 생성

- 날짜: 2026-11-05
- 영역: server
- 관련: Issue #153, F-CHAT-04, CHAT-01, CHAT-03, CHAT-05

## 목적

- 작업자의 "V벨트 30개 시켜주세요"를 직원 요청 검토(F-REVIEW)로 연결

## 한 일

- `chat/intents/purchase_request.py`: 확인·선택 카드, 공급사 표현 해석(`supplier_resolution`)
- `Interpretation.unit_price` 추가, 카드에 `unit_price`·`supplier_resolution` 추가
- `api/chat.py`: 카드 확정과 폼 입력(CHAT-05)에서 `create_review` 호출, 커밋 뒤 `ReviewRunner` 실행
- `docs/api-spec/chat.md` 갱신

## 결정과 근거

- 레인 A의 `reviews/service.py`(`create_review`, `ReviewRunner`)를 그대로 호출
- 발주 기록(#161) 전이라 최근 발주처 표현은 기본 공급사(`default`)로 해석
- 공급사 표현이 이름과 맞지 않으면 `none`, 검토는 기본 공급사로 진행
- 폼 발주 요청은 기존 `chat_entry` 멱등 키로 검토 중복 생성 방지

## 검증

- `REQUIRE_DB_TESTS=1 make test` 742개 통과(발주 요청 테스트 6개 포함)
- `make lint` 통과

## 남은 일·확인 필요

- #161 머지 후 `last_order` 해석 추가
- 검토 결정 결과의 요청자 채팅 전달(F-NOTI-04)은 알림 범위
