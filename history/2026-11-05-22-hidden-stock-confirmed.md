# nightly 확인된 숨은 재고 H_c 계산

- 날짜: 2026-11-05
- 영역: server
- 관련: #187, F-MATCH-03, F-ANAL-09

## 목적

- nightly가 같은 규격 부품 재고를 모두 미확인(H_u)으로 두던 고정값을 해제

## 한 일

- `domain/hidden_stock.py`: 같은 규격 판정 `same_spec`, 확인 판정 `is_confirmed`, 분리 `split_hidden`
- `jobs/nightly.py`: 부품별 마지막 실사 응답 시각(`count_requests.answered_at`)과 열린 의심 항목(`audit_flags.status <> 'closed'`)을 모아 H_c·H_u 계산. 권장 발주량·경로 시뮬레이션은 H_c만 반영
- 테스트: `test_domain_hidden_stock.py`, `test_nightly.py`의 H_c·H_u 4가지 경우

## 결정과 근거

- 확인 기준 일수는 설정 `system.hidden_stock_count_days`(기본 30, SYS-01)
- 장부 상태 의심은 부품 상세 `ledger_status`와 같이 열린 의심 항목 존재로 판단
- 재고가 0 이하인 같은 규격 부품은 숨은 재고에서 제외
- `split_hidden`은 검토 스냅샷 수집(#146)의 `hidden[].confirmed`에 재사용

## 검증

- 검증 대기

## 남은 일·확인 필요

- #137 머지 후 부품 상세 응답 `hidden.H_c` 테스트 추가
