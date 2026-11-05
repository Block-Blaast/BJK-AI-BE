# 회사별 LLM 일일 토큰 상한

- 날짜: 2026-11-05
- 영역: server
- 관련: #172, API 명세서 1-5, `docs/ai-integration.md` 1장

## 목적

- 회사별 하루 ai 토큰 사용량을 제한하고 넘으면 기존 대체 경로로 응답한다

## 한 일

- `apps/server/src/bjk_server/ai/quota.py`: 당일(Asia/Seoul) `llm_calls` 입력·출력 토큰 합계와 회사 설정 상한 비교
- `ai/client.py`: `AiClient`에 상한 확인 함수 주입, 공통 `_post`에서 넘으면 요청 없이 `AiUnavailable(quota_exceeded)`. 메서드 영역은 변경 없음
- `defaults.py`: `system.llm_daily_tokens` 기본값 1,000,000 추가
- `tests/test_ai_quota.py`: 요청 차단·정상 호출·KST 하루와 회사 격리·채팅 `form` 대체·앱 계정 조회 5개

## 결정과 근거

- 상한 위치: API 명세서 1-5는 "회사별 일일 토큰 상한(설정값)"만 규정. 회사 설정 `system`(SYS-01)에 두어 회사별로 바꿀 수 있게 함
- 기본값 1,000,000은 명세에 숫자가 없어 2026-11-05 사용자 결정으로 정한 값
- 합계는 요청 트랜잭션과 별도 세션으로 읽음. 같은 요청에서 남긴 기록은 커밋 뒤부터 반영
- 합계가 상한 이상이면 초과로 판정

## 검증

- `REQUIRE_DB_TESTS=1 uv run pytest apps/server/tests/test_ai_quota.py`: 5개 통과
- `REQUIRE_DB_TESTS=1 make test`: 559개 통과
- `make lint` 통과
- dev 반영 후 `REQUIRE_DB_TESTS=1 make test` 574개 통과

## 남은 일·확인 필요

- 기본 상한 값 사용자 확인 완료(2026-11-05)
- ai 호출마다 조회 1회가 늘어남. `ix_llm_calls_company_created` 사용
- `docs/ai-integration.md` 19줄의 "회사별 토큰 상한은 아직" 문구는 다른 영역 문서라 그대로 둠
