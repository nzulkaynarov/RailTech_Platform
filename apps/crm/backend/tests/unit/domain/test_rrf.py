import pytest

from app.domain.rrf import reciprocal_rank_fusion


def test_item_in_both_lists_wins() -> None:
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["c", "d"]])
    assert [item.key for item in fused] == ["c", "a", "b", "d"]
    assert fused[0].ranks == (3, 1)


def test_scores_follow_formula() -> None:
    fused = reciprocal_rank_fusion([["a"], ["a"]], k=60)
    assert fused[0].score == pytest.approx(2 / 61)


@pytest.mark.parametrize(
    ("rankings", "expected"),
    [
        ([[], []], []),
        ([["a", "a", "b"]], ["a", "b"]),
        ([["x", "y"], ["y", "x"]], ["x", "y"]),
        ([["b"], ["a"]], ["b", "a"]),
    ],
    ids=["empty", "duplicates-first-wins", "tie-by-first-list", "tie-first-rank-then-key"],
)
def test_ordering(rankings: list[list[str]], expected: list[str]) -> None:
    assert [item.key for item in reciprocal_rank_fusion(rankings)] == expected


def test_limit() -> None:
    assert len(reciprocal_rank_fusion([["a", "b", "c"]], limit=2)) == 2


def test_rejects_non_positive_k() -> None:
    with pytest.raises(ValueError, match="k must be positive"):
        reciprocal_rank_fusion([["a"]], k=0)
