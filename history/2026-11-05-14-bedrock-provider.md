# LLM·임베딩 제공자를 Bedrock으로 전환, 임베딩 1024차원

- 날짜: 2026-11-05
- 영역: AI (contracts 포함)
- 관련: Issue #89, Draft PR #90(→ #85 브랜치), 브랜치 `feat/ai-bedrock/#89`(#85 브랜치 위에 쌓음), `2026-11-05-13-bedrock-feasibility.md`

## 목적

- 사용자 결정: 임베딩 1024차원, LLM·임베딩 모두 Bedrock(인프라 보안 요청, API 키 없이 EC2 IAM Role). server에는 사용자가 1024차원 변경을 전달함

## 한 일

- `packages/contracts/src/bjk_contracts/embedding.py`: `EMBEDDING_DIM` 1536 → 1024
- 의존성: `apps/ai`에 `anthropic[bedrock]`(2.5.0), `boto3` 추가
- `apps/ai/src/bjk_ai/gateway.py`
  - `LlmGateway` 프로토콜 변경: 모델 대신 용도(`purpose`)를 받고, 쓴 모델을 결과에 담음. `max_tokens`·`attempt`·임베딩 `task` 추가
  - `BedrockGateway`: Claude는 `AsyncAnthropicBedrockMantle`의 `messages.parse`(구조화 출력), 임베딩은 boto3 `bedrock-runtime` Titan V2(`dimensions`, `normalize`)를 텍스트마다 스레드로 최대 8개 동시
  - `GeminiGateway`: 같은 프로토콜로 맞추고 Gemini 임베딩 입력 형식(저장용·검색용 접두어)을 안으로 옮김
  - `RoutedGateway`: LLM 첫 시도는 주 제공자, 재시도는 폴백(없으면 주 제공자). 임베딩은 정한 제공자 하나
  - `build_gateway`: AWS 자격 증명이 있으면 Bedrock, Gemini 키가 있으면 Gemini를 만들고 설정대로 묶음
  - 이벤트 루프별 클라이언트 재생성을 `_PerLoopClient`로 공용화
- `apps/ai/src/bjk_ai/config.py`: `LLM_PROVIDER`, `EMBEDDING_PROVIDER`, `AWS_REGION`, `BEDROCK_*` 설정
- `chat.py`·`opinion.py`·`import_suggest.py`·`embedding.py`: 용도로 호출, 사용량 모델은 실제 쓴 모델
- `main.py`: `create_app(gateway="auto")`가 `build_gateway`로 구성, `None`이면 미설정
- `apps/ai/scripts/smoke.py`: 실제 제공자로 엔드포인트를 불러 모델·지연·대체 여부를 출력(EC2 확인용)
- 테스트: `test_gateway.py` 다시 작성(Bedrock 요청·응답 변환, Titan 호출, 경로 선택, 구성 선택), 기존 테스트를 새 프로토콜에 맞춤
- `docs/ai-work-rules.md`: 제공자 결정과 실행 설정 표 갱신

## 결정과 근거

- **Bedrock 클라이언트는 Mantle:** Anthropic 문서가 새 코드에 권장하는 Messages API 경로. 모델 ID는 `anthropic.` 접두어, 자격 증명은 AWS 기본 체인(IAM Role 포함)
- **기본 모델 Haiku 4.5:** 모든 Bedrock 고객에게 열려 있음. Haiku 5.5는 접근 승인이 필요해 승인 후 `BEDROCK_*_MODEL`과 `BEDROCK_EFFORT=low`로 바꾸게 함. Haiku 4.5는 effort를 받지 않아 기본은 보내지 않음
- **구조화 출력:** `messages.parse(output_format=스키마)`. 채팅·의견서·이관 제안 스키마 3개 모두 SDK 변환이 되는 것을 네트워크 없이 확인. 응답은 기존처럼 pydantic으로 다시 검증
- **거절·잘림은 실패:** `stop_reason`이 `refusal`·`max_tokens`면 오류로 보고 재시도·대체
- **임베딩은 폴백하지 않음:** 다른 모델 벡터를 server DB에 섞으면 유사도 비교가 깨짐. Bedrock을 못 쓰면 임베딩은 대체 응답(server는 규격·철자만으로 매칭)
- **Titan은 용도 구분 없음:** 저장용·검색용 모두 원문 그대로 보냄. Gemini 접두어는 Gemini 게이트웨이 안에서만 붙임
- **폴백은 재시도 자리에:** 채팅 2.5초 예산 안에 같은 제공자 재시도 대신 Bedrock 1회 → Gemini 1회

## 검증

- `uv run pytest`: 148개 통과, `ruff check`·`ruff format --check` 통과
- 이 환경(AWS 자격 증명 없음, Gemini 키 있음)에서 `smoke.py`: LLM은 Gemini로 대신해 채팅 8문장·의견서·이관 제안 정상, 임베딩은 의도대로 대체 응답
- **Bedrock 실제 호출은 미검증:** AWS 자격 증명이 없음. EC2에서 `smoke.py`로 확인 필요. 특히 Haiku 4.5의 Bedrock 구조화 출력, 오사카 Titan V2 제공 여부, 지연(채팅 2.5초 예산)

## 남은 일·확인 필요

- 인프라: EC2에서 `smoke.py` 실행, Bedrock 모델 접근(Haiku 4.5·Titan V2) 확인. ai를 Docker로 띄우면 컨테이너가 IAM Role을 쓰도록 EC2 메타데이터 응답 홉 제한을 2 이상으로(IMDSv2 기본 1이면 컨테이너에서 자격 증명을 못 받음)
- `compose.yaml` ai 서비스에 `AWS_REGION` 전달: 스택을 최신 dev에 맞출 때 함께(dev의 compose가 바뀌어 있어 지금 고치면 충돌)
- server: `vector(1024)` 마이그레이션(사용자가 전달), 임베딩 모델명은 응답의 `model`(`amazon.titan-embed-text-v2:0`) 저장
