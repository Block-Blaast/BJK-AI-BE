# 실시간 이벤트 API

## NOT-03 GET /api/v1/events (SSE)

- 권한: 로그인한 모든 사용자. `Authorization: Bearer` 헤더로 인증한다. 브라우저 기본 `EventSource`는 헤더를 못 붙이므로 화면은 fetch 기반 SSE 클라이언트를 쓴다.
- 응답: `text/event-stream`. 화면은 이벤트를 받으면 해당 API를 다시 조회한다.
- 같은 회사 이벤트만 보낸다(`events` 테이블 RLS).
- `Last-Event-ID` 헤더가 있으면 그 id 다음 이벤트부터, 없으면 연결 이후 이벤트부터 보낸다. 숫자가 아니면 없는 것으로 본다.

```txt
retry: 3000

id: 9182
event: stock.changed
data: {"part_id":"...","stock":2}

: keepalive
```

| 이벤트 | 데이터 | 언제 | 구현 |
| --- | --- | --- | --- |
| `stock.changed` | `part_id`, `stock` | 원장 기록 (채팅 확정, 폼 입력) | ○ |
| `review.created` | `review_id`, `entry` | 검토 생성 | ○ |
| `review.progress` | `review_id`, `step`, `at` | 검토 단계 진행 ([reviews.md](reviews.md)) | ○ |
| `review.decided` | `review_id`, `status` | 결정 | 검토 결정 Issue에서 |
| `audit.flagged` | `audit_flag_id`, `part_id`, `level` | 의심 항목 생성 | 장부 검증 Issue에서 |

### 동작

- 이벤트는 업무 기록과 같은 트랜잭션에 저장한다(`bjk_server.events.publish`). 기록이 롤백되면 이벤트도 남지 않는다.
- 연결마다 2초 간격으로 새 이벤트를 조회한다. 서버 프로세스가 여러 개여도 같은 테이블을 보므로 따로 맞출 필요가 없다.
- 먼저 id를 받았지만 늦게 커밋된 이벤트가 빠지지 않도록, 최근 30초 이벤트는 id와 관계없이 다시 보고 이미 보낸 id는 건너뛴다.
- 15초 동안 보낼 이벤트가 없으면 `: keepalive` 주석을 보낸다.
- 연결은 5분 뒤 서버가 닫는다. 클라이언트는 `retry`(3초) 뒤 `Last-Event-ID`를 붙여 다시 연결하고, 이때 토큰도 다시 검증된다.

| 상황 | 응답 |
| --- | --- |
| 토큰 없음·만료 | 401 `UNAUTHORIZED` |

- 현재 구현 범위: `stock.changed`, `review.created`, `review.progress` 발행. 오래된 이벤트 정리 배치는 아직 없다.
