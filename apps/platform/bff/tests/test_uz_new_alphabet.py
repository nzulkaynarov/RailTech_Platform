"""СЦ-7: узбекские фразы BFF (`tr(ru, uz, en)`, тройки, `EVENT_TEXTS_UZ`) — в новом алфавите.

Ö Ğ Ş Ç вместо Oʻ Gʻ Sh Ch, без турецких İ/ı; проверка тем же конвертером, что чинит словари
(`scripts/uz_new_alphabet.py`).
"""

import ast
import importlib.util
import sys
from collections.abc import Iterator
from pathlib import Path

from app.feeds.events_i18n import EVENT_TEXTS_UZ

ROOT = Path(__file__).resolve().parents[4]
FEEDS = Path(__file__).resolve().parents[1] / "app" / "feeds"

_spec = importlib.util.spec_from_file_location(
    "uz_new_alphabet", ROOT / "scripts" / "uz_new_alphabet.py"
)
assert _spec is not None
assert _spec.loader is not None
_module = importlib.util.module_from_spec(_spec)
sys.modules["uz_new_alphabet"] = _module
_spec.loader.exec_module(_module)
convert_uz = _module.convert_uz


def _uz_strings() -> Iterator[tuple[str, str]]:
    for path in sorted(FEEDS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf8"))
        for node in ast.walk(tree):
            uz: ast.expr | None = None
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", "") == "tr"
                and len(node.args) == 3
            ):
                uz = node.args[1]
            elif (
                isinstance(node, ast.Tuple)
                and len(node.elts) == 3
                and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.elts)
            ):
                uz = node.elts[1]
            if uz is None:
                continue
            for const in ast.walk(uz):
                if isinstance(const, ast.Constant) and isinstance(const.value, str):
                    yield f"{path.name}:{const.lineno}", const.value


def test_uz_phrases_are_in_the_new_alphabet() -> None:
    found = list(_uz_strings()) + [(f"events_i18n:{k}", v) for k, v in EVENT_TEXTS_UZ.items()]
    assert len(found) > 150  # обход видит фразы, а не пустоту
    old = [(where, text) for where, text in found if convert_uz(text) != text]
    assert old == []
    turkish = [(where, text) for where, text in found if "İ" in text or "ı" in text]
    assert turkish == []
