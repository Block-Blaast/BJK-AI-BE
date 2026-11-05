# dev PR 협업 정책 검사 중단

- 날짜: 2026-11-05
- 영역: 공통
- 관련: #217, #214

## 목적

- dev CI 중단(#214)에 이어 dev 대상 PR의 Collaboration Policy 검사도 중단

## 한 일

- `.github/workflows/collaboration-policy.yml`: `pull_request` 트리거를 main 대상으로 한정

## 결정과 근거

- dev 머지는 머지 큐가 로컬 테스트·lint로 검증하므로 PR 양식·머지 준비 검사도 dev에서는 생략
- Issue 양식 검사(`issues` 이벤트)와 main push 정책 테스트는 그대로 둠

## 검증

- 트리거만 바꾼 변경. 이 PR(dev 대상)에서 `Collaboration /` 검사가 돌지 않는 것으로 확인

## 남은 일·확인 필요

- main 대상 배포 PR에서는 검사가 그대로 돌아야 함
