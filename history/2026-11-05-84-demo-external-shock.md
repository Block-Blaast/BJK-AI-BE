# 운영 시연용 외부 충격 스위치와 검토 목록 부품 id

- 날짜: 2026-11-05
- 영역: server(시연 API, REV-01)
- 관련: #303, F-EXT-03, DEV-02, REV-01, W-11

## 목적

- 외부 충격 스위치(DEV-02)가 개발 모드에서만 열려 운영 시연에서 환율·해상운임 위험(3D 외부 요인 알림, C-09)을 보여 줄 수 없었음
- 3D 외부 요인 알림의 "결정 대기 N건"이 검토 목록에 부품 id가 없어 나오지 않았음

## 한 일

- `api/scenarios.py`: 사장님 전용 `GET /api/v1/scenarios`, `POST /api/v1/scenarios/external-shock`. 처리 함수 `switch_external_shock`을 DEV-02와 공유
- REV-01 항목에 `part_id` 추가
- 명세 `docs/api-spec/dev.md`·`review-queries.md` 갱신, 테스트 `test_scenarios.py` 4개와 목록 테스트 갱신

## 결정과 근거

- 사용자 결정(2026-11-05): 운영 시연에서 외부 충격을 켤 수 있게 함
- 사장님만 켤 수 있음. 회사 전체 근거 지표를 다시 계산하는 쓰기 작업이라서
- 끝난 검토는 다시 돌리지 않음. 결정의 근거 스냅샷을 바꾸지 않기 위해

## 검증

- `test_scenarios.py` 4개 포함 전체 `REQUIRE_DB_TESTS=1 uv run pytest` 971개 통과·1개 건너뜀(로컬 PostgreSQL)

## 남은 일·확인 필요

- 운영 배포 후 프론트(설정 화면 스위치, 3D 알림 결정 대기 링크)와 함께 확인
