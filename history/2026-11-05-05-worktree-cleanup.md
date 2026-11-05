# 원래 폴더의 복사본 정리와 작업 위치 규칙

- 날짜: 2026-11-05
- 영역: AI
- 관련: Issue #67, PR #70

## 목적

- 원래 폴더 `BJK-AI-BE`에 남아 있던 AI 작업 복사본 제거
- AI 작업을 별도 worktree에서 하는 이유와 규칙 문서화

## 한 일

- 원래 폴더(server 에이전트가 `feat/health-status/#53`로 사용 중)에서 커밋되지 않은 제 복사본 제거
- 제거 대상: `packages/contracts/src/bjk_contracts/{chat,common,embedding}.py`, `apps/ai/tests/test_contracts.py`, `docs/ai-work-rules.md`, `history/` 4개 파일
- `packages/contracts/src/bjk_contracts/__init__.py`는 제가 더한 35줄만 있어 `git restore`로 되돌림
- 원래 폴더의 staged `about_project/` 변경은 건드리지 않음
- `docs/ai-work-rules.md`에 4장 "작업 위치" 추가

## 결정과 근거

- 제거 전 `feat/ai-contracts-chat-embedding/#61` 브랜치의 커밋과 비교: 9개 파일은 내용이 같고, `history/2026-11-05-03-...`은 브랜치에 더 최신 버전이 있음. 잃는 내용 없음
- 원래 폴더에서 브랜치를 바꾸면 server 에이전트의 작업 파일이 바뀌므로 AI 작업은 worktree에서 계속함

## 검증

- 정리 후 원래 폴더 `git status --short`: staged `about_project/` 8개만 남음 확인

## 남은 일·확인 필요

- 없음
