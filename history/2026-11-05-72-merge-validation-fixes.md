# main 배포 PR 검증: 병합 부품 합산·승인 409 반복·PDF 재현성 수정

- 날짜: 2026-11-05
- 영역: server
- 관련: #267, main 배포 PR #254, #264, #209, #164, #235, REV-05, REV-07, F-LEDGER-02·04, F-APPROVAL-04

## 목적

- main 배포 PR #254의 CI 실패와 레인 통합 버그 수정

## 한 일

- `inventory.py`: `with_merged_ids`(부품 + 병합된 부품 id), `merged_owners`(병합된 부품 → 대표 부품) 추가
- `jobs/nightly.py`: 재고·첫 기록·출고 이력·연간 사용량·납기 표본·열린 발주를 대표 부품으로 합산
- `audit/flags.py`: 장부 검증 원장과 정비 필요 부품을 대표 부품 기준으로 합산
- `api/dashboard.py`: 묶인 재고의 최근 출고 판단에 병합된 부품 출고 포함
- `purchasing/receipt.py`, `chat/intents/po_preview.py`, `chat/intents/incoming.py`: 병합된 부품의 열린 발주까지 대조. `reviews/snapshot.py`는 같은 함수로 교체
- `purchasing/decision.py`: 스냅샷을 새로 모은 뒤 미리 본 값(재검토 해시·대안 id)이 맞지 않으면 새 스냅샷·결과를 저장한 채 `SNAPSHOT_REFRESHED`
- `reviews/pdf.py`: PDF 바이트 고정은 #269의 글꼴 시각 고정(`_fix_font_timestamp`)으로 통합하고, 이 PR의 `SOURCE_DATE_EPOCH` 방식은 머지 시 제외. API 응답 바이트 테스트(`test_pdf_endpoint_bytes_do_not_depend_on_render_time`)는 유지
- 테스트 추가: `test_merged_part_ledger.py` 3개, `test_dashboard.py` 1개, `test_review_decision.py` 1개, `test_review_pdf.py` 1개

## 결정과 근거

- 병합은 원장·발주 행을 옮기지 않음(#209). 읽는 쪽이 대표 부품으로 합산하는 검토 스냅샷 방식(2026-11-05-58)에 맞춤
- 수정 전 증상: 병합 재고 800개가 있어도 nightly 재고 40(실제 840)·추천 500개, 대표 부품 출고로 `NEGATIVE_STOCK` 오탐, 흡수된 부품 발주는 입고 대조 `no_order`, 묶인 재고 14,000원 오집계
- 409 반복 원인: 새로 모은 스냅샷이 `ApiError`로 롤백되어 REV-04가 계속 이전 스냅샷 기준 해시를 돌려줌
- 판정이 같으면 계속 결정하는 기존 흐름 유지. 스냅샷 `computed_at`은 nightly 기준이라 다음 nightly 전까지 계속 갱신 대상이므로, 미리 본 값이 맞지 않을 때만 `Refreshed`로 돌려줌
- PDF 원인: harfbuzz-subset이 없는 환경(CI 러너, slim 이미지)에서 WeasyPrint가 fontTools로 글꼴을 줄이며 `head.modified`에 현재 시각 기록. CI 실패(길이 같고 6526번째 바이트 1개 차이)와 같은 증상을 fontTools 경로 강제로 재현
- 라이브러리 설치 대신 코드에서 고정. 실행 환경과 관계없이 같은 바이트
- 시드 납기 지터(#247)는 바꾸지 않음. 2026-11-05-70의 확인 필요 항목 유지

## 검증

- `ruff check .`, `ruff format --check .` 통과
- 전체 pytest(`REQUIRE_DB_TESTS=1`, pgvector pg16, Homebrew pango로 PDF 테스트 포함): 929개 통과
- 새 테스트 6개: 수정 전 실패, 수정 후 통과 확인
- PR #254 head(207f557) 원격 CI: 12개 실패(시드 11, PDF 1). 시드 11개는 dev #264로 해결, PDF 1개는 이 작업
- Linux에서 PDF 테스트: 미검증(로컬 이미지 받기 실패). CI에서 확인 필요

## 남은 일·확인 필요

- 결재용 PDF가 승인한 줄(원안·수정·대안) 대신 항상 수정안 기준으로 그림(`reviews/pdf.py`)
- missed-scan 즉시 검토가 작업 연결 외에 연결을 하나 더 씀. 스케줄러 풀(2개)이 차면 초안이 `reviewing`에 남음
- VAPID 키를 나중에 넣으면 `pushed_at` 없는 과거 알림 전체 발송(기간 제한 없음)
- 부품 상세 `incoming`·`ledger_status`·`last_counted_at` 고정값
- 엑셀 이관 부품 규격(문자열)과 기존 부품 규격(정수) 비교 불일치로 숨은 재고 미탐지
- 병합된 부품 원장 정정(LED-02) 404
- 만료 배치가 막 승인된 검토를 `expired`로 덮을 수 있음(행 잠금 없음)
- `stock.changed` 이벤트가 채팅 기록 경로에서만 발행
- 시연 시드 납기 지터로 V벨트 검토가 명세 예시 1과 다름(사용자 판단)
