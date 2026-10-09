import pytest

from app.domain.fulltext import query_terms, ts_config


@pytest.mark.parametrize(("lang", "cfg"), [("ru", "russian"), ("en", "english"), ("uz", "simple")])
def test_ts_config(lang: str, cfg: str) -> None:
    assert ts_config(lang) == cfg  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Сколько стоит касса? Касса!", ["сколько", "стоит", "касса"]),
        ("O‘zbekistonda narxi", ["o'zbekistonda", "narxi"]),
        ("a b c", []),
        ("", []),
    ],
)
def test_query_terms(text: str, expected: list[str]) -> None:
    assert query_terms(text) == expected


def test_query_terms_limit() -> None:
    assert len(query_terms(" ".join(f"w{i}" for i in range(100)), max_terms=5)) == 5
