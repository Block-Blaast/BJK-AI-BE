# 외부 지표·공휴일 실제 수집

- 날짜: 2026-11-05
- 영역: server (새벽 배치)
- 관련: F-EXT-01, F-EXT-02, DSH-03, jobs nightly

## 목적

- 명세는 새벽 배치 첫 단계를 "외부 지표 수집"으로 두지만, 환율·해상운임은 시연용 CSV를 다시 읽기만 했고 연휴는 사람이 직접 넣어야 했다.
- API가 있는 것(환율·공휴일)은 API로, API가 없는 해상운임은 주기적으로 수집해 갱신한다(사용자 결정).

## 한 일

- `apps/server/src/bjk_server/external_sources.py` 추가
  - 환율 `USDKRW`: Frankfurter API(ECB 기준 환율, 키 없음) 2년치, 주마다 가장 이른 날 값을 그 주 월요일 날짜로
  - 해상운임 `FREIGHT`: 한국해양진흥공사 KCCI 시계열 페이지(`timeseries/gridList.do`, `sDay`·`eDay` POST)에서 종합지수 열 수집
  - 공휴일 `KR`·`CN`: Nager.Date API로 올해·내년. 국내는 이어지는 같은 이름(사이 2일 이하)을 한 연휴로, 중국 춘절은 전날부터 8일·국경절 7일로 넓힘
  - 출처별로 실패를 잡아 나머지 출처는 그대로 쓴다
- `jobs/nightly.py`
  - `load_indicators`: 받은 지표는 통째로 교체(시드 CSV와 섞이지 않게), 실패한 지표는 직전 값 유지, 값이 없을 때만 시드 CSV
  - 위험도를 DB에 쌓인 지표 전체로 날짜순 재계산
  - `sync_holidays`: 회사 연휴 캘린더에 추가. 같은 범위에 겹치는 일정이 있거나 지난 연휴는 건너뜀
  - 요약에 `external_fetched`(받은 출처), `holidays_added` 추가
- `config.py` `EXTERNAL_FETCH`(기본 `true`), 테스트는 `conftest.py` autouse로 끔
- 문서: `docs/api-spec/jobs.md`, `docs/api-spec/external.md`, `.env.example`

## 결정과 근거

- 환율은 한국은행 ECOS 대신 Frankfurter: 키가 필요 없어 배포 비밀 값이 늘지 않는다. 위험도는 변화율 기준이라 ECB 기준 환율로 충분하다.
- 해상운임은 SCFI(상하이) 대신 KCCI: 국내 공공기관 지표이고 robots.txt가 수집을 막지 않는다. SCFI 페이지는 무단 전재·상업 이용 금지 문구가 있다.
- 받은 지표를 통째로 바꾸는 이유: 시드 CSV(1,700대)와 KCCI(4,600대)는 단위가 달라 섞이면 변화율 분포가 망가진다. 매번 2년치를 받으므로 이력이 짧아지지 않는다.
- 공휴일은 기존 일정과 겹치면 넣지 않는다: 직접 등록한 공장 휴무(예: 9일짜리 춘절)를 덮지 않는다.

## 검증

- `pytest apps/server/tests/test_external_sources.py`: 파서·수집 6건 통과 (가짜 HTTP)
- `pytest test_external_collect.py test_nightly.py test_health.py test_external_status.py test_holiday_lead_time.py test_external_shock.py`: 34건 통과 (로컬 PostgreSQL)
- 실제 수집: `collect(2026-11-05)` 10.3초, USDKRW 105주(최신 2026-11-02 1,342.9), FREIGHT 97주(최신 4,667), KR 27건, CN 12건
- 로컬 DB `make seed` 후 `EXTERNAL_FETCH=true make job name=nightly`: `external_fetched` 4개 출처, `holidays_added` 18, 시드 설날·춘절은 건너뜀
- 실제 값 위험도: FREIGHT r 0.30, USDKRW r 0 (둘 다 `normal`)

## 남은 일·확인 필요

- 대회 서버(BJK-Cloud `deploy/compose.yaml`)의 scheduler는 `data` 네트워크(internal)에만 있어 외부로 나갈 수 없다. 수집하려면 scheduler에 외부로 나가는 네트워크(예: `app`)를 붙여야 한다. 인프라 담당 확인 필요.
- 실제 데이터에서는 운임 위험도가 `normal`이라, 시드 CSV 기준으로 "운임 주의 → 납기 연장"을 보여 주던 시연 흐름은 외부 충격 스위치(DEV-02)로 보여 줘야 한다.
- KCCI 페이지 구조가 바뀌면 수집이 실패한다(직전 값 유지). 실패는 경고 로그와 요약의 `external_fetched`로 확인한다.
