"""ПРАВДА-2: сделку-заявку создаёт одна функция (`request_deal.create_request_deal`), других путей нет."""

from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]


def test_no_other_module_names_a_request_after_the_company():
    offenders = [
        str(path.relative_to(BACKEND))
        for path in BACKEND.rglob("*.py")
        if "tests" not in path.parts
        and "migrations" not in path.parts
        and path.name != "request_deal.py"
        and 'title=f"Заявка:' in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
