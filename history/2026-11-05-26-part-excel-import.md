# 부품 엑셀 이관과 AI 규격·카테고리 제안

- 날짜: 2026-11-05
- 영역: server
- 관련: #190, F-SETUP-01·02, SET-01·02

## 목적

- 부품 엑셀 이관(SET-01·02)을 ai `/v1/imports/suggest`로 구현하고 ai 실패 시 대체 경로 확보

## 한 일

- `part_imports` 테이블·RLS(마이그레이션 0021), `PartImport` 모델
- `imports/parse.py`: xlsx·csv 읽기, 열 이름 후보, 줄 오류 코드
- `imports/service.py`: 제안 목록(정규식 + ai 규격 병합, 카테고리 제안, 기존 부품, 중복 의심), 확정(`stock_mode` 4종, 별칭, 공급사 단가, 임베딩)
- `api/imports.py` 라우터, `ai/client.py`에 `suggest_import` 추가(기존 메서드는 그대로)
- 의존성 `openpyxl`, `python-multipart` 추가
- `docs/api-spec/imports.md`

## 결정과 근거

- ai 실패·대체 응답·미설정이면 규격은 정규식, `suggested_category: null` (F-SETUP-02 3번, `docs/ai-integration.md` 4장)
- 묶음 하나라도 실패하면 전체를 대체 경로로 둔다. 줄마다 출처가 섞이지 않게 하기 위해서
- 재이관 판정은 확정한 이관이 있는지로 정함. 줄의 기존 부품은 부품명(정규화) + 규격으로 찾음 (F-SETUP-01)
- 새 부품은 모드와 관계없이 파일 재고를 시작 재고로 넣음. 원장이 없어 덮을 기록이 없기 때문
- 첫 이관(`initial`)에서도 기존 부품 재고는 건드리지 않음. 원장 이력을 덮지 않는다는 F-SETUP-01 원칙
- 등록되지 않은 공급사는 새로 만들지 않고 `warnings: supplier_unknown`로 알림 (명세에 없는 필드, 추가만 함)

## 검증

- `tests/test_part_imports.py` 14개: ai 정상, 시간 초과·연결 실패·대체 응답·미설정, 첫 이관, 재이관 preview·apply·ignore, 줄 오류, xlsx, 잘못된 파일, 권한
- `REQUIRE_DB_TESTS=1 make test` 588개 통과, `make lint` 통과
- 실제 ai 서비스(Bedrock) 호출은 미검증

## 남은 일·확인 필요

- 마이그레이션은 dev의 0020(#68) 다음 0021로 확정. A의 #137(0020~0022)이 나중에 머지하면 번호 조정 필요
- `warnings` 필드와 재이관 판정 기준을 Notion API 명세서에 반영할지 확인 필요
