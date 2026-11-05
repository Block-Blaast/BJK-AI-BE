# Bedrock Claude 호출을 오사카 bedrock-runtime으로 변경

- 날짜: 2026-11-05
- 영역: AI
- 관련: Issue #176, `2026-11-05-14-bedrock-provider.md`, `2026-11-05-19-embedding-migration-main.md`

## 목적

- 클라우드 담당이 대회 서버 ai 컨테이너에서 `smoke.py`를 돌린 결과: 임베딩(Titan V2)은 정상, LLM은 모두 `APIConnectionError`로 대체 응답
- 원인: 오사카에 Bedrock Mantle 엔드포인트(`bedrock-mantle.ap-northeast-3.api.aws`)가 없어 DNS 조회 실패
- 클라우드 담당 제안: `AsyncAnthropicBedrock(aws_region="ap-northeast-3")` + `global.anthropic.claude-haiku-4-5-20251001-v1:0`. ai 컨테이너에서 0.7~1초 응답 확인, `global.anthropic.claude-sonnet-4-6`도 가능, `jp.` 프로필과 Haiku 5.5는 계정 권한 없음

## 한 일

- `BedrockGateway`의 Claude 클라이언트를 `AsyncAnthropicBedrockMantle`에서 `AsyncAnthropicBedrock`으로 교체. Titan과 같은 bedrock-runtime InvokeModel을 씀
- 기본 모델 ID를 `HAIKU_4_5 = "global.anthropic.claude-haiku-4-5-20251001-v1:0"`으로 변경(채팅·의견서·이관)
- 테스트: 모델 ID 갱신, 기본 클라이언트 주소가 `https://bedrock-runtime.ap-northeast-3.amazonaws.com`인지 검증 추가
- 문서 갱신: `docs/ai-work-rules.md` 설정 표, `docs/ai-integration.md` 예시, `.env.example`

## 결정과 근거

- 구조화 출력은 그대로 `messages.parse(output_format=...)`를 씀. 공식 플랫폼 표에서 Bedrock 구조화 출력 지원 확인
- 설치된 SDK(anthropic 2.5.0)로 가짜 HTTP 응답을 붙여 실제 요청을 확인
  - 주소: `.../model/global.anthropic.claude-haiku-4-5-20251001-v1:0/invoke`
  - 인증: `AWS4-HMAC-SHA256` 서명
  - 본문: `output_config.format`에 JSON 스키마가 들어감, 응답이 Pydantic 모델로 파싱됨
  - `effort`를 함께 주면 `output_config` 안에 `effort`와 `format`이 함께 들어감

## 검증

- ai·packages `pytest` 148개 통과, `ruff check`·`ruff format --check` 통과
- 실제 Bedrock 호출은 이 환경에 AWS 자격 증명이 없어 미검증. 배포 후 ai 컨테이너에서 `smoke.py`로 확인 필요

## 알아둘 점

- 배포 서버 env에 `BEDROCK_CHAT_MODEL` 등을 따로 넣었다면 그 값이 기본값보다 우선함
- 클라우드 담당이 확인한 응답이 구조화 출력(`output_config.format`)까지 포함한 요청인지는 모름. smoke에서 채팅 해석·의견서·이관 제안이 대체 응답 없이 나오는지로 확인

## 남은 일

- dev·main 머지 후 배포, ai 컨테이너에서 `smoke.py` 재실행
