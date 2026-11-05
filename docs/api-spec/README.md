# API 명세 (구현 기준)

Notion「API 명세서」가 정본이고, 이 디렉터리는 저장소에 구현된 범위를 기록한다. 구현이 바뀌면 같은 PR에서 해당 문서를 갱신한다. 진행 상황·남은 일은 루트 [history](../../history/README.md)에 날짜별로 남긴다.

| 문서 | 범위 |
| --- | --- |
| [common.md](common.md) | Base URL, 오류 형식, 페이지네이션, 멱등성 |
| [auth.md](auth.md) | 인증·직원 (AUTH) |
| [parts.md](parts.md) | 부품·기준 정보 (SET) |
| [master-data.md](master-data.md) | 카테고리·공급사·설비·정비·캘린더 (SET) |
| [chat.md](chat.md) | 채팅 기록 (CHAT) |
| [events.md](events.md) | 실시간 이벤트 (NOT-03) |
| [ledger.md](ledger.md) | 원장 정정 (LED-02) |
| [audit.md](audit.md) | 장부 검증·실사 (AUD) |
| [external.md](external.md) | 외부 요인 현황 (DSH-03) |
| [notifications.md](notifications.md) | 알림 목록·읽음 (NOT-01·02) |
| [system.md](system.md) | 설정·시스템 (SYS) |
| [dev.md](dev.md) | 개발·시연 전용 API (DEV) |
| [jobs.md](jobs.md) | 배치 실행과 예약 |
