from bjk_server.domain.matching import PartText, match_parts

BOLT = PartText("bolt", "육각볼트 M8-20", {"thread": "M8", "length_mm": 20})
BOLT30 = PartText("bolt30", "육각볼트 M8-30", {"thread": "M8", "length_mm": 30})
BELT = PartText("belt", "V벨트 A-42", {"type": "A", "length": 42})
BEARING = PartText("bearing", "볼베어링 6205ZZ", {"bearing_no": "6205", "shield": "ZZ"})
PARTS = [BOLT, BOLT30, BELT, BEARING]


def test_without_semantic_ranking_is_unchanged():
    assert match_parts("hex bolt", PARTS) == match_parts("hex bolt", PARTS, None)
    assert match_parts("hex bolt", PARTS).ranked == []


def test_semantic_only_candidate_needs_min_cosine():
    result = match_parts("hex bolt", PARTS, {"bolt": 0.7, "belt": 0.3})
    assert [(r.part_id, r.semantic_only) for r in result.ranked] == [("bolt", True)]
    assert result.confirmed is None  # 0.85 미만


def test_cosine_confirms_top_with_gap():
    result = match_parts("hex bolt", PARTS, {"bolt": 0.92, "bolt30": 0.80})
    assert (result.confirmed, result.confirmed_by) == ("bolt", "semantic")


def test_cosine_gap_too_small_needs_selection():
    result = match_parts("hex bolt", PARTS, {"bolt": 0.92, "bolt30": 0.89})
    assert [r.part_id for r in result.ranked] == ["bolt", "bolt30"]
    assert result.confirmed is None


def test_company_thresholds_apply():
    semantic = {"bolt": 0.80, "bolt30": 0.60}
    assert match_parts("hex bolt", PARTS, semantic).confirmed is None
    assert match_parts("hex bolt", PARTS, semantic, 0.75, 0.1).confirmed == "bolt"


def test_spec_conflict_is_never_matched_by_meaning():
    result = match_parts("hex bolt M8x30", PARTS, {"bolt": 0.99, "bolt30": 0.70})
    assert [r.part_id for r in result.ranked] == ["bolt30"]
    assert (result.confirmed, result.confirmed_by) == ("bolt30", "spec")


def test_rrf_combines_spelling_and_meaning():
    # 철자로는 베어링이 1위지만 의미로는 벨트가 1위. 두 순위에 모두 든 후보가 앞선다.
    result = match_parts("베어링", PARTS, {"belt": 0.95, "bearing": 0.90})
    assert [r.part_id for r in result.ranked][:2] == ["bearing", "belt"]
    assert result.ranked[0].cosine == 0.90 and not result.ranked[0].semantic_only
    assert result.confirmed is None  # 1위 코사인 0.90, 2위 0.95보다 낮음
