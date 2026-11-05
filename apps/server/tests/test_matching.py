import pytest
from bjk_server.db.models import Part
from bjk_server.domain.matching import (
    PartText,
    extract_spec,
    jamo,
    match_parts,
    normalize,
    similarity,
    spec_relation,
)
from bjk_server.seed.demo import COMPANY_CODE, demo_id
from sqlalchemy.orm import Session

PARTS = [
    PartText("6205", "볼베어링 6205ZZ", {"bearing_no": "6205", "shield": "ZZ"}),
    PartText("6204", "볼베어링 6204ZZ", {"bearing_no": "6204", "shield": "ZZ"}),
    PartText("2rs", "볼베어링 6205-2RS", {"bearing_no": "6205", "shield": "2RS"}),
    PartText("m820", "육각볼트 M8-20", {"thread": "M8", "length_mm": 20}),
    PartText("p20", "오링 P-20", {"size": "P-20"}, [("작은 오링", False)]),
]


def test_normalize_unifies_spec_separators():
    assert normalize("M8-20") == normalize("M8*20") == normalize("m8 × 20") == "m8x20"


def test_jamo_decomposition():
    assert jamo("베어링") == "ㅂㅔㅇㅓㄹㅣㅇ"


def test_typo_is_closer_than_unrelated_part():
    assert similarity("베아링", "볼베어링 6205ZZ") > similarity("베아링", "육각볼트 M8-20")


@pytest.mark.parametrize(
    ("text", "spec"),
    [
        ("볼베어링 6205ZZ", {"bearing_no": "6205", "shield": "ZZ"}),
        ("6205-2RS", {"bearing_no": "6205", "shield": "2RS"}),
        ("육각볼트 M8*20", {"thread": "M8", "length_mm": "20", "kind": "HEX_BOLT"}),
        ("헥사볼트 M8x20", {"thread": "M8", "length_mm": "20", "kind": "HEX_BOLT"}),
        ("평와셔 M10", {"thread": "M10", "kind": "FLAT_WASHER"}),
        ("와셔 M10", {"thread": "M10"}),
        ("유압유 ISO VG32 20L", {"volume_l": "20", "iso_vg": "32", "kind": "HYDRAULIC_OIL"}),
        ("불수용성 절삭유 18L", {"volume_l": "18", "kind": "NEAT_CUTTING_OIL"}),
        ("수용성 절삭유 20L", {"volume_l": "20", "kind": "SOLUBLE_CUTTING_OIL"}),
        ("V벨트 A-42", {"type": "A", "length": "42"}),
        ("오링 P20", {"size": "P20"}),
        ("베어링", {}),
    ],
)
def test_extract_spec(text, spec):
    assert extract_spec(text) == spec


def test_spec_relation():
    part = {"bearing_no": "6205", "shield": "ZZ"}
    assert spec_relation({"bearing_no": "6205"}, part) == "match"
    assert spec_relation({"bearing_no": "6205", "shield": "2RS"}, part) == "conflict"
    assert spec_relation({"thread": "M8"}, part) == "none"


def test_bearing_number_confirms_unique_spec_and_excludes_other_numbers():
    result = match_parts("6205ZZ", PARTS)
    assert result.confirmed == "6205"
    assert [r.part_id for r in result.ranked] == ["6205"]  # 6204·2RS는 규격 충돌로 제외


def test_partial_spec_with_two_matches_is_not_confirmed():
    result = match_parts("6205", PARTS)
    assert result.confirmed is None
    assert {r.part_id for r in result.ranked} == {"6205", "2rs"}


def test_different_length_bolt_is_never_matched():
    assert match_parts("M8x30 볼트", PARTS).ranked == []


def test_typo_lists_bearings_without_confirming():
    result = match_parts("베아링", PARTS)
    assert result.confirmed is None
    assert {"6205", "6204"} <= {r.part_id for r in result.ranked}


def test_alias_confirms():
    assert match_parts("작은오링", PARTS).confirmed == "p20"


def test_ambiguous_alias_does_not_confirm():
    parts = [
        PartText("a", "부품A", {}, [("그거", True)]),
        PartText("b", "부품B", {}, [("그거", True)]),
    ]
    assert match_parts("그거", parts).confirmed is None


# 채팅 흐름 (시드 데이터)


def test_typo_message_gives_select_with_bearings(chat):
    card = chat("베아링 2개 씀").json()["cards"][0]
    assert card["type"] == "select"
    assert {"볼베어링 6205ZZ", "볼베어링 6204ZZ"} <= {c["name"] for c in card["candidates"]}


def test_bearing_number_message_confirms_6205(chat):
    card = chat("6205 1개 씀").json()["cards"][0]
    assert (card["type"], card["part_id"]) == ("confirm", str(demo_id("part", "6205")))


def test_bolts_are_told_apart_by_length(chat, demo_db):
    with Session(demo_db.admin) as s, s.begin():
        s.add(
            Part(
                company_id=demo_id("company", COMPANY_CODE),
                name="육각볼트 M8-30",
                unit="개",
                spec={"thread": "M8", "length_mm": 30},
            )
        )
    m830 = chat("M8*30 볼트 5개 씀").json()["cards"][0]
    assert m830["type"] == "confirm"
    assert m830["name"] == "육각볼트 M8-30"
    m820 = chat("M8x20 볼트 5개 씀").json()["cards"][0]
    assert (m820["type"], m820["name"]) == ("confirm", "육각볼트 M8-20")
