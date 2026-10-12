import pytest

from app.domain.crm_url import crm_url_problem


@pytest.mark.parametrize(
    ("url", "problem"),
    [
        ("https://crm.railtech.uz", None),
        ("https://crm.railtech.uz/", None),
        ("http://localhost", "localhost"),
        ("https://localhost:5173", "localhost"),
        ("http://127.0.0.1:8000", "localhost"),
        ("http://crm.railtech.uz", "https"),
        ("", "не задан"),
        ("crm.railtech.uz", "не задан"),
    ],
)
def test_crm_url_problem(url: str, problem: str | None) -> None:
    result = crm_url_problem(url)
    if problem is None:
        assert result is None
    else:
        assert result is not None
        assert problem in result
