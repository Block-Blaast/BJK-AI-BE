# 작업 기록

AI·server 영역 작업 기록 색인. 작성 규칙은 [docs/ai-work-rules.md](../docs/ai-work-rules.md) 3장을 따른다. 최신 항목이 위로 온다.

| 날짜 | 파일 | 내용 |
| --- | --- | --- |
| 2026-11-05 | [2026-11-05-49-morning-briefing.md](2026-11-05-49-morning-briefing.md) | 아침 브리핑 DSH-01(#182)과 briefing 배치, 검토 만료·브리핑 알림 |
| 2026-11-05 | [2026-11-05-48-chat-query-incoming.md](2026-11-05-48-chat-query-incoming.md) | 채팅 재고 조회 답변에 입고 예정 추가(#22), 792개 통과 |
| 2026-11-05 | [2026-11-05-47-review-decision.md](2026-11-05-47-review-decision.md) | 검토 결정 REV-05와 발주 생성, 결정 직전 스냅샷 갱신, DB 포함 802개 통과 |
| 2026-11-05 | [2026-11-05-46-review-pdf.md](2026-11-05-46-review-pdf.md) | 결재용 PDF API(REV-07), WeasyPrint·한글 글꼴 |
| 2026-11-05 | [2026-11-05-45-purchase-order-list-cancel.md](2026-11-05-45-purchase-order-list-cancel.md) | 발주 목록·주문 취소 API(PO-01·04), DB 포함 724개 통과 |
| 2026-11-05 | [2026-11-05-44-receipt-po-match.md](2026-11-05-44-receipt-po-match.md) | 입고와 발주 대조(`po_match`, 실제 납기, `po_id`), DB 포함 753개 통과 |
| 2026-11-05 | [2026-11-05-43-chat-purchase-request.md](2026-11-05-43-chat-purchase-request.md) | 채팅·폼 발주 요청으로 직원 요청 검토 생성(#153), 공급사 표현 해석, 742개 통과 |
| 2026-11-05 | [2026-11-05-42-review-questions.md](2026-11-05-42-review-questions.md) | 검토 후속 질문 API(REV-06), 양식 답변 |
| 2026-11-05 | [2026-11-05-41-missed-scan.md](2026-11-05-41-missed-scan.md) | 놓친 발주 스캔 배치(F-MISSED-01), 중복 방지 |
| 2026-11-05 | [2026-11-05-40-review-clarify.md](2026-11-05-40-review-clarify.md) | 보류 검토 보완 API(REV-03), 같은 검토 재실행 |
| 2026-11-05 | [2026-11-05-39-dashboard-summary.md](2026-11-05-39-dashboard-summary.md) | 대시보드 요약 DSH-02(#180), 묶인 재고 180일 미출고 기준, 주문 대기는 발주 연결 전 0 |
| 2026-11-05 | [2026-11-05-38-part-merge.md](2026-11-05-38-part-merge.md) | 중복 부품 후보 탐지 `weekly-merge`, MAT-01·02 병합, 병합 재고 합산(#209), 714개 통과 |
| 2026-11-05 | [2026-11-05-37-policy-main-only.md](2026-11-05-37-policy-main-only.md) | dev 대상 PR 협업 정책 검사 중단, main·Issue 검사 유지 |
| 2026-11-05 | [2026-11-05-36-ci-main-only.md](2026-11-05-36-ci-main-only.md) | dev CI 실행 중단(main 대상 PR만 CI), main 배포 유지 |
| 2026-11-05 | [2026-11-05-35-review-recheck.md](2026-11-05-35-review-recheck.md) | 재검토 미리 보기 API(REV-04), 같은 수정 값이면 같은 해시 |
| 2026-11-05 | [2026-11-05-34-purchase-orders.md](2026-11-05-34-purchase-orders.md) | 발주 테이블(0026)과 열린 발주·최근 단가 조회 함수, DB 포함 705개 통과 |
| 2026-11-05 | [2026-11-05-33-review-run.md](2026-11-05-33-review-run.md) | 검토 실행·저장 서비스, 스냅샷 수집, 의견서 ai 호출 |
| 2026-11-05 | [2026-11-05-32-hidden-stock-confirmed.md](2026-11-05-32-hidden-stock-confirmed.md) | nightly H_c·H_u 분리, 최근 실사·의심 여부 판정 순수 함수 |
| 2026-11-05 | [2026-11-05-31-lane-c-chat-batch.md](2026-11-05-31-lane-c-chat-batch.md) | 레인 C 채팅 기능(#179·#186·#192) 통합 브랜치로 묶어 dev 반영(#200) |
| 2026-11-05 | [2026-11-05-30-chat-multi-item-cards.md](2026-11-05-30-chat-multi-item-cards.md) | 채팅 여러 품목을 품목별 확인 카드로 응답(#192), 556개 통과 |
| 2026-11-05 | [2026-11-05-29-chat-maintenance-done.md](2026-11-05-29-chat-maintenance-done.md) | 채팅 MAINTENANCE_DONE 의도를 정비 완료 확인 카드로 연결(#186), 558개 통과 |
| 2026-11-05 | [2026-11-05-28-chat-count-answer.md](2026-11-05-28-chat-count-answer.md) | 채팅 COUNT 의도를 실사 응답(AUD-03)으로 연결(#179), 558개 통과 |
| 2026-11-05 | [2026-11-05-27-notifications.md](2026-11-05-27-notifications.md) | 알림 저장·목록·읽음(#183), 중복 방지와 조용한 시간 보류, 마이그레이션 0025 |
| 2026-11-05 | [2026-11-05-26-part-excel-import.md](2026-11-05-26-part-excel-import.md) | 부품 엑셀 이관 SET-01·02, ai 제안과 정규식 대체 경로, DB 포함 588개 통과 |
| 2026-11-05 | [2026-11-05-25-part-detail-dev-merge.md](2026-11-05-25-part-detail-dev-merge.md) | #137 dev 반영, 충돌 양쪽 유지, 마이그레이션 0021~0023으로 변경 |
| 2026-11-05 | [2026-11-05-25-expired-rows-cleanup.md](2026-11-05-25-expired-rows-cleanup.md) | `cleanup` 배치(#185), 호출 제한·PIN 잠금·멱등 키 만료 행 삭제 |
| 2026-11-05 | [2026-11-05-25-expired-rows-cleanup.md](2026-11-05-25-expired-rows-cleanup.md) | `cleanup` 배치(#185), 호출 제한·PIN 잠금·멱등 키 만료 행 삭제 |
| 2026-11-05 | [2026-11-05-24-llm-daily-token-quota.md](2026-11-05-24-llm-daily-token-quota.md) | 회사별 LLM 일일 토큰 상한(#172), `system.llm_daily_tokens`, 초과 시 `quota_exceeded` 대체 |
| 2026-11-05 | [2026-11-05-23-chat-intent-handlers.md](2026-11-05-23-chat-intent-handlers.md) | 채팅 의도별 처리기 파일 분리와 등록 표(#174), 554개 통과 |
| 2026-11-05 | [2026-11-05-22-chat-idempotency-port.md](2026-11-05-22-chat-idempotency-port.md) | #68 멱등 요청 사용자·본문 검증 dev 이식, 마이그레이션 0020, 566개 통과 |
| 2026-11-05 | [2026-11-05-21-llm-usage-docs.md](2026-11-05-21-llm-usage-docs.md) | LLM 사용처 문구를 ai 엔드포인트 네 곳에 맞춤, server 할 일 목록 정정(#170) |
| 2026-11-05 | [2026-11-05-21-ai-warmup-opinion-budget.md](2026-11-05-21-ai-warmup-opinion-budget.md) | ai 시작 시 Bedrock 워밍업, 의견서 예산 7초, 검토 10초 안에서만 재작성 |
| 2026-11-05 | [2026-11-05-20-inventory-concurrency-port.md](2026-11-05-20-inventory-concurrency-port.md) | #69 부품 행 잠금 이식, 채팅 기록·원장 정정·실사 응답에 공통 잠금 적용 |
| 2026-11-05 | [2026-11-05-20-bedrock-runtime-claude.md](2026-11-05-20-bedrock-runtime-claude.md) | 오사카 Mantle 없음 → Claude를 bedrock-runtime·global 추론 프로필로 변경 |
| 2026-11-05 | [2026-11-05-19-embedding-migration-main.md](2026-11-05-19-embedding-migration-main.md) | main 0012(1024)과 dev 0019 충돌 해결, 0019는 1024가 아닐 때만 변경, 554개 통과 |
| 2026-11-05 | [2026-11-05-18-server-ai-integration.md](2026-11-05-18-server-ai-integration.md) | server ↔ ai 채팅 해석·임베딩 연동(#154), llm_calls, vector(1024), RRF 매칭, DB 포함 552개 통과 |
| 2026-11-05 | [2026-11-05-18-embedding-dim-check.md](2026-11-05-18-embedding-dim-check.md) | server 1024차원 변경(#157·#159) 대조, #159 실제 HTTP·DB 확인, 두 PR 충돌 |
| 2026-11-05 | [2026-11-05-17-ai-stack-merge.md](2026-11-05-17-ai-stack-merge.md) | AI PR 10개 dev 머지, 색인 충돌 해결, DB 포함 500개 통과, server AI 연동은 아직 없음 |
| 2026-11-05 | [2026-11-05-16-ai-integration-doc.md](2026-11-05-16-ai-integration-doc.md) | server ↔ AI 연동 안내 문서, 예시 코드 실행 확인 |
| 2026-11-05 | [2026-11-05-15-stack-sync-dev.md](2026-11-05-15-stack-sync-dev.md) | AI PR 스택을 최신 dev에 맞춤(merge), compose ai 설정, DB 포함 385개 통과 |
| 2026-11-05 | [2026-11-05-14-bedrock-provider.md](2026-11-05-14-bedrock-provider.md) | LLM·임베딩 Bedrock 전환(Claude Mantle, Titan V2 1024차원), Gemini는 LLM 폴백 |
| 2026-11-05 | [2026-11-05-13-bedrock-feasibility.md](2026-11-05-13-bedrock-feasibility.md) | Bedrock(Anthropic) 전환 가능성 검토: 구조·작업량·임베딩 문제 |
| 2026-11-05 | [2026-11-05-12-ai-status-review.md](2026-11-05-12-ai-status-review.md) | AI 전체 점검: 실제 동작, dev 시험 머지 374개 통과, server와 어긋난 9건 |
| 2026-11-05 | [2026-11-05-11-review-langgraph.md](2026-11-05-11-review-langgraph.md) | 검토 처리 단계 LangGraph 그래프·진행 단계, 이전 "구현 완료" 보고 바로잡기 |
| 2026-11-05 | [2026-11-05-10-import-suggest.md](2026-11-05-10-import-suggest.md) | 엑셀 이관 규격 추출·카테고리 제안 엔드포인트, 실제 Gemini 13줄 확인 |
| 2026-11-05 | [2026-11-05-09-review-followup.md](2026-11-05-09-review-followup.md) | 재검토 미리 보기·갱신 판단, 후속 질문 주제 분류·양식 답변 |
| 2026-11-05 | [2026-11-05-08-server-perf-1000-parts.md](2026-11-05-08-server-perf-1000-parts.md) | 부품 1,000종 nightly 4.0초·채팅 매칭 36ms 측정, compose 기동 확인 |
| 2026-11-05 | [2026-11-05-08-opinion-verify-template.md](2026-11-05-08-opinion-verify-template.md) | 의견서 숫자 검증·양식 의견서·재작성 흐름, 실제 Gemini 6건 통과 |
| 2026-11-05 | [2026-11-05-07-server-todo.md](2026-11-05-07-server-todo.md) | server 스택 앞으로 할 일 31단계 (시연 경로 나머지, ai 연동, B 단계, 운영 준비) |
| 2026-11-05 | [2026-11-05-07-review-engine.md](2026-11-05-07-review-engine.md) | 발주 검토 판정 엔진 `packages/review`, F-REVIEW-10 예시 고정 |
| 2026-11-05 | [2026-11-05-06-server-deferred.md](2026-11-05-06-server-deferred.md) | server 스택 남겨둔 점 (ai 파트, 선행 기능 대기 항목, 미검증 항목) |
| 2026-11-05 | [2026-11-05-06-review-opinion-endpoint.md](2026-11-05-06-review-opinion-endpoint.md) | 의견서 문장 엔드포인트, 실제 Gemini 호출 확인, 이벤트 루프 문제 수정 |
| 2026-11-05 | [2026-11-05-05-worktree-cleanup.md](2026-11-05-05-worktree-cleanup.md) | 원래 폴더의 복사본 정리, 작업 위치 규칙 추가 |
| 2026-11-05 | [2026-11-05-05-server-considerations.md](2026-11-05-05-server-considerations.md) | server 스택 추가로 고려할 점 (스택 운영, 팀 작업 경계, 매칭, 환경, 보안·운영) |
| 2026-11-05 | [2026-11-05-04-server-progress.md](2026-11-05-04-server-progress.md) | server 스택 진행 상황 (PR 26개, API 15종, 테스트 230개, CI 통과) |
| 2026-11-05 | [2026-11-05-04-gemini-chat-embedding-endpoints.md](2026-11-05-04-gemini-chat-embedding-endpoints.md) | Gemini 채팅 해석·임베딩 엔드포인트, 재시도·대체 응답, 테스트 |
| 2026-11-05 | [2026-11-05-03-contracts-chat-embedding-draft.md](2026-11-05-03-contracts-chat-embedding-draft.md) | 채팅 해석·임베딩(1536차원) 계약 스키마 초안, 테스트 8건 |
| 2026-11-05 | [2026-11-05-02-llm-scope-decision.md](2026-11-05-02-llm-scope-decision.md) | LLM 사용처는 정본 명세로 확정, LLM·임베딩 모두 Gemini API로 결정 |
| 2026-11-05 | [2026-11-05-01-project-onboarding.md](2026-11-05-01-project-onboarding.md) | 프로젝트 숙지, AI 영역 범위 정리, 작업 규칙 문서 작성 |
