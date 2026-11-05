"""부품 엑셀(xlsx, csv) 읽기 (F-SETUP-01).

첫 번째 비어 있지 않은 줄을 머리글로 보고 열 이름으로 항목을 찾는다.
줄 번호는 엑셀 화면의 줄 번호다. 필수 열(부품 이름·현재 재고·단위)이 없으면 파일 전체를
거절하고, 값이 잘못된 줄은 그 줄의 오류로 남긴다.
"""

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any

from openpyxl import load_workbook

from bjk_server.errors import ApiError, ErrorCode

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ROWS = 1000
NAME_MAX_LEN = 200
UNIT_MAX_LEN = 16
LOCATION_MAX_LEN = 100

# 항목 → 열 이름 후보 (공백을 뺀 뒤 비교)
COLUMNS: dict[str, tuple[str, ...]] = {
    "name": ("부품이름", "부품명", "품명", "이름"),
    "stock": ("현재재고", "재고", "재고수량"),
    "unit": ("단위",),
    "spec_text": ("규격",),
    "supplier": ("기본공급사", "공급사", "거래처"),
    "unit_price": ("단가", "기본단가"),
    "monthly_estimate": ("월사용추정치", "월사용량", "월사용"),
    "location": ("보관위치", "위치"),
}
REQUIRED = {"name": "부품 이름", "stock": "현재 재고", "unit": "단위"}


@dataclass
class ParsedRow:
    row: int
    name: str
    stock: int | None
    unit: str
    spec_text: str | None = None
    supplier: str | None = None
    unit_price: int | None = None
    monthly_estimate: int | None = None
    location: str | None = None
    errors: list[str] = field(default_factory=list)


def _key(header: Any) -> str:
    return re.sub(r"\s+", "", str(header or ""))


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    return text or None


def _int(value: Any) -> int | None:
    """정수 칸. 비면 None, 숫자가 아니면 ValueError. 쉼표·원 표기는 허용한다."""
    text = _text(value)
    if text is None:
        return None
    number = float(text.replace(",", "").removesuffix("원").strip())
    if not number.is_integer():
        raise ValueError(text)
    return int(number)


def _table(file_name: str, content: bytes) -> list[list[Any]]:
    if file_name.lower().endswith(".xlsx"):
        try:
            book = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        except Exception:  # openpyxl은 손상된 파일에 여러 종류의 예외를 낸다
            raise ApiError(ErrorCode.VALIDATION_ERROR, "엑셀 파일을 읽을 수 없습니다.") from None
        sheet = book.worksheets[0]
        return [list(r) for r in sheet.iter_rows(values_only=True)]
    if file_name.lower().endswith(".csv"):
        for encoding in ("utf-8-sig", "cp949"):
            try:
                return list(csv.reader(io.StringIO(content.decode(encoding))))
            except UnicodeDecodeError:
                continue
        raise ApiError(ErrorCode.VALIDATION_ERROR, "CSV 파일의 글자 인코딩을 읽을 수 없습니다.")
    raise ApiError(
        ErrorCode.VALIDATION_ERROR, "xlsx 또는 csv 파일만 올릴 수 있습니다.", {"file": file_name}
    )


def parse_parts_file(file_name: str, content: bytes) -> list[ParsedRow]:
    if len(content) > MAX_FILE_BYTES:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR, "파일은 5MB 이하여야 합니다.", {"bytes": len(content)}
        )
    table = _table(file_name, content)
    start = next((i for i, r in enumerate(table) if any(_text(c) for c in r)), None)
    if start is None:
        raise ApiError(ErrorCode.VALIDATION_ERROR, "파일에 내용이 없습니다.")
    headers = [_key(h) for h in table[start]]
    index: dict[str, int] = {}
    for item, names in COLUMNS.items():
        found = next((i for i, h in enumerate(headers) if h in names), None)
        if found is not None:
            index[item] = found
    missing = [label for item, label in REQUIRED.items() if item not in index]
    if missing:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR, "필수 열이 없습니다.", {"missing_columns": missing}
        )

    rows: list[ParsedRow] = []
    for offset, cells in enumerate(table[start + 1 :], start=start + 2):

        def cell(item: str, cells: list[Any] = cells) -> Any:
            i = index.get(item)
            return cells[i] if i is not None and i < len(cells) else None

        if not any(_text(c) for c in cells):
            continue
        if len(rows) == MAX_ROWS:
            raise ApiError(
                ErrorCode.VALIDATION_ERROR,
                f"한 번에 {MAX_ROWS}줄까지 올릴 수 있습니다.",
                {"max_rows": MAX_ROWS},
            )
        errors: list[str] = []
        name = (_text(cell("name")) or "")[:NAME_MAX_LEN]
        unit = (_text(cell("unit")) or "")[:UNIT_MAX_LEN]
        if not name:
            errors.append("name_required")
        if not unit:
            errors.append("unit_required")
        numbers: dict[str, int | None] = {}
        for item, code in (
            ("stock", "stock_invalid"),
            ("unit_price", "unit_price_invalid"),
            ("monthly_estimate", "monthly_estimate_invalid"),
        ):
            try:
                numbers[item] = _int(cell(item))
            except ValueError:
                numbers[item] = None
                errors.append(code)
            else:
                if numbers[item] is not None and numbers[item] < 0:
                    numbers[item] = None
                    errors.append(code)
        if numbers["stock"] is None and "stock_invalid" not in errors:
            errors.append("stock_required")
        location = _text(cell("location"))
        rows.append(
            ParsedRow(
                row=offset,
                name=name,
                stock=numbers["stock"],
                unit=unit,
                spec_text=(_text(cell("spec_text")) or None),
                supplier=_text(cell("supplier")),
                unit_price=numbers["unit_price"],
                monthly_estimate=numbers["monthly_estimate"],
                location=location[:LOCATION_MAX_LEN] if location else None,
                errors=errors,
            )
        )
    if not rows:
        raise ApiError(ErrorCode.VALIDATION_ERROR, "부품 줄이 없습니다.")
    return rows
