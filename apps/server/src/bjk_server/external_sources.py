"""외부 지표·연휴 수집 (기능명세서 F-EXT-01, 새벽 배치 첫 단계).

- 환율 `USDKRW`: Frankfurter API(ECB 기준 환율, 키 없음). 일간 값을 주 단위로 묶는다.
- 해상운임 `FREIGHT`: 한국해양진흥공사 KCCI 시계열 페이지를 긁는다(주간, 월요일 발표).
- 연휴 `KR`·`CN`: Nager.Date 공휴일 API(키 없음). 이어지는 같은 이름의 날은 한 연휴로 묶고,
  중국 춘절·국경절은 공장이 쉬는 기간으로 넓힌다.

지표는 모두 그 주 월요일 날짜(`as_of`)로 맞춘다. 수집에 실패한 출처는 빠지고, 새벽 배치는 직전 값
(처음이면 시드 CSV)을 쓴다.
"""

import html
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal

import httpx

logger = logging.getLogger(__name__)

FRANKFURTER_URL = "https://api.frankfurter.dev/v1/{start}..{end}"
KCCI_URL = "https://www.kobc.or.kr/ebz/shippinginfo/timeseries/gridList.do?mId=0304000000"
NAGER_URL = "https://date.nager.at/api/v3/PublicHolidays/{year}/{country}"
USER_AGENT = "Mozilla/5.0 (compatible; baljukok-batch/1.0; +https://app.baljukok.kr)"
TIMEOUT_SECONDS = 15
# 위험도 z에 최근 13주 변화율과 그 이전 변화율 분포가 필요해 2년치를 받는다.
HISTORY_DAYS = 728

# KCCI 표 한 줄: 날짜 칸 다음 칸이 종합지수(KCCI)
_KCCI_ROW = re.compile(
    r"<td[^>]*>\s*(\d{4}-\d{2}-\d{2})\s*</td>\s*<td[^>]*>\s*([\d,.]+)\s*</td>", re.S
)
# 같은 이름의 공휴일 사이가 이 일수 이하면 한 연휴로 본다 (설날 사이에 낀 일요일 등)
MERGE_GAP_DAYS = 2
# 중국 공휴일 이름 → (한국어 이름, 첫날 기준 시작 오프셋, 연휴 일수). Nager는 첫날 하루만 준다.
CN_HOLIDAYS = {
    "春节": ("춘절", -1, 8),
    "国庆节": ("국경절", 0, 7),
    "劳动节": ("노동절", 0, 1),
    "中秋节": ("중추절", 0, 1),
    "端午节": ("단오절", 0, 1),
    "清明节": ("청명절", 0, 1),
    "元旦": ("원단", 0, 1),
}

Scope = Literal["KR", "CN"]


@dataclass(frozen=True)
class Holiday:
    name: str
    start: date
    end: date
    scope: Scope


@dataclass
class ExternalData:
    """한 번 수집한 결과. 실패한 지표는 `indicators`에 없고, 실패한 나라는 `holidays`에 없다."""

    indicators: dict[str, list[tuple[date, float]]] = field(default_factory=dict)
    holidays: dict[Scope, list[Holiday]] = field(default_factory=dict)


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _weekly(points: Iterable[tuple[date, float]]) -> list[tuple[date, float]]:
    """주마다 가장 이른 날의 값을 그 주 월요일 날짜로. 날짜순."""
    weeks: dict[date, tuple[date, float]] = {}
    for day, value in points:
        key = week_start(day)
        if key not in weeks or day < weeks[key][0]:
            weeks[key] = (day, value)
    return [(week, weeks[week][1]) for week in sorted(weeks)]


def parse_frankfurter(payload: dict[str, Any]) -> list[tuple[date, float]]:
    rates = payload.get("rates") or {}
    return _weekly((date.fromisoformat(d), float(r["KRW"])) for d, r in rates.items() if "KRW" in r)


def parse_kcci(page: str) -> list[tuple[date, float]]:
    return _weekly(
        (date.fromisoformat(d), float(v.replace(",", ""))) for d, v in _KCCI_ROW.findall(page)
    )


def parse_holidays(items: list[dict[str, Any]], scope: Scope) -> list[Holiday]:
    """Nager 응답을 연휴 단위로. KR은 이어지는 같은 이름을 묶고, CN은 쉬는 기간으로 넓힌다."""
    days = sorted((date.fromisoformat(i["date"]), html.unescape(i["localName"])) for i in items)
    holidays: list[Holiday] = []
    for day, name in days:
        if scope == "CN":
            ko, offset, length = CN_HOLIDAYS.get(name, (name, 0, 1))
            start = day + timedelta(days=offset)
            holidays.append(Holiday(ko, start, start + timedelta(days=length - 1), scope))
            continue
        last = holidays[-1] if holidays else None
        if last and last.name == name and (day - last.end).days <= MERGE_GAP_DAYS:
            holidays[-1] = Holiday(name, last.start, day, scope)
        else:
            holidays.append(Holiday(name, day, day, scope))
    return holidays


def fetch_usdkrw(client: httpx.Client, today: date) -> list[tuple[date, float]]:
    url = FRANKFURTER_URL.format(start=today - timedelta(days=HISTORY_DAYS), end=today)
    res = client.get(url, params={"from": "USD", "to": "KRW"})
    res.raise_for_status()
    return parse_frankfurter(res.json())


def fetch_kcci(client: httpx.Client, today: date) -> list[tuple[date, float]]:
    start = today - timedelta(days=HISTORY_DAYS)
    res = client.post(KCCI_URL, data={"sDay": start.isoformat(), "eDay": today.isoformat()})
    res.raise_for_status()
    return parse_kcci(res.text)


def fetch_holidays(client: httpx.Client, today: date, scope: Scope) -> list[Holiday]:
    holidays: list[Holiday] = []
    for year in (today.year, today.year + 1):
        res = client.get(NAGER_URL.format(year=year, country=scope))
        res.raise_for_status()
        holidays += parse_holidays(res.json(), scope)
    return holidays


def collect(today: date, client: httpx.Client | None = None) -> ExternalData:
    """출처별로 받아 온다. 한 출처가 실패해도 나머지는 그대로 쓴다."""
    own = client is None
    client = client or httpx.Client(
        timeout=TIMEOUT_SECONDS, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    )
    data = ExternalData()
    try:
        for code, fetch in (("USDKRW", fetch_usdkrw), ("FREIGHT", fetch_kcci)):
            try:
                if points := fetch(client, today):
                    data.indicators[code] = points
                else:
                    logger.warning("외부 지표 %s: 받은 값이 없습니다.", code)
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                logger.warning("외부 지표 %s 수집 실패: %s", code, exc)
        for scope in ("KR", "CN"):
            try:
                data.holidays[scope] = fetch_holidays(client, today, scope)
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                logger.warning("%s 공휴일 수집 실패: %s", scope, exc)
    finally:
        if own:
            client.close()
    return data
