# API 명세 문서를 현재 구현에 맞게 수정

- 날짜: 2026-11-05
- 영역: server
- 관련: #270

## 목적

- `docs/api-spec`의 권한·요청·응답·오류 설명을 `apps/server` 구현과 일치

## 한 일

- 경로 대조: 서버 OpenAPI 경로 83개와 문서 경로 일치 확인(누락·여분 없음)
- 구현된 기능을 미구현으로 적은 서술 수정: 대시보드 `awaiting_order`, 검토 스냅숏 O·`price_stats`, REV-07 PDF, 채팅 ai 해석, `review.decided` 이벤트, 웹 푸시 발송
- 권한·입력 의미 수정: 기준 정보 조회도 manager 이상, 정비 `required_parts: []`는 필요 부품 없음, 이관 미리보기 차이 목록에 새 부품 포함
- 오류 보완: common 오류 표 `IDEMPOTENCY_CONFLICT`, REV-05 오류 표와 `recheck_hash` 409 detail, 429 `detail.retry_after_seconds`
- 응답 필드 보완: 대시보드·브리핑 응답 구조, CHAT-03 `po_match`·`actual_lead_time_days`, 정비 `completed_by`, 공급사 거래 조건 PUT 응답, 설정 `llm_daily_tokens`, nightly `embeddings_filled`
- 코드 쪽 미구현 동작은 현재 상태로 명시

## 남은 일·확인 필요

- 부품 상세 `stock.ledger_status`가 `normal` 고정이라 목록(`suspect`)과 다름
- `stock.changed`가 채팅 확정·폼 입력에서만 발행(원장 정정, 실사 조정, 엑셀 이관, 부품 등록 초기 재고 제외)
- `audit.flagged` 미발행
- 알림 `review_completed`, `review_urgent`, `count_request`, `maintenance_check` 생성처 없음
- `infra/cron/crontab`에 `push` 작업 없음
