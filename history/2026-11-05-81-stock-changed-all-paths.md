# 재고가 바뀌는 모든 경로에 stock.changed 발행

- 날짜: 2026-11-05
- 영역: server(NOT-03 실시간 이벤트)
- 관련: #295, NOT-03, LED-02, AUD-03, SET-02, SET-05, MAT-02

## 목적

- 채팅 확정·폼 입력 외 경로(정정, 실사 조정, 엑셀 이관 확정, 부품 등록 초기 재고, 부품 병합)는 재고가 바뀌어도 `stock.changed`를 보내지 않아, 다른 기기에 열린 화면이 SSE로 재고 변화를 받을 수 없었음

## 한 일

- `bjk_server/events.py`에 `publish_stock_changed` 추가: flush 뒤 병합 합산 재고를 구해 같은 트랜잭션에 이벤트 저장, 재고 반환
- 채팅 기록(`chat/records.py`), 원장 정정(`api/ledger.py`), 실사 조정(`audit/counts.py`), 부품 등록(`api/parts.py`), 이관 확정(`imports/service.py` `_adjust`), 병합(`api/merge_candidates.py` 대표 부품)에서 호출
- 테스트: `conftest.watch_stock_events`로 저장된 이벤트 확인. 정정·실사·등록·이관(시작 재고, 재이관 apply)·병합 발행과, 차이 0·초기 재고 0 미발행
- 명세 `docs/api-spec/events.md` 발행 경로 갱신

## 결정과 근거

- 이벤트 데이터는 기존 계약 그대로 `part_id`, `stock`. 프론트는 받으면 다시 조회하므로 경로 구분 필드를 늘리지 않음
- 병합은 원장 추가는 없지만 대표 부품 재고가 바뀌므로 대표 부품으로 발행. 흡수된 부품은 목록에서 사라져 따로 보내지 않음

## 검증

- `REQUIRE_DB_TESTS=1 uv run pytest` 관련 6개 파일(정정·실사 응답·부품 등록·병합·이관·이벤트) 49개 통과(로컬 PostgreSQL)
- 전체 `REQUIRE_DB_TESTS=1 uv run pytest` 966개 통과·1개 건너뜀, `make lint` 통과

## 남은 일·확인 필요

- 프론트(BJKFE)는 아직 SSE를 구독하지 않아 이 변경만으로 다른 기기 화면이 바로 바뀌지는 않음
- `audit.flagged` 미발행은 그대로
