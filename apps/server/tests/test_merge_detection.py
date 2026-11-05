from bjk_server.domain.merge import MergePart, find_duplicates, name_score

CAT = "bolt"


def _part(pid, name, spec, category=CAT, vec=None, model=None):
    return MergePart(pid, category, name, spec, vec, model)


def test_same_spec_and_similar_name_is_candidate():
    pairs = find_duplicates(
        [
            _part("b", "헥사볼트 M8x20", {"thread": "M8", "length_mm": 20}),
            _part("a", "육각볼트 M8-20", {"thread": "m8", "length_mm": "20"}),
        ]
    )
    assert [(p.part_a, p.part_b, p.reason) for p in pairs] == [
        ("a", "b", "spec_exact+name_similar")
    ]


def test_spec_conflict_category_or_empty_spec_is_never_candidate():
    parts = [
        _part("a", "육각볼트 M8-20", {"thread": "M8", "length_mm": 20}),
        _part("b", "육각볼트 M8-30", {"thread": "M8", "length_mm": 30}),
        _part("c", "육각볼트 M8-20", {"thread": "M8", "length_mm": 20}, category="other"),
        _part("d", "육각볼트", {}),
        _part("e", "육각볼트", {}),
        _part("f", "육각볼트 M8-20", {"thread": "M8", "length_mm": 20}, category=None),
    ]
    assert find_duplicates(parts) == []


def test_embedding_cosine_is_used_when_both_vectors_share_a_model():
    a = _part("a", "가나다", {"thread": "M8"}, vec=[1.0, 0.0], model="m")
    b = _part("b", "라마바", {"thread": "M8"}, vec=[0.9, 0.1], model="m")
    score, ok = name_score(a, b)
    assert ok and 0.99 < score <= 1.0
    far = _part("c", "가나다", {"thread": "M8"}, vec=[0.0, 1.0], model="m")
    assert name_score(a, far) == (0.0, False)
    # 모델이 다르면 벡터를 비교하지 않고 자모 유사도로 본다.
    other_model = _part("d", "가나다", {"thread": "M8"}, vec=[0.0, 1.0], model="n")
    assert name_score(a, other_model) == (1.0, True)
