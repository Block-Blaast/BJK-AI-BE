from datetime import date

import httpx
from bjk_server.external_sources import (
    Holiday,
    collect,
    parse_frankfurter,
    parse_holidays,
    parse_kcci,
)

TODAY = date(2026, 11, 5)

# KCCI 시계열 표 일부. 2026-10-06(화)은 월요일 휴일로 하루 늦게 발표된 주.
KCCI_PAGE = """
<table><thead><tr><th>Date</th><th>KCCI</th><th>Mainlane</th></tr></thead><tbody>
<tr><td>2026-11-02</td><td>4,667</td><td>8,247</td></tr>
<tr><td>2026-10-26</td><td> 4,666 </td><td>8,267</td></tr>
<tr><td>2026-10-06</td><td>4,512</td><td>8,001</td></tr>
</tbody></table>
"""

FRANKFURTER = {
    "base": "USD",
    "rates": {
        "2026-10-27": {"KRW": 1327.75},
        "2026-10-28": {"KRW": 1340.47},
        "2026-11-03": {"KRW": 1344.59},
        "2026-11-04": {"KRW": 1338.58},
    },
}


def _nager(days):
    return [{"date": d, "localName": name, "name": "x"} for d, name in days]


def test_frankfurter_takes_first_day_of_each_week_as_monday():
    assert parse_frankfurter(FRANKFURTER) == [
        (date(2026, 10, 26), 1327.75),
        (date(2026, 11, 2), 1344.59),
    ]


def test_kcci_reads_composite_column_by_week():
    assert parse_kcci(KCCI_PAGE) == [
        (date(2026, 10, 5), 4512.0),
        (date(2026, 10, 26), 4666.0),
        (date(2026, 11, 2), 4667.0),
    ]


def test_kr_holidays_merge_same_name_across_weekend():
    items = _nager(
        [
            ("2027-02-06", "설날"),
            ("2027-02-08", "설날"),
            ("2027-02-09", "설날"),
            ("2027-03-01", "3·1절"),
            ("2027-09-14", "추석"),
            ("2027-09-15", "추석"),
            ("2027-09-16", "추석"),
        ]
    )
    assert parse_holidays(items, "KR") == [
        Holiday("설날", date(2027, 2, 6), date(2027, 2, 9), "KR"),
        Holiday("3·1절", date(2027, 3, 1), date(2027, 3, 1), "KR"),
        Holiday("추석", date(2027, 9, 14), date(2027, 9, 16), "KR"),
    ]


def test_cn_holidays_widen_to_factory_closure():
    items = _nager([("2027-02-06", "春节"), ("2027-10-01", "国庆节"), ("2027-06-09", "端午节")])
    assert parse_holidays(items, "CN") == [
        Holiday("춘절", date(2027, 2, 5), date(2027, 2, 12), "CN"),
        Holiday("단오절", date(2027, 6, 9), date(2027, 6, 9), "CN"),
        Holiday("국경절", date(2027, 10, 1), date(2027, 10, 7), "CN"),
    ]


def _transport(kcci_status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host == "api.frankfurter.dev":
            return httpx.Response(200, json=FRANKFURTER)
        if host == "www.kobc.or.kr":
            assert request.method == "POST"
            assert b"sDay=2024-11-07" in request.content
            return httpx.Response(kcci_status, text=KCCI_PAGE)
        if host == "date.nager.at":
            country = request.url.path.rsplit("/", 1)[-1]
            year = request.url.path.split("/")[-2]
            name = "설날" if country == "KR" else "春节"
            return httpx.Response(200, json=_nager([(f"{year}-02-06", name)]))
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_collect_gathers_every_source():
    data = collect(TODAY, _transport())
    assert set(data.indicators) == {"USDKRW", "FREIGHT"}
    assert data.indicators["FREIGHT"][-1] == (date(2026, 11, 2), 4667.0)
    assert [h.start.year for h in data.holidays["KR"]] == [2026, 2027]
    assert data.holidays["CN"][0].name == "춘절"


def test_collect_skips_only_the_failing_source():
    data = collect(TODAY, _transport(kcci_status=503))
    assert set(data.indicators) == {"USDKRW"}
    assert set(data.holidays) == {"KR", "CN"}
