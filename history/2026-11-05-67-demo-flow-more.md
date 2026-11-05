# 시연 흐름 통합 테스트 보강

- 날짜: 2026-11-05
- 영역: server
- 관련: #255, #249, #251

## 목적

- 레인 D의 시연 흐름 테스트(#249)에 없던 경우를 덧붙여 화면 흐름 끊김 확인

## 한 일

- `tests/test_demo_flow.py`에 3개 추가: 작업자 상세·목록·후속 질문·수정안 승인·결재용 PDF → 입고완료, 보류 → 작업자 보완 → 직접 수정 승인 → 입고완료, 재고 부족 초안 → 수정안 승인 → 입고완료

## 결정과 근거

- 결재용 PDF는 pango가 있을 때만 확인

## 검증

- `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run pytest apps/server/tests/test_demo_flow.py` 5개 통과(PDF 200 포함), `make lint` 통과. 전체 테스트는 지시에 따라 생략
- 끊기는 곳 없음

## 남은 일·확인 필요

- 없음
