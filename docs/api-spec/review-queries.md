# 발주 검토 조회 (REV-01·02)

API 명세서 REV 기준. 검토 실행·저장은 [reviews.md](reviews.md)(#146)를 따르고, 이 문서는 조회만 다룬다.

## 권한

- manager 이상: 회사 전체 검토.
- worker: 본인이 올린 요청(`requested_by`)만. 다른 사람 검토와 시스템 초안은 404 `NOT_FOUND`.

## REV-02 `GET /reviews/{id}`

- `requested_by`: `{"type":"user","id","name"}`, 시스템 초안(`stock_draft`·`missed_draft`)은 `null`.
- `checks`, `original`, `proposal`, `alternatives`, `risk_if_not_ordered`, `count_requests`: 저장된 검토 결과. 공급사는 `{id, name}`, 수정안 공급사가 없으면 `null`.
- `hold_reasons`: 보류 사유. 보류가 아니면 빈 배열.
- `part`: 부품 이름(명세 예시에 없어 추가).
- `snapshot`: 가장 최근 스냅샷의 `id`, `hash`, `values`. `values`는 저장한 스냅샷에서 뽑은 명세 키 `Q, S, O, H_c, H_u, P, m, F, D95, D99, R, MOQ, p_mean`. R = max(0, D95 − S − O − H_c), MOQ는 기본 공급사 값.
- `computed_at`: 스냅샷 근거 계산 시각. `reviewing` 상태는 결과·의견서·스냅샷이 `null`(또는 빈 배열).

## REV-01 `GET /reviews`

- 쿼리: `status`(`reviewing`·`reviewed`·`held`·`approved`·`closed`·`expired`), `verdict`(`ok`·`revise`·`hold`), `urgent`(`true`·`false`), `entry`(`staff_request`·`stock_draft`·`missed_draft`), `mine`(`true`면 본인 요청만), `cursor`, `limit`. 허용 값 밖이면 400 `VALIDATION_ERROR`.
- 정렬: 긴급(`flags`에 `urgent`) 먼저, 그다음 미발주 예상 손실(`risk_if_not_ordered.loss`) 큰 순, 최근 생성 순, ID 순. 커서는 이 네 값.
- 항목: `{"id","entry","part","status","verdict","flags","original_total","saving","created_at"}`. `part`는 부품 이름 문자열.
