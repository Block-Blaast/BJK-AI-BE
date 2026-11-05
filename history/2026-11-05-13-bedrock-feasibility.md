# Bedrock(Anthropic) 전환 가능성 검토

- 날짜: 2026-11-05
- 영역: AI
- 관련: 인프라 문의(EC2 IAM Role로 Bedrock 오사카 호출, Gemini API 키 유출 우려)

## 목적

- 인프라 질문에 답: 지금 LLM 코드 위치, provider 교체 가능 구조인지, Bedrock 전환 작업량, 품질 재조정 필요 여부, Bedrock 우선 + Gemini 폴백 가능 여부

## 확인한 사실

- **코드 위치:** dev·main에는 아직 없음(AI PR 8개 모두 Draft로 쌓여 있음). Gemini 호출 코드는 `feat/ai-gemini-chat-embedding/#67`(채팅·임베딩)부터, 의견서 `#71`, 이관 제안 `#81`, 전체는 스택 끝 `feat/review-langgraph/#85`
- **구조:** 유스케이스(채팅·임베딩·의견서·이관 제안)는 `LlmGateway` 프로토콜(`generate_json`, `embed`)만 부름. Gemini 전용 코드는 `apps/ai/src/bjk_ai/gateway.py`의 `GeminiGateway`와 `embedding.py`의 Gemini 임베딩 입력 형식뿐. 검토 엔진(판정)은 LLM과 무관
- **Bedrock 쪽(공식 문서 기준, 콘솔 확인 필요):**
  - Claude Haiku 5.5: 오사카 in-region 없음, 교차 리전 추론(`jp.anthropic.claude-haiku-5-5`, `global.anthropic.claude-haiku-5-5`)으로 사용. 문서끼리 Geo 지원 표기가 엇갈림. Claude 문서상 Haiku 5.5는 접근 신청 필요("See Access")
  - Claude Haiku 4.5: 오사카 Geo·Global 경로 있음(2027-04-08 종료 예정)
  - 구조화 출력은 Bedrock에서 지원. Anthropic SDK의 Bedrock 클라이언트(`AnthropicBedrockMantle`, IAM 자격 증명 사용) 권장
  - **Anthropic에는 임베딩 모델이 없음.** Bedrock 임베딩(Titan Text Embeddings V2는 최대 1024차원, Cohere Embed는 오사카 제공·1536차원 지원 여부 미확인)으로 바꾸면 server DB `vector(1536)`(#66)과 저장 벡터를 바꿔야 할 수 있음
- 이 환경에는 AWS 자격 증명이 없어 Bedrock 실제 호출은 확인하지 못함

## 결론(제안)

- (a) LLM 3곳(채팅 해석·의견서·이관 제안)은 Bedrock 전환 가능. 임베딩은 별도 결정 필요(당분간 Gemini 유지 제안)
- (b) Bedrock 게이트웨이 + Bedrock 우선·Gemini 폴백 + 실측 재검증: 약 1.5~2일. EC2(IAM Role)에서 지연·품질 실측 필요
- (c) 전환 전까지는 Gemini 유지. 키는 `.env` 대신 AWS Secrets Manager·SSM Parameter Store에 두고 IAM Role로 읽으면 키 유출 위험을 줄일 수 있음

## 남은 일·확인 필요

- 사용자·인프라 결정: Bedrock 전환 진행 여부, 사용할 모델(Haiku 5.5 접근 승인 여부), 임베딩 provider
- 진행 시 EC2 또는 Bedrock 호출 가능한 자격 증명으로 실측 필요
- 참고: [Bedrock 리전별 모델](https://docs.aws.amazon.com/bedrock/latest/userguide/models-region-compatibility.html), [Claude Haiku 5.5 모델 카드](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-haiku-5-5.html), [Claude in Amazon Bedrock](https://platform.claude.com/docs/en/build-with-claude/claude-in-amazon-bedrock)
