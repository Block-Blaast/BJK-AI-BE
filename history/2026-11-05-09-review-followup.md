# 재검토 미리 보기와 후속 질문 양식 답변

- 날짜: 2026-11-05
- 영역: AI (검토 엔진)
- 관련: Issue #79, Draft PR #80(→ #77 브랜치), 브랜치 `feat/review-followup/#79`(#77 브랜치 위에 쌓음), F-REVIEW-09, REV-04·05·06

## 목적

- F-REVIEW-09의 세 상황을 엔진 쪽 순수 함수로 제공: 직접 수정 재검토, 승인 직전 스냅샷 갱신 판단, 후속 질문

## 한 일

- `packages/review/src/bjk_review/recheck.py`
  - `recheck(스냅샷, 수정 값)`: 같은 스냅샷으로 다시 판정, 결과 `review_hash` = REV-04 `recheck_hash`
  - `needs_refresh(스냅샷, now, part_moved_since)`: 24시간 초과 또는 같은 부품 입출고
  - `decision_changed(전, 후)`: 판정 또는 수정안(수량·공급사·단가) 변경. REV-05 `SNAPSHOT_REFRESHED` 판단용
- `packages/review/src/bjk_review/questions.py`
  - `classify(질문)`: 낱말로 주제 분류(`risk` → `urgency` → `supplier` → `price` → `qty` 순서로 먼저 걸리는 것)
  - `answer_question(질문, 검토 결과, 스냅샷)`: 주제별 양식 답변과 근거 기호(`evidence_refs`)
- `test_followup.py`: 재검토·갱신 판단·변경 판단, 주제 분류, 주제별 답변, 근거 없음

## 결정과 근거

- **재검토는 `run_review` 그대로:** 직접 수정도 같은 스냅샷·같은 규칙이어야 같은 판정(설계 원칙 2). 해시로 미리 본 결과와 승인 시 결과가 같은지 대조 가능
- **현재 시각은 인자로 받음:** `needs_refresh`도 순수 함수로 유지
- **답변은 스냅샷 숫자만:** 없는 것은 "근거 데이터에 없습니다."(REV-06). 보류 건은 근거 계산이 없어 항상 이 답변
- **REV-06 예시 그대로 고정:** "왜 0개야?" → `qty`, 예시 문장, `["R", "S", "O", "D95"]`
- **분류 낱말:** 처음엔 "급"을 긴급 낱말로 넣었다가 "공급사"에도 걸려 공급사 질문이 긴급으로 분류됨(테스트에서 발견). "급해·급한·긴급" 등 구체적인 낱말로 바꿈
- **수량 답변:** 발주 불필요면 합계 > D95 설명, 수량을 바꿨으면 권장량 계산 설명, 그대로면 바꿀 근거 없음. 미확인 숨은 재고가 있으면 "실사 전이라 빼지 않았습니다"를 덧붙임(설계 원칙 9)
- **공급사 답변:** C-08 교체, C-05 교체, 대안만 표시(6203), 유지를 구분
- **위험 답변:** 소진 예상일·멈추는 설비·예상 손실·외부 위험(주의 이상)만. 없으면 근거 없음

## 검증

- `uv run pytest`: 112개 통과(검토 77개). `ruff check`, `ruff format --check` 통과
- 커버리지: `bjk_review` 95%(questions 83%, recheck 93%)
- REV-04 예시(V벨트 6개로 직접 수정 → C-01 facts `Q: 6`, 수정안 0개, 수정 권고) 확인

## 남은 일·확인 필요

- 분류 낱말은 경험치. 실제 질문이 쌓이면 조정. LLM 자유 답변(`mode: "llm"`)은 확장
- server 연동: REV-04는 `recheck`, REV-05는 `needs_refresh` → 새 스냅샷 `run_review` → `decision_changed`, REV-06은 `answer_question`
- 검토 과정(F-REVIEW-01~10) 중 엔진 쪽 구현은 이번으로 마무리. 남은 AI 작업은 엑셀 규격·카테고리 제안(F-SETUP-02)
