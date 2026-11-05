# 발주 검토 판정 엔진 (보류·체크 9개·수정안·판정)

- 날짜: 2026-11-05
- 영역: AI (검토 엔진)
- 관련: Issue #73, Draft PR #74(→ #71 브랜치), 브랜치 `feat/review-engine/#73`(#71 브랜치 위에 쌓음), F-REVIEW-02~06·10, F-ANAL-09, 부록 A-1, REV-02·04, SYS-01

## 목적

- 사용자 결정으로 검토 과정(F-REVIEW)을 AI 영역이 맡음. 이번에는 판정까지(보류 → 체크 9개 → 수정안 → 판정·표시) 구현
- 맡은 사람이 없던 영역 확인: 검토 관련 Issue 없음, decision-engine은 server의 근거 지표 nightly(#27)뿐

## 한 일

- 팀원 Issue #20(채팅 해석, #67과 중복), #21(별칭 후보 순위, 명세상 LLM 미사용)은 이미 닫혀 있음 확인
- 새 패키지 `packages/review`(`bjk_review`) 추가
  - `models.py`: 스냅샷(`ReviewSnapshot`), 원안(`OrderRequest`), 설정값(`ReviewSettings`), 결과(`ReviewResult`)
  - `pricing.py`: MOQ 배수 올림, 단가 구간, 배송비 포함 총액
  - `checks.py`: C-01~C-09
  - `engine.py`: 보류 판단, 권장량 R, 수정안, 대안, 표시, 판정, `review_hash`, `run_review`
- 루트 `pyproject.toml`: `bjk-review` 워크스페이스 소스, `testpaths`에 `packages/review/tests` 추가
- 테스트: `test_examples.py`(F-REVIEW-10 예시 5개 + 볼트 H_u 변형 + 100회 같은 결과), `test_rules.py`(보류, 경계값, 공급사 교체, 주의, 대안, 설정값)
- `docs/ai-work-rules.md` 담당 범위에 검토 엔진 추가, 깨져 있던 임베딩 표 줄 수정

## 결정과 근거

- **위치: server가 같은 프로세스에서 실행하는 순수 함수 패키지:** `apps/ai`에 두면 ai 서비스가 멈출 때 판정도 멈춤. 설계 원칙 7("LLM이 멈춰도 계산·판정·승인은 동작")과 `CLAUDE.md`의 "ai 실패 시 규칙 결과로 대체"를 지키기 위함. LLM은 의견서 문장만(`apps/ai` `/v1/opinions`)
- **역할 나눔:** 스냅샷 수집(DB 조회: S, O, H, P, part_metrics, 공급사 조건)과 검토 저장·상태·승인은 server. 엔진은 스냅샷만 보고 계산. "오늘"도 스냅샷의 `as_of`를 써서 현재 시각에 의존하지 않음
- **스냅샷 필드는 server 모델에 맞춤:** `part_metrics`(m, d95, d99, t_out, t_deadline, loss, loss_equipment, r_lead, r_price, data_mode), `supplier_parts`(unit_price, moq, `price_tiers` = `[{min_qty, unit_price}]`, shipping_fee), `part_supplier_metrics`(공급사별 LT90)
- **권장량 R은 엔진이 다시 계산:** nightly의 `recommended_qty`는 P(다른 열린 요청)를 빼지 않음. 검토 시에는 P도 빼야 함(F-REVIEW-02, 부록 A-1 7번). MOQ는 요청 공급사 기준
- **금액:** 표시 금액(`total`, `saving`)은 단가 × 수량, 공급사 고를 때만 배송비 포함 총액 비교. F-REVIEW-10 예시 금액(540,000원, 62,000원, 11,000원)이 단가 × 수량이기 때문
- **단가:** 요청에 단가가 있으면 같은 공급사에서는 그 단가 유지(견적일 수 있음). 없으면 수량에 맞는 단가 구간 적용. 공급사를 바꾸면 그 공급사의 구간 단가와 MOQ
- **C-08은 원인을 따로 기록:** `deadline`(마감 5일 이내·지남), `supplier_lead`(요청 공급사 납기로 t_need를 못 맞춤). 공급사 교체는 `supplier_lead`일 때만(F-REVIEW-05). 맞출 곳이 없으면 가장 빠른 곳, 긴급 유지
- **C-05 공급사 교체 기준:** t_need를 맞추는 공급사 중 총액 최저가 요청 공급사 총액 × `c06_ratio`(0.9) 이하일 때만. 아니면 유지하고 주의
- **basis:** 수량이 실제로 바뀐 경우에만 걸린 수량 체크를 넣음. 바뀐 게 없으면 비어 있어 판정 `ok`
- **주의 표시 규칙(해석):** 미확인 숨은 재고(H_u)가 있거나, 발주를 하는데 basis에 없는 경고가 남은 경우. 명세의 "경고는 있지만 수정안으로 해결 불가"를 일반화한 것이며 F-REVIEW-10 예시 5개 표시와 일치
- **대안:** 발주 불필요면 없음. C-06 공급사가 이미 수정안 공급사면 제외(6204 예시에 대안 표시 없음). 단가 구간 대안의 "D99를 넘지 않음"은 S + O + H_c + P + 다음 구간 수량 ≤ D99로 해석
- **C-02 사용 기록 없음:** m + F_12m/12 = 0이면 `note: no_recent_usage`로 걸림
- **판정 재현:** `review_hash` = 스냅샷·원안·설정값의 정렬된 JSON SHA-256. REV-04 `recheck_hash`, REV-05 `snapshot_hash` 대조에 쓸 수 있음
- 테스트 데이터 중 예시 표에 없는 값(공급사 납기·MOQ·배송비, D99, m 등)은 예시 판정이 성립하는 범위에서 정함

## 검증

- `uv run pytest`: 62개 통과(검토 27개 포함)
- F-REVIEW-10 예시 5개 + H_u 변형: 걸린 체크·수정안·절감액·판정·표시 모두 명세와 일치
- 같은 입력 100회 같은 결과·같은 해시 확인
- 커버리지(`pytest-cov`, 일회성 실행): `bjk_review` 99%(명세 기준 80% 이상)
- `ruff check`, `ruff format --check` 통과
- Docker 이미지는 `COPY packages`로 새 패키지를 포함함. 실제 빌드는 CI에서 확인 예정

## 남은 일·확인 필요

- **server 담당에게 알릴 것:** 판정 엔진을 `bjk_review`로 제공. server는 스냅샷을 모아 `run_review` 호출, 결과 저장. `CLAUDE.md` 구조 설명("server: 계산·판정·검증 엔진")과 달라짐
- 다음 단계: 의견서 숫자 검증(허용 목록·판정 일치·누락)과 양식 의견서(F-REVIEW-08), 후속 질문 주제 분류·양식 답변(F-REVIEW-09), 결과 → 의견서 요청(`OpinionRequest`) 변환
- 확인 필요: 단가 구간 대안의 D99 해석, 주의 표시 일반화 규칙
