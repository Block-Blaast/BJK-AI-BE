# 프로젝트 숙지와 AI 작업 규칙 수립

- 날짜: 2026-11-05
- 영역: AI
- 관련: F-CHAT-01, F-SETUP-02, F-MATCH-01, F-REVIEW-01·08·09, CHAT-01, SET-01, REV-02, REV-06

## 목적

- `about_project/` 문서로 발주콕의 목적·원칙·기능을 숙지하고, AI 영역이 맡을 범위를 정리
- 작업마다 기록을 남기는 규칙을 문서로 고정

## 한 일

- `about_project/` 7개 문서와 `AGENTS.md`, `CLAUDE.md`, `docs/collaboration.md`, `docs/reference/dev-harness.md`, `origin/dev`의 `docs/work-areas.md` 확인
- `docs/ai-work-rules.md` 작성: 담당 범위, 원칙, history 기록 규칙과 양식, 명세 충돌 시 처리
- `history/README.md` 색인과 이 기록 작성
- 코드 변경 없음

## 프로젝트 요약

- 발주콕: 작업자가 채팅 한 줄로 입출고를 기록하면, 창고 숫자와 외부 요인(해상운임·명절·환율)을 근거로 **사람이 올린 발주가 맞는지 검토**해 사장님이 원클릭으로 결정하게 하는 영세 제조 현장용 서비스
- 원칙: 숫자는 알고리즘, 해석은 AI, 결정은 사람. 같은 입력이면 같은 판정. LLM이 멈춰도 계산·판정·승인은 동작
- 구성: FastAPI + PostgreSQL(pgvector). 레포는 uv 모노레포로 `apps/server`, `apps/ai`, `packages/contracts`. 앱끼리 직접 import 금지, 계약 스키마로만 주고받음
- 현재 코드 상태: `apps/ai`는 `/health`만 있음. `packages/contracts`는 빈 패키지. 원격 브랜치 중 `apps/ai`·`packages/contracts`를 바꾼 브랜치 없음(server 쪽은 인증·채팅·배치 등 다수 진행 중)

## AI 영역이 맡을 일 (명세 기준)

| 기능 | 입력 | 출력 | 실패 시 |
| --- | --- | --- | --- |
| 채팅 해석 F-CHAT-01 | 원문(500자 이하) | intent(`OUT`/`IN`/`COUNT`/`QUERY`/`PURCHASE_REQUEST`/`MAINTENANCE_DONE`/`OTHER`), items[part_text, qty, unit, equipment, supplier_text, unit_price, note]. tool calling으로 스키마 강제 | 1회 재시도 후 server가 폼 카드, `ai.fallback: true` |
| 규격·카테고리 제안 F-SETUP-02 | 엑셀 줄의 부품 이름, 등록된 카테고리 목록 | 규격(JSONB), 카테고리 + 확신도(목록 안에서만 선택) | 규격은 정규식만, `suggested_category: null` |
| 의견서 문장 F-REVIEW-08 | 판정, 걸린 체크의 근거 숫자, 수정안, 리스크, 대안 | 고정 구성의 의견서 문장. 검증 실패 항목을 받으면 재작성(최대 2회) | server가 양식 의견서, `opinion.source: template` |

- 처리 기준: 채팅은 확인 카드까지 3초 이내, 검토는 의견서까지 10초 이내
- 공급사 표현("저번 데")은 LLM이 문자열만 뽑고 실제 공급사 해석은 코드가 함
- 숫자 검증(허용 목록 대조·판정 단어·누락 체크)은 코드가 함. CLAUDE.md 구조상 server 쪽 검증 엔진에 속함
- 후속 질문(REV-06)은 MVP에서 주제 분류 + 양식 답변, LLM 자유 답변은 확장
- 공통: 회사별 일일 토큰 상한, 호출별 토큰·지연 기록(`llm_calls`), 이유 코드 `timeout`/`error`/`schema_invalid`/`quota_exceeded`/`verify_failed`

## 결정과 근거

- history 파일 이름은 `YYYY-MM-DD-NN-<slug>.md`로 정함. 하루 여러 작업을 순서대로 구분하기 위함
- `CLAUDE.md`·`AGENTS.md`는 수정하지 않음. server 에이전트와 함께 쓰는 파일이고, 이번 요청은 docs 폴더에 규칙을 두는 것

## 검증

- 문서 작업만 진행. 테스트·린트 대상 아님

## 남은 일·확인 필요

- **LLM 사용처 불일치:** `CLAUDE.md`·`AGENTS.md`·`docs/work-areas.md`(dev)는 LLM 호출 지점을 "채팅 해석, **별칭 후보 순위**, 리포트 설명"으로 적음. 정본 `01`은 "채팅 해석, **엑셀 규격·카테고리 제안**, 의견서"이고 매칭 순위는 LLM이 매기지 않음(F-MATCH-01). 어느 쪽을 따를지 확인 필요
- **임베딩 위치:** 부품 이름 임베딩(BGE-M3 등, F-SETUP-02 5단계·F-MATCH-01 4단계)을 `apps/ai`가 계산할지 server가 직접 할지 미정
- **LLM 제공자·모델:** 명세는 "tool calling 지원 상용 API"만 지정. 제공자와 API 키 관리 방식 확인 필요
- **의견서 검증 위치:** 숫자 검증과 재작성 루프(LangGraph 6·7단계)를 server가 돌리고 ai는 문장 생성만 할지 확인 필요
- 다음 작업 후보: server와 합의 후 `packages/contracts`에 채팅 해석 요청·응답 스키마부터 정의(시연 경로 CHAT-01 ★)
