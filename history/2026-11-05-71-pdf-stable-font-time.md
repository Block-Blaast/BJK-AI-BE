# 결재용 PDF 렌더링 시각 의존 수정

- 날짜: 2026-11-05
- 영역: server
- 관련: #266, #254, REV-07

## 목적

- main 배포 PR #254 CI의 `test_approved_review_pdf_is_stable` 실패 해소

## 한 일

- 원인 확인: server Docker 이미지(리눅스, Noto Sans CJK)에서 같은 HTML을 두 번 렌더링하면 부분 글꼴 `head` 테이블만 다름. WeasyPrint가 부분 글꼴을 fontTools로 저장할 때 `head.modified`를 현재 시각으로 기록
- `reviews/pdf.py`: 렌더링 전 fontTools `head` 시각을 고정(`FONT_TIMESTAMP`)
- 테스트 `test_review_pdf.py`에 렌더링 시각이 달라도 같은 바이트인지 확인 추가

## 결정과 근거

- `SOURCE_DATE_EPOCH` 환경 변수는 프로세스 전체(파이썬 바이트코드 등)에 영향을 줘서 쓰지 않고 fontTools `head` 시각만 고정
- 맥 로컬은 글꼴 경로가 달라 재현되지 않아 이전 테스트가 통과했음

## 검증

- server Docker 이미지에서 1.5초 간격 두 번 렌더링: 수정 전 다름, 수정 후 같음
- `test_review_pdf.py` 6개 통과(맥), `make lint` 통과. 전체 테스트는 지시에 따라 생략

## 남은 일·확인 필요

- #254 배포 브랜치에 이 수정과 #264 포함 필요
