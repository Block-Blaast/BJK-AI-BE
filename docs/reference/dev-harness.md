# 개발 하네스

> 이슈(작업 단위) 하나 기준. 매번 처음부터 반복.

---

## 0. 시작 전 — 읽을 문서

- [AGENTS.md](../../AGENTS.md): 이슈·브랜치·커밋·PR 공통 규칙, 설계 원칙
- [docs/collaboration.md](../collaboration.md): Issue·PR 양식과 자동 검사
- Notion「발주콕 기능명세서」의 해당 기능 행

멈추고 물어볼 조건:
- 요구가 두 가지 이상으로 읽힐 때
- server ↔ ai 계약(`packages/contracts`)을 바꿔야 할 때
- DB 스키마 변경이 기존 데이터를 손상시킬 수 있을 때
- 외부 연동(LLM 제공자 등) 동작이 바뀔 때

---

## 1. 최신 코드 동기화

```bash
git switch main && git pull --ff-only origin main
make install
```

---

## 2. 이슈 등록

제목은 한국어로 `<type>: <작업 내용>` (`feat` · `fix` · `chore` · `refactor`).
본문은 `docs/collaboration.md`의 Issue 양식을 따른다.

```bash
gh issue create --title "feat: 오늘의 발주 리포트 조회 추가"
```

---

## 3. 개발 플랜 (코드 전에 먼저)

```bash
git switch -c feat/<english-slug>/#<issue-number>
```

플랜에 포함:
1. 생성·수정 파일 목록
2. 스키마 변경이 필요하면 마이그레이션 계획
3. 검증 방법 — 단계별 `→ verify:` 형태로
4. §0 "멈추고 물어볼 조건" 해당 여부

---

## 4. 개발

**금지**
- `apps/server`와 `apps/ai` 사이의 직접 import(`packages/contracts`로만 주고받기)
- 계산·판정·검증 로직에서 LLM 호출
- 로그·에러 메시지에 토큰·API 키·비밀번호 노출
- 기존 마이그레이션 파일 수정(추가만)
- 요청하지 않은 리팩터링, 인접 코드 "개선"

**따를 것**
- `ruff` 규칙(`make format`)
- ai 호출 실패·시간 초과 시의 대체 경로를 같이 만든다

---

## 5. 테스트

```bash
make test
```

유스케이스마다 테스트 최소 2건: 정상 경로 1건 + 실패/권한 거부 경로 1건.

---

## 6. 2차 검증

```bash
make lint                                                           # 오류 없어야 함
grep -rn "TODO\|FIXME" $(git diff --name-only main..HEAD | grep '\.py$')
git diff main..HEAD | grep -in "password\|secret\|api_key\|token"  # 로그 노출 확인
```

---

## 7. API 확인

엔드포인트를 추가·변경했으면 `make server` 후 `/docs`에서 요청·응답·에러 코드를 확인한다.

---

## 8. 자체 코드리뷰

```bash
git diff main..HEAD
```

- [ ] 모든 변경 라인이 이슈에 직접 대응되는가
- [ ] 요청 범위 밖 파일 수정 없음
- [ ] 로그에 비밀 정보 없음
- [ ] TODO/FIXME 없음
- [ ] `make test` · `make lint` 깨끗함

---

## 9. 커밋·푸시

목적별로 쪼개서, 한국어 제목으로 커밋한다.

```bash
git add <파일>
git commit -m "feat: 오늘의 발주 리포트 조회 엔드포인트 추가"
git push -u origin HEAD
```

---

## 10. API 명세서 동기화

/docs/api-spec 패키지에 변경 사항에 따라 API 명세서를 업데이트 및 추가한다.

---

## 11. Draft PR 생성

```bash
gh pr create --draft \
  --base main \
  --title "feat: <english-slug>/#<issue-number>"
```

PR 본문은 `docs/collaboration.md`의 PR 양식을 따른다.

---

## 12. 보고

사용자에게 보고할 내용: 무엇을 바꿨는지 · 어떻게 검증했는지(명령과 결과) ·
남긴 것과 그 이유 · PR 링크.
