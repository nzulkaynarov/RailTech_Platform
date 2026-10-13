import math

import pytest

from app.domain.embedding_profile import GEMINI_EMBEDDING_2, l2_normalize


def test_query_and_document_formatting() -> None:
    assert GEMINI_EMBEDDING_2.format_query("  Цена? ") == "task: search result | query: Цена?"
    assert GEMINI_EMBEDDING_2.format_document("текст", None) == "title: none | text: текст"
    assert GEMINI_EMBEDDING_2.format_document("t", " Кассы ") == "title: Кассы | text: t"


def test_dimensions_fit_hnsw_limit() -> None:
    assert GEMINI_EMBEDDING_2.dimensions <= 2000


@pytest.mark.parametrize("vector", [[3.0, 4.0], [1e-9, 0.0, 0.0], [-2.0, 2.0, 1.0]])
def test_l2_normalize_unit_length(vector: list[float]) -> None:
    assert math.isclose(math.hypot(*l2_normalize(vector)), 1.0, rel_tol=1e-12)


@pytest.mark.parametrize("vector", [[0.0, 0.0], [float("nan"), 1.0], [float("inf"), 1.0]])
def test_l2_normalize_rejects_degenerate(vector: list[float]) -> None:
    with pytest.raises(ValueError, match="normalize"):
        l2_normalize(vector)
