"""의견서 검증 (F-REVIEW-08): 숫자, 판정 일치, 누락.

- 숫자: 의견서의 숫자를 뽑아 정규화(쉼표, 만·천, %, 날짜)하고 허용 목록(검토 입력값 + 파생값)과
  대조한다. 만·천 단위로 어림해 쓴 금액(예: "1만 5천 원")은 천 원 미만, 비율은 1%p 이하 차이를
  반올림 오차로 본다. 숫자로 정확히 쓴 금액(예: "15,000원")은 정확히 같아야 한다.
- 판정 일치: 첫 줄 머리가 실제 판정·표시와 같고, 다른 판정 표시가 섞이지 않았는지.
- 누락: 걸린 체크마다 근거 줄이 있고 그 체크를 가리키는 말이 있는지.

돌려주는 문자열은 그대로 재작성 요청(`OpinionRequest.feedback`)에 쓴다.
"""

import re
from datetime import date, datetime

from bjk_contracts import OpinionRequest
from bjk_contracts.opinion_format import CHECK_NAMES, SEOUL, VERDICT_NAMES, opinion_header

MONEY_TOLERANCE = 1000
PERCENT_TOLERANCE = 1.0
# 의견서가 기준을 설명할 때 쓰는 고정 비율(상위 95%·99%)
FIXED_PERCENTS = (95.0, 99.0)

# 걸린 체크를 언급했다고 볼 말. 체크 이름 또는 근거를 설명하는 낱말 하나 이상
CHECK_KEYWORDS = {
    "C-01": ("과다", "많습니다", "많아", "넉넉"),
    "C-02": ("개월", "장기", "쌓일", "오래"),
    "C-03": ("입고 예정", "중복", "다른 요청", "열린 발주"),
    "C-04": ("숨은 재고", "다른 이름", "실사", "같은 규격"),
    "C-05": ("단가", "비싸", "평균"),
    "C-06": ("공급사", "저렴", "더 싼"),
    "C-07": ("부족", "못 미", "모자", "필요량", "더 필요"),
    "C-08": ("마감", "긴급", "빠듯", "받기 어렵", "남았", "납기"),
    "C-09": ("환율", "운임", "연휴", "명절", "춘절", "외부", "위험", "리스크"),
}

_UNITS = {"억": 100_000_000, "만": 10_000, "천": 1_000}
_ISO_DATE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
_KO_DATE = re.compile(r"(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일")
_TIME = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)")
_KO_AMOUNT = re.compile(r"(?:\d[\d,]*(?:\.\d+)?\s*[억만천]\s*)+(?:\d[\d,]*)?")
_KO_AMOUNT_PART = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*([억만천])?")
_NUMBER = re.compile(r"(?<![\d.])(\d[\d,]*(?:\.\d+)?)(\s*%)?")
_CODE = re.compile(r"C-0\d")


def _to_float(raw: str) -> float:
    return float(raw.replace(",", ""))


def _parse_amount(raw: str) -> float:
    total = 0.0
    for number, unit in _KO_AMOUNT_PART.findall(raw):
        total += _to_float(number) * (_UNITS[unit] if unit else 1)
    return total


def _seoul(request: OpinionRequest) -> datetime:
    computed = request.computed_at
    return computed.astimezone(SEOUL) if computed.tzinfo is not None else computed


def _dates(value) -> list[date]:
    if isinstance(value, date):
        return [value]
    if isinstance(value, str):
        return [date(int(y), int(m), int(d)) for y, m, d in _ISO_DATE.findall(value)]
    return []


class Allowed:
    """의견서에 쓸 수 있는 숫자·날짜·시각."""

    def __init__(self, request: OpinionRequest) -> None:
        self.numbers: set[float] = set()
        self.percents: set[float] = set(FIXED_PERCENTS)
        self.dates: set[date] = set()
        self.names: list[str] = []
        self._collect(request)

    def _add(self, value) -> None:
        if isinstance(value, bool) or value is None:
            return
        if isinstance(value, int | float):
            self.numbers.add(float(value))
            self.numbers.add(abs(float(value)))
        else:
            self.dates.update(_dates(value))

    def _collect(self, r: OpinionRequest) -> None:
        for check in r.checks:
            for value in check.facts.values():
                self._add(value)
            if isinstance(check.facts.get("supplier"), str):
                self.names.append(check.facts["supplier"])
            if isinstance(check.facts.get("holiday"), str):
                self.names += [h.strip() for h in check.facts["holiday"].split(",")]
        lines = [r.original, *([r.proposal] if r.proposal else []), *r.alternatives]
        for line in lines:
            for value in (line.qty, line.unit_price, line.total):
                self._add(value)
            if line.supplier_name:
                self.names.append(line.supplier_name)
        if r.proposal:
            self._add(r.proposal.saving)
        for alternative in r.alternatives:
            self._add(alternative.saving)
        risk = r.risk_if_not_ordered
        self._add(risk.loss)
        if risk.stockout_date:
            self.dates.add(risk.stockout_date)
        self.names += risk.equipment
        self.names.append(r.part_name)

        self.dates.add(_seoul(r).date())
        self._derived(r)

    def _derived(self, r: OpinionRequest) -> None:
        """설명에 자연스럽게 나오는 파생값: 차액, 합계, 평균 대비 비율."""
        facts = {c.code: c.facts for c in r.checks}
        original_price = r.original.unit_price
        prices = [line.unit_price for line in [r.proposal, *r.alternatives] if line]
        for price in prices:
            if original_price is not None and price is not None:
                self._add(original_price - price)
        if r.proposal:
            self._add(r.original.qty - r.proposal.qty)
        for code in ("C-01", "C-07"):
            f = facts.get(code)
            if f:
                held = sum(f.get(k) or 0 for k in ("S", "O", "H_c", "P"))
                self._add(held)
                self._add(held + (f.get("Q") or 0))
        if c04 := facts.get("C-04"):
            self._add((c04.get("H_c") or 0) + (c04.get("H_u") or 0))
        if (c05 := facts.get("C-05")) and c05.get("p_mean"):
            price, mean = c05["unit_price"], c05["p_mean"]
            self._add(price - mean)
            self.percents.add(round((price / mean - 1) * 100))

    def number_ok(self, value: float, *, approximate: bool, decimals: int) -> bool:
        for allowed in self.numbers:
            if approximate and abs(value - allowed) < MONEY_TOLERANCE:
                return True
            if round(allowed, decimals) == value:
                return True
        return False

    def percent_ok(self, value: float) -> bool:
        return any(abs(value - p) <= PERCENT_TOLERANCE for p in self.percents)

    def date_ok(self, month: int, day: int, year: int | None) -> bool:
        return any(
            d.month == month and d.day == day and (year is None or d.year == year)
            for d in self.dates
        )


def _strip_names(text: str, names: list[str]) -> str:
    # 부품명·공급사명·설비명 속 숫자(6205ZZ, 3호기)는 검증 대상이 아니다. 긴 이름부터 지운다.
    for name in sorted({n for n in names if n}, key=len, reverse=True):
        text = text.replace(name, " ")
    return _CODE.sub(" ", text)


def check_numbers(text: str, request: OpinionRequest) -> list[str]:
    allowed = Allowed(request)
    errors: list[str] = []
    body = _strip_names(text, allowed.names)

    def blank(match: re.Match) -> str:
        return " " * len(match.group(0))

    for match in _ISO_DATE.finditer(body):
        y, m, d = (int(g) for g in match.groups())
        if not allowed.date_ok(m, d, y):
            errors.append(f"허용 목록에 없는 날짜: {match.group(0)}")
    body = _ISO_DATE.sub(blank, body)
    for match in _KO_DATE.finditer(body):
        y, m, d = match.groups()
        if not allowed.date_ok(int(m), int(d), int(y) if y else None):
            errors.append(f"허용 목록에 없는 날짜: {match.group(0)}")
    body = _KO_DATE.sub(blank, body)

    footer_time = f"{_seoul(request):%H:%M}"
    for match in _TIME.finditer(body):
        if match.group(0) != footer_time and match.group(0).zfill(5) != footer_time:
            errors.append(f"허용 목록에 없는 시각: {match.group(0)}")
    body = _TIME.sub(blank, body)

    for match in _KO_AMOUNT.finditer(body):
        value = _parse_amount(match.group(0))
        if not allowed.number_ok(value, approximate=True, decimals=0):
            errors.append(f"허용 목록에 없는 숫자: {match.group(0).strip()}({value:,.0f})")
    body = _KO_AMOUNT.sub(blank, body)

    for match in _NUMBER.finditer(body):
        raw, percent = match.groups()
        value = _to_float(raw)
        if percent:
            if not allowed.percent_ok(value):
                errors.append(f"허용 목록에 없는 비율: {raw}%")
            continue
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        # 실제 평균 15,500원을 "15,000원"으로 쓴 경우를 잡으려고 숫자 표기는 오차를 두지 않는다
        if not allowed.number_ok(value, approximate=False, decimals=decimals):
            errors.append(f"허용 목록에 없는 숫자: {raw}")
    return errors


def check_verdict(text: str, request: OpinionRequest) -> list[str]:
    expected = opinion_header(request)
    errors = []
    if text.startswith(expected + " "):
        rest = text[len(expected) :]
    else:
        errors.append(f"첫 줄 판정 표시가 {expected}와 다름")
        rest = text.partition("\n")[2]
    for name in VERDICT_NAMES.values():
        if f"[{name}" in rest:
            errors.append(f"본문에 판정 표시 [{name}]가 섞임")
    return errors


def check_missing(text: str, request: OpinionRequest) -> list[str]:
    bullets = [line for line in text.splitlines() if line.startswith("- ")]
    errors = []
    if len(bullets) != len(request.checks):
        errors.append(f"체크 근거 줄이 {len(request.checks)}개여야 하는데 {len(bullets)}개")
    for check in request.checks:
        words = (CHECK_NAMES[check.code], *CHECK_KEYWORDS[check.code])
        if not any(word in text for word in words):
            errors.append(f"{check.code}({CHECK_NAMES[check.code]}) 언급 없음")
    return errors


def verify_opinion(text: str, request: OpinionRequest) -> list[str]:
    """틀린 항목 목록. 비어 있으면 통과."""
    return [
        *check_verdict(text, request),
        *check_missing(text, request),
        *check_numbers(text, request),
    ]
