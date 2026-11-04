<!-- collaboration-harness:start -->
# 협업 규칙

작업 종류와 사용하는 에이전트에 맞는 `.codex`, `.claude`, `.agent`의 `skills/{issue,branch,commit,pull-request}/SKILL.md`를 읽는다. Issue·Commit·PR 작성 시 `docs/collaboration.md`와 해당 템플릿을 따른다.

- Issue는 한국어 제목과 작업 체크리스트, 완료 기준을 작성한다.
- 브랜치는 `<type>/<english-slug>/#<issue-number>` 형식을 사용한다.
- 커밋은 변경 목적별로 분리하고 `<type>: <한국어 변경 내용>` 형식을 사용한다. 개별 커밋 타입은 브랜치와 달라도 된다.
- PR은 구현 중 Draft로 생성할 수 있다. 본문은 변경 내용·검증 결과·머지 체크리스트·관련 이슈의 개조식으로 작성한다.
- PR에 구현 과정과 서술형 문단을 적지 않는다. 변경 내용과 검증 결과는 각각 1~3개 항목으로 제한한다.
- 미검증 항목은 체크하지 않는다. 실제 검증 후 결과와 체크 상태를 갱신하고 필수 항목 완료 후 머지한다.
- merge commit만 사용하고 제목은 `merge: <head 브랜치 전체 이름>`, 본문은 빈 값으로 지정한다.
- 기존 Issue·PR 기록, 다른 사람의 변경, 저장소 고유 규칙을 보존한다.
<!-- collaboration-harness:end -->

# 발주콕 server·ai 모노레포

기능 정본은 Notion「발주콕 기능명세서」의 SERVER·WEB·APP DB. 명세와 코드가 다르면 명세를 먼저 확인한다.

작업을 시작하거나 Issue 범위를 정할 때 `docs/work-areas.md`의 영역별 책임과 분리 기준을 확인한다. 라벨과 브랜치 운영 제안의 적용 여부는 해당 문서와 실제 저장소 상태를 확인한다.

## 구조

- `apps/server` (`bjk_server`): API 서버. 장부, 계산·판정·검증 엔진, 리포트, 승인
- `apps/ai` (`bjk_ai`): LLM 게이트웨이. 채팅 해석, 별칭 후보 순위, 리포트 설명 문장
- `packages/contracts` (`bjk_contracts`): server ↔ ai 요청·응답 스키마

uv workspace 하나로 묶는다. 앱끼리 직접 import하지 않고 `bjk_contracts`로만 주고받는다.

## 명령

- `make install` / `make test` / `make lint` / `make format`
- `make server` (:8000), `make ai` (:8001), `make up` (docker compose)
- `make db-up` (PostgreSQL :5433), `make migrate` (Alembic 최신 적용)
- `make seed`: 개발 DB를 시연 상태(demo_v1)로 초기화. 시연 계정은 `bjk_server/seed/demo.py`의 `USERS`
- DB 테스트는 `TEST_DATABASE_URL`이 있을 때만 실행 (`.env.example` 참고). CI는 PostgreSQL 서비스와 `REQUIRE_DB_TESTS=1`로 항상 실행

## 설계 원칙

- 계산·판정·검증은 LLM을 쓰지 않는 순수 함수로 만든다. 같은 입력이면 같은 결과.
- LLM 호출 지점은 채팅 해석, 별칭 후보 순위, 리포트 설명 문장 세 곳뿐이며 모두 `apps/ai`를 거친다.
- ai 호출이 실패·시간 초과돼도 server는 대체 경로(버튼 입력, 규칙 결과, 템플릿 문장)로 응답한다.
- 재고는 저장하지 않고 이벤트 합산으로 계산한다. 이벤트는 수정·삭제하지 않고 정정 이벤트를 추가한다.
