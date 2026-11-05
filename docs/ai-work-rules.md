# AI 영역 작업 규칙

AI 영역(`apps/ai`, `packages/review`, `packages/contracts`의 ai·검토 관련 스키마)을 맡은 에이전트가 따르는 규칙이다. server 로직은 다른 에이전트가 맡으며, 이 문서는 협업 공통 규칙(`AGENTS.md`, `docs/collaboration.md`, `docs/reference/dev-harness.md`)에 더해 지킨다.

## 1. 담당 범위

| 구분 | 내용 |
| --- | --- |
| 담당 | `apps/ai`(`bjk_ai`) LLM 게이트웨이, server ↔ ai 계약 중 ai 호출 스키마(`packages/contracts`) |
| 담당 | 발주 검토 판정 엔진 `packages/review`(`bjk_review`): 보류·체크 9개·수정안·판정, 의견서 숫자 검증·양식 의견서, 재검토, 후속 질문 양식 답변(F-REVIEW, 2026-11-05 사용자 결정) |
| 담당 아님 | `apps/server`의 장부·근거 지표 계산(F-ANAL)·스냅샷 수집·검토 저장·승인·알림 |
| 공동 | 계약 스키마와 검토 스냅샷 형식. 바꾸기 전에 사람에게 확인한다(dev-harness §0) |

검토 엔진은 server가 같은 프로세스에서 실행하는 순수 함수 패키지다. ai 서비스가 멈춰도 판정은 나와야 하기 때문이다(설계 원칙 7). LLM은 의견서 문장만 맡는다.

MVP의 LLM 사용처는 `about_project/01-functional-spec.md` 기준으로 아래 셋이며, 모두 실패 시 대체 경로가 있어야 한다.

| 용도 | 기능 ID | 대체 경로 |
| --- | --- | --- |
| 채팅 해석(tool calling 구조화 추출) | F-CHAT-01 | 폼 입력 카드(F-CHAT-07) |
| 엑셀 이관 규격·카테고리 제안 | F-SETUP-02 | 규격은 정규식만, 카테고리는 직접 선택 |
| 의견서 문장 | F-REVIEW-08 | 정해진 양식 의견서 |
| 부품 이름 임베딩(매칭·중복 후보용 벡터) | F-SETUP-02 5단계, F-MATCH-01 4단계 | (제안, 명세에 없음) 임베딩 없이 규격 필터 + 자모 유사도만으로 후보 제시 |

LLM과 임베딩은 모두 **Gemini API**로 하고, API 키 하나를 `apps/ai`에서만 관리한다(2026-11-05 결정). 로컬 임베딩 모델(BGE-M3 등)은 쓰지 않는다.

### 실행 설정 (`apps/ai`)

| 환경 변수 | 기본값 | 내용 |
| --- | --- | --- |
| `GEMINI_API_KEY` | 없음 | 비어 있으면 Gemini를 부르지 않고 모든 요청에 대체 응답 |
| `GEMINI_CHAT_MODEL` | `gemini-3.5-flash-lite` | 채팅 해석 모델 |
| `GEMINI_EMBEDDING_MODEL` | `gemini-embedding-2` | 임베딩 모델(1536차원으로 받음) |
| `GEMINI_OPINION_MODEL` | `gemini-3.5-flash-lite` | 의견서 문장 모델 |
| `CHAT_BUDGET_SECONDS` | 2.5 | 채팅 해석 재시도 포함 시간 예산 |
| `EMBED_BUDGET_SECONDS` | 10 | 임베딩 재시도 포함 시간 예산 |
| `OPINION_BUDGET_SECONDS` | 3 | 의견서 한 번 호출의 재시도 포함 시간 예산 |

환경 변수는 레포 루트 `.env`(커밋 안 됨)에 둔다. `make ai`가 루트에서 실행되며 이 파일을 읽는다.

## 2. 지킬 원칙

- LLM은 수량·판정·수정안을 만들지 않는다. 숫자는 입력으로 받은 스냅샷 값만 문장에 쓴다.
- 부품 매칭 순위는 LLM이 매기지 않는다(F-MATCH-01: 규격 필터 + 임베딩·자모 유사도 + RRF). `CLAUDE.md`·`AGENTS.md`의 "별칭 후보 순위"와 다르지만 정본 명세를 따르기로 확정했다(2026-11-05, `history/2026-11-05-02-llm-scope-decision.md`).
- 실패·시간 초과·스키마 불일치·토큰 상한 초과는 오류가 아니라 대체 응답으로 돌려준다. 이유 코드는 `02-api-spec.md` 1-6의 `timeout`, `error`, `schema_invalid`, `quota_exceeded`, `verify_failed`를 쓴다.
- LLM 컨텍스트에는 요청한 회사의 데이터만 넣는다(F-AUTH-04).
- 모든 LLM 호출은 용도·입력/출력 토큰·성공 여부·지연 시간을 남길 수 있게 한다(`llm_calls`).
- 로그·에러에 API 키·토큰·비밀번호를 남기지 않는다.

## 3. 작업 기록 (history) 규칙

작업을 할 때마다 레포 루트 `history/` 폴더에 기록을 남긴다. 코드 변경이 없는 조사·문서 작업도 기록한다.

- **파일 이름:** `history/YYYY-MM-DD-NN-<english-slug>.md`. `NN`은 그날의 순번(01부터).
- **색인:** `history/README.md` 표에 한 줄을 추가한다. 최신 항목이 위로 온다.
- **시점:** 작업을 마치는 턴에 작성한다. 작업이 여러 턴에 걸치면 같은 파일을 갱신한다.
- **사실만 쓴다.** 실행하지 않은 테스트를 통과로 적지 않는다. 미검증 항목은 미검증이라고 적는다.
- **기존 기록은 고치지 않는다.** 앞선 기록이 틀렸으면 새 기록에서 바로잡고 앞선 파일 이름을 적는다.

### 기록 양식

```markdown
# <작업 제목>

- 날짜: YYYY-MM-DD
- 영역: AI
- 관련: Issue·PR 번호, 기능 ID(F-…), API ID(CHAT-01 등)

## 목적

- 이 작업을 왜 했는지

## 한 일

- 변경한 내용과 파일 경로

## 결정과 근거

- 정한 것, 그렇게 정한 이유(명세 위치)

## 검증

- 실행한 명령과 결과. 하지 않았으면 "미검증"과 이유

## 남은 일·확인 필요

- 다음 작업, 사람에게 확인할 질문
```

## 4. 작업 위치

- 원래 폴더 `BJK-AI-BE`는 server 에이전트가 자기 브랜치를 체크아웃해 쓴다. AI 작업은 별도 git worktree(`../BJK-AI-BE-ai-contracts-61`)에서 한다.
- 원래 폴더에는 파일을 만들거나 브랜치를 바꾸지 않는다. 브랜치를 바꾸면 server 작업 파일이 통째로 바뀐다.
- worktree는 같은 저장소라 커밋·브랜치·원격을 공유한다. 결과는 PR로 합친다.

## 5. 명세 충돌 시

`about_project/README.md`의 충돌 규칙을 따른다. 기능·규칙은 `01`, API·코드값은 `02`가 정본이고, 레포의 다른 문서와 다르면 임의로 고르지 않고 사람에게 확인한다. 확인 전까지 해당 부분은 구현하지 않고 history의 "확인 필요"에 남긴다.
