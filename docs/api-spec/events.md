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
| `stock.changed` | `part_id`, `stock` | 재고가 바뀐 원장 기록, 부품 병합 (아래 발행 경로 참고) | ○ |
| `review.created` | `review_id`, `entry` | 검토 생성 | ○ |
| `review.progress` | `review_id`, `step`, `at` | 검토 단계 진행 ([reviews.md](reviews.md)) | ○ |
| `review.decided` | `review_id`, `status`, `action` | 결정 ([reviews.md](reviews.md) REV-05) | ○ |
| `audit.flagged` | `audit_flag_id`, `part_id`, `level` | 의심 항목 생성 | 미발행 |

### 동작

- 이벤트는 업무 기록과 같은 트랜잭션에 저장한다(`bjk_server.events.publish`). 기록이 롤백되면 이벤트도 남지 않는다.
- 연결마다 2초 간격으로 새 이벤트를 조회한다. 서버 프로세스가 여러 개여도 같은 테이블을 보므로 따로 맞출 필요가 없다.
- 먼저 id를 받았지만 늦게 커밋된 이벤트가 빠지지 않도록, 최근 30초 이벤트는 id와 관계없이 다시 보고 이미 보낸 id는 건너뛴다.
- 15초 동안 보낼 이벤트가 없으면 `: keepalive` 주석을 보낸다.
- 연결은 5분 뒤 서버가 닫는다. 클라이언트는 `retry`(3초) 뒤 `Last-Event-ID`를 붙여 다시 연결하고, 이때 토큰도 다시 검증된다.

| 상황 | 응답 |
| --- | --- |
| 토큰 없음·만료 | 401 `UNAUTHORIZED` |

- 현재 구현 범위: `stock.changed`, `review.created`, `review.progress`, `review.decided` 발행. 오래된 이벤트 정리 배치는 아직 없다.
- `stock.changed`는 재고가 바뀌는 모든 경로에서 부품마다 발행한다(`bjk_server.events.publish_stock_changed`): 채팅 확정·폼 입력, 원장 정정(LED-02), 실사 조정(AUD-03), 엑셀 이관 확정의 시작 재고·재이관 차이(SET-02), 부품 등록 초기 재고(SET-05), 중복 부품 병합(MAT-02, 대표 부품). `stock`은 병합 부품을 합산한 바뀐 뒤 재고다.
- 재고가 그대로인 경우(정정 차이 0, 실사 차이 0, 초기 재고 0, 재이관 `ignore`·`preview`)는 발행하지 않는다.
- `audit.flagged`는 이벤트 이름만 정의돼 있고 의심 항목을 만들 때 발행하지 않는다.
