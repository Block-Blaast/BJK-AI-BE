# 검토 후속 질문 API

- 날짜: 2026-11-05
- 영역: server
- 관련: #149, F-REVIEW-09, REV-06

## 목적

- 승인자 질문에 같은 스냅샷 근거로 양식 답변

## 한 일

- `api/review_questions.py`: `POST /reviews/{id}/questions`
- `reviews/service.py`: `stored_review`로 저장 결과와 최근 스냅샷을 판정 결과·스냅샷 모델로 복원
- 테스트 `test_review_questions.py` 9개, 문서 `docs/api-spec/reviews.md` REV-06

## 결정과 근거

- 재검토·보완 API(#210·#211)의 `review_actions.py`와 충돌하지 않도록 별도 라우터 파일
- 질문 길이 1~500자(채팅 입력 한도와 같게), 명세에 없어 이 레포에서 정함
- 검토중 409 `REVIEW_NOT_DECIDABLE`, 보류 건은 "근거 데이터에 없습니다."

## 검증

- 검증 대기

## 남은 일·확인 필요

- 이슈 완료 기준 "왜 0개야?"는 열린 발주 O 연결 전이라 수정안이 10개로 나와 10개 질문으로 확인
