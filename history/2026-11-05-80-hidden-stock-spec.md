# 숨은 재고 같은 규격 판정 오류 수정

- 날짜: 2026-11-05
- 영역: server·검토(숨은 재고 H_c·H_u)
- 관련: #289, F-MATCH-01·03, F-REVIEW-02(H_c·H_u), C-04, 3D 창고 `same_spec_group`

## 목적

- 배포된 3D 창고 화면에서 숨은 재고 5묶음 중 4묶음이 다른 품목(육각너트 M10 ↔ 평와셔 M10, 유압유 ↔ 기어오일 20L)이었음
- 정본 예시 ③(육각볼트 M8-20 ↔ 헥사볼트 M8x20 800개)은 반대로 묶이지 않았음
- 같은 판정을 검토 스냅샷과 새벽 배치가 써서 C-04와 권장량 R까지 틀어질 수 있었음

## 한 일

- `domain/matching.py`: 규격 비교 키 `spec_key`(값 표기 통일)와 같은 규격 판정 `same_spec_key` 추가, 규격 추출에 점도 등급 `iso_vg`와 품목 종류 `kind`(볼트·너트·와셔, 오일 종류) 추가
- `domain/hidden_stock.py` `same_spec`, `domain/merge.py` `find_duplicates`: `same_spec_key`로 통일
- `api/twin.py` `same_spec_group`: 정규화한 `spec_key`로 묶음 키 생성
- `seed/demo.py`: v1 육각볼트 M8-20·수용성 절삭유 20L 규격에 `kind` 추가
- 테스트: `test_matching.py` 추출 사례 6개, `test_domain_hidden_stock.py` 표기 통일·다른 품목·동의어 사례

## 결정과 근거

- 원인 1: v1 시드는 `{"length_mm": 20}`(숫자), v2 시드·정규식은 `"20"`(문자열)이라 `spec == other_spec`이 거짓. 병합 후보(`domain.merge`)는 이미 값을 통일해 비교하고 있어 같은 키로 맞춤
- 원인 2: 정규식이 치수(M10, 20L)만 뽑아 품목이 달라도 규격이 같았음. F-MATCH-01 3단계 "카테고리별 정규식으로 추출한 규격"에 종류·등급을 더함
- 종류는 두 부품 모두에 있을 때만 비교. 직접 등록(PART API)한 규격에는 종류가 없을 수 있어서, 엄격 비교면 진짜 같은 부품을 놓침(`test_merge_candidates`의 직접 등록 헥사볼트가 그 경우)
- 3D 묶음 키는 종류까지 포함한 엄격 키. 시연 데이터는 모두 종류가 있어 검토 판정과 결과가 같음
- 동의어(육각볼트·헥사볼트, V벨트·전동벨트)는 같은 값이거나 종류를 뽑지 않아 계속 같은 규격. 그냥 "와셔"처럼 종류가 불분명한 표현은 비워 매칭에서 후보를 좁히지 않음
- 매칭 영향: 질의에 종류가 있으면 다른 종류 부품은 규격 충돌로 빠짐("M10 너트"에 평와셔가 안 나옴). 의도한 동작

## 검증

- demo_v1+v2 부품 106개로 묶음 확인: V벨트 B-50 ↔ 전동벨트 B-50, 헥사볼트 M8x20 ↔ 육각볼트 M8-20 두 묶음만 남음
- `uv run pytest apps/server/tests/test_matching.py tests/test_domain_hidden_stock.py tests/test_merge_detection.py`: 44 통과(DB 3 건너뜀)
- `REQUIRE_DB_TESTS=1 uv run pytest apps/server packages`: 914 통과, 엑셀 이관 기대 규격 5건 실패 → 기대값에 `kind` 반영 후 해당 파일·병합·3D 테스트 26 통과

## 남은 일·확인 필요

- 배포 DB의 기존 부품 `spec`에는 `kind`·`iso_vg`가 없음. 시연 서버는 `make seed`(demo_v2)를 다시 돌려야 반영됨
- 실사용 회사의 기존 부품은 규격을 다시 추출하는 마이그레이션이 없음(해커톤 범위 밖)
- 프론트: 숨은 재고 묶음 제목에 키(`카테고리ID:{...}`)를 그대로 보여 줌. 부품 이름으로 표시 필요
