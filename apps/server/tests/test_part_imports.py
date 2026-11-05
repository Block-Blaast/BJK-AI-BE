"""부품 엑셀 이관 SET-01·02 (F-SETUP-01·02). ai 제안과 ai 실패 시 대체 경로."""

import io
import json

import httpx
import pytest
from bjk_contracts import (
    AiMeta,
    EmbedResponse,
    FallbackReason,
    ImportSuggestResponse,
    LlmPurpose,
    RowSuggestion,
)
from bjk_server.ai.client import AiClient, get_ai_client
from bjk_server.db.models import LlmCall, Movement, Part, PartAlias, SupplierPart
from bjk_server.seed.demo import demo_id
from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .ai_fakes import usage
from .conftest import auth_header

URL = "/api/v1/imports/parts"
BEARING = str(demo_id("category", "bearing"))
BOLT = str(demo_id("category", "bolt"))
P6205 = demo_id("part", "6205")

CSV = (
    "부품 이름,현재 재고,단위,규격,기본 공급사,단가,보관 위치\n"
    '볼베어링 6305ZZ,4,개,,공급사 A,"21,000",B선반 1칸\n'
    "육각볼트 M10-30,200,개,M10x30,,,\n"
    "베어링 6205 ZZ,5,개,,,,\n"
)


class SuggestAi:
    """`/v1/imports/suggest`만 흉내 낸다. `fail`이 예외면 던지고, "fallback"이면 대체 응답."""

    def __init__(self, fail: Exception | str | None = None) -> None:
        self.fail = fail
        self.requests: list[dict] = []

    def client(self) -> AiClient:
        return AiClient(httpx.Client(base_url="http://ai", transport=httpx.MockTransport(self._h)))

    def _h(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if request.url.path == "/v1/embeddings":
            # 확정 때 새 부품 임베딩. 비워 두면 nightly가 채운다.
            response = EmbedResponse(
                model=None, vectors=None, ai=AiMeta.failed(FallbackReason.TIMEOUT), usage=None
            )
            return httpx.Response(200, json=response.model_dump(mode="json"))
        self.requests.append(body)
        if isinstance(self.fail, Exception):
            raise self.fail
        if self.fail == "fallback":
            response = ImportSuggestResponse(
                suggestions=None,
                ai=AiMeta.failed(FallbackReason.QUOTA_EXCEEDED),
                usage=usage(LlmPurpose.IMPORT_SUGGEST, False),
            )
        else:
            response = ImportSuggestResponse(
                suggestions=[_suggest(r) for r in body["rows"]],
                ai=AiMeta.ok(),
                usage=usage(LlmPurpose.IMPORT_SUGGEST),
            )
        return httpx.Response(200, json=response.model_dump(mode="json"))


def _suggest(row: dict) -> RowSuggestion:
    if "볼트" in row["name"]:
        # 정규식은 M10·30을 찾는다. ai가 길이를 다르게 주면 정규식 값이 이기고 확신도가 낮아진다.
        return RowSuggestion(
            row=row["row"],
            spec={"thread": "M10", "length_mm": "35"},
            category_id=BOLT,
            confidence=0.9,
        )
    return RowSuggestion(
        row=row["row"], spec={"shield": "ZZ"}, category_id=BEARING, confidence=0.95
    )


@pytest.fixture
def fresh(demo_db):
    demo_db.reseed()


def _use_ai(client, fake: SuggestAi | None):
    client.app.dependency_overrides[get_ai_client] = fake.client if fake else lambda: None


def _upload(client, content: bytes | str = CSV, name="parts.csv", user="manager"):
    data = content.encode() if isinstance(content, str) else content
    return client.post(URL, files={"file": (name, data)}, headers=auth_header(user))


def _confirm(client, import_id, rows, stock_mode=None):
    body = {"rows": rows} | ({"stock_mode": stock_mode} if stock_mode else {})
    return client.post(f"{URL}/{import_id}/confirm", json=body, headers=auth_header("manager"))


def _rows(res) -> dict[int, dict]:
    return {r["row"]: r for r in res.json()["rows"]}


def test_upload_with_ai_suggestions_sorted_by_confidence(client, demo_db, fresh):
    fake = SuggestAi()
    _use_ai(client, fake)
    res = _upload(client)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ai"] == {"used": True, "fallback": False, "reason": None}
    assert body["is_reimport"] is False
    assert [r["row"] for r in body["rows"]] == [3, 2, 4]  # 확신도 0.45 → 0.95 → 0.95
    rows = _rows(res)
    assert rows[3]["spec"] == {"thread": "M10", "length_mm": "30"}
    assert rows[3]["suggested_category"]["confidence"] == 0.45
    assert rows[2]["spec"] == {"bearing_no": "6305", "shield": "ZZ"}
    assert rows[2]["suggested_category"] == {"id": BEARING, "name": "베어링", "confidence": 0.95}
    # 이름이 달라 기존 부품은 아니고, 규격이 같아 중복 의심으로 보여준다 (F-SETUP-02 4번)
    assert rows[4]["existing_part_id"] is None
    assert {"part_id": str(P6205), "name": "볼베어링 6205ZZ", "reason": "spec_exact"} in rows[4][
        "duplicate_suspects"
    ]
    assert {c["name"] for c in fake.requests[0]["categories"]} >= {"베어링", "볼트·너트"}
    with Session(demo_db.admin) as s:
        assert s.scalar(select(func.count()).where(LlmCall.purpose == "import_suggest")) == 1


@pytest.mark.parametrize(
    ("fake", "reason", "used"),
    [
        (SuggestAi(httpx.ReadTimeout("slow")), "timeout", True),
        (SuggestAi(httpx.ConnectError("down")), "error", True),
        (SuggestAi("fallback"), "quota_exceeded", True),
        (None, "error", False),
    ],
)
def test_ai_failure_falls_back_to_regex_and_manual_category(client, fresh, fake, reason, used):
    _use_ai(client, fake)
    res = _upload(client)
    assert res.status_code == 200, res.text
    assert res.json()["ai"] == {"used": used, "fallback": True, "reason": reason}
    rows = _rows(res)
    assert all(r["suggested_category"] is None for r in rows.values())
    assert rows[2]["spec"] == {"bearing_no": "6305", "shield": "ZZ"}
    assert rows[3]["spec"] == {"thread": "M10", "length_mm": "30"}


def test_first_import_creates_parts_with_initial_stock(client, demo_db, fresh):
    _use_ai(client, SuggestAi())
    res = _upload(client)
    import_id = res.json()["import_id"]
    rows = [
        {"row": 2},
        {"row": 3, "category_id": BOLT},
        {"row": 4, "merge_with_part_id": str(P6205)},
    ]
    done = _confirm(client, import_id, rows)
    assert done.status_code == 200, done.text
    assert done.json() == {"created": 2, "updated": 1, "adjust_movements": 2, "stock_diffs": []}
    with Session(demo_db.admin) as s:
        bearing = s.scalar(select(Part).where(Part.name == "볼베어링 6305ZZ"))
        assert str(bearing.category_id) == BEARING
        assert bearing.spec == {"bearing_no": "6305", "shield": "ZZ"}
        assert bearing.location == "B선반 1칸"
        adjust = s.scalar(select(Movement).where(Movement.part_id == bearing.id))
        assert (adjust.type, adjust.qty, adjust.reason) == ("ADJUST", 4, "초기 재고")
        link = s.scalar(select(SupplierPart).where(SupplierPart.part_id == bearing.id))
        assert link.unit_price == 21000
        # 기존 부품 6205ZZ는 원장을 건드리지 않고, 다른 이름은 별칭으로 남긴다
        assert s.scalar(select(func.sum(Movement.qty)).where(Movement.part_id == P6205)) == 3
        assert s.scalar(select(PartAlias.id).where(PartAlias.text == "베어링 6205 ZZ"))
    again = _confirm(client, import_id, rows)
    assert again.status_code == 409


def test_reimport_ignores_stock_until_preview_and_apply(client, demo_db, fresh):
    _use_ai(client, None)
    first = _upload(client).json()
    _confirm(client, first["import_id"], [{"row": 2}, {"row": 3}])

    second = _upload(client, CSV.replace("볼베어링 6305ZZ,4", "볼베어링 6305ZZ,1"))
    body = second.json()
    assert body["is_reimport"] is True
    created = _rows(second)[2]["existing_part_id"]
    assert created is not None
    import_id = body["import_id"]
    assert _confirm(client, import_id, [{"row": 2}], "initial").status_code == 400
    assert _confirm(client, import_id, [{"row": 2}], "apply").status_code == 400
    preview = _confirm(client, import_id, [{"row": 2}, {"row": 3}], "preview")
    assert preview.json()["stock_diffs"] == [
        {
            "row": 2,
            "part_id": created,
            "name": "볼베어링 6305ZZ",
            "ledger_stock": 4,
            "file_stock": 1,
            "diff": -3,
        }
    ]
    applied = _confirm(client, import_id, [{"row": 2}, {"row": 3}], "apply")
    assert applied.json()["adjust_movements"] == 1
    with Session(demo_db.admin) as s:
        rows = s.execute(
            select(Movement.qty, Movement.reason).where(Movement.part_id == created)
        ).all()
        assert sorted(rows) == [(-3, "엑셀 재이관"), (4, "초기 재고")]


def test_reimport_default_ignores_stock(client, demo_db, fresh):
    _use_ai(client, None)
    _confirm(client, _upload(client).json()["import_id"], [{"row": 2}])
    second = _upload(client, CSV.replace("볼베어링 6305ZZ,4", "볼베어링 6305ZZ,9")).json()
    assert _confirm(client, second["import_id"], [{"row": 2}]).json()["updated"] == 1
    with Session(demo_db.admin) as s:
        part = s.scalar(select(Part).where(Part.name == "볼베어링 6305ZZ"))
        assert s.scalar(select(func.sum(Movement.qty)).where(Movement.part_id == part.id)) == 4


def test_row_errors_block_only_that_row(client, fresh):
    _use_ai(client, None)
    res = _upload(client, "부품명,재고,단위\n볼트,많음,개\n,3,\n너트,5,개\n")
    rows = _rows(res)
    assert rows[2]["errors"] == ["stock_invalid"]
    assert rows[3]["errors"] == ["name_required", "unit_required"]
    assert [r["row"] for r in res.json()["rows"]][:2] == [2, 3]
    assert _confirm(client, res.json()["import_id"], [{"row": 2}]).status_code == 400
    assert _confirm(client, res.json()["import_id"], [{"row": 4}]).status_code == 200


def test_xlsx_and_unknown_supplier_warning(client, fresh):
    _use_ai(client, None)
    book = Workbook()
    sheet = book.active
    sheet.append(["품명", "현재 재고", "단위", "공급사"])
    sheet.append(["오링 P-25", 30, "개", "없는상사"])
    buffer = io.BytesIO()
    book.save(buffer)
    res = _upload(client, buffer.getvalue(), name="parts.xlsx")
    assert res.status_code == 200, res.text
    row = _rows(res)[2]
    assert (row["stock"], row["spec"], row["warnings"]) == (
        30,
        {"size": "P25"},
        ["supplier_unknown"],
    )


@pytest.mark.parametrize(
    ("content", "name"),
    [
        ("이름,단위\n볼트,개\n", "parts.csv"),
        ("부품명,재고,단위\n", "parts.csv"),
        ("x", "parts.txt"),
    ],
)
def test_bad_file_is_rejected(client, fresh, content, name):
    _use_ai(client, None)
    assert _upload(client, content, name=name).status_code == 400


def test_worker_cannot_import(client, fresh):
    _use_ai(client, None)
    assert _upload(client, user="worker").status_code == 403
