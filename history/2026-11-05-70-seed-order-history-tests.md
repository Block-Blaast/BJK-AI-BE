# 시드 발주 이력으로 깨진 납기·검토 예시 테스트 분리

- 날짜: 2026-11-05
- 영역: server
- 관련: #264, main 배포 PR #254, #247, #236

## 목적

- main 배포 PR CI의 테스트 12개 실패 수정

## 한 일

- 최신 dev(e25cc14)에서 11개 재현. `test_review_pdf`는 로컬 WeasyPrint 네이티브 라이브러리가 없어 건너뜀
- `tests/conftest.py`: `DemoDB.clear_orders()` 추가
- nightly 전에 시드 발주를 지우도록 수정: `test_review_run.fresh`(검토·재검토·결정·PDF·스냅샷 테스트 공용), `test_nightly.nightly`, `test_holiday_lead_time`, `test_part_detail.fresh`, `test_review_detail`

## 결정과 근거

- 원인: 시드(#247)가 공급사·부품마다 입고 완료 발주(납기 = 기본 납기 + 지터 -1~+3일)를 넣고, nightly(#236)가 이를 실제 납기 표본으로 써서 LT90이 늘어남(예: 볼트 11 → 13, 6205 10 → 13, V벨트 A-42 공급사 A 15일)
- 그 결과 V벨트 검토에 C-08이 더 걸리고(`alternative` 대신 `caution`, 수정안 근거에 C-08), 도착 예정이 필요 시점 뒤로 밀려 O가 0이 됨
- 코드 버그가 아니고 두 기능이 의도대로 함께 동작한 결과. 실패한 테스트는 표본이 없을 때의 기본 납기 공식과 명세 예시 숫자를 확인하는 테스트라 시드 발주와 분리(#247이 다른 3개 파일에 한 방식과 같음)
- 시드·nightly 코드는 바꾸지 않음

## 검증

- 실패 테스트 파일 10개: 70개 통과, 1개 건너뜀(PDF)
- 같은 픽스처를 쓰는 `test_demo_flow`·`test_review_clarify`·`test_review_snapshot_merged`·`test_review_questions`·`test_seed`: 32개 통과
- `make lint` 통과

## 남은 일·확인 필요

- 시연 시드 그대로면 V벨트 A-42 검토가 명세 예시 1과 다르게 나옴(C-08 추가, 표시 `caution`). 시연 화면을 명세 예시에 맞출지는 사용자·레인 B 판단 필요
- PDF 테스트는 CI에서 확인
