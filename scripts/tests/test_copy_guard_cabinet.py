"""Copy guard for the Cabinet texts (ru / uz new Latin / en): no new finding, no H or M at all, the baseline only shrinks.

The tool and its word lists are in scripts/copy_guard/ (stdlib only). Fixed a text — run
`python3 -I scripts/copy_guard/copy_guard.py check . --app cabinet --baseline scripts/copy_guard/baseline/cabinet.json --update`
and commit the shorter baseline. A new finding is fixed in the text, not added to the baseline.
"""

import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "scripts/copy_guard"
BASELINE = GUARD / "baseline/cabinet.json"
ALLOW = GUARD / "allow.tsv"
# Ceilings only go down: each PR that fixes texts lowers the number (README, «Как работать»).
BASELINE_CEILING = 50
ALLOW_CEILING = 5


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, GUARD / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules[name] = mod  # dataclasses look the module up by name
    spec.loader.exec_module(mod)
    return mod


def _row(text: str, lang: str = "ru", audience: str = "client") -> dict:
    return {"app": "cabinet", "surface": "ui", "audience": audience, "lang": lang, "source": "x.json:1",
            "key": "x.y", "text": text}


class CabinetCopyGuard(unittest.TestCase):
    def test_no_new_findings_and_baseline_is_not_stale(self) -> None:
        guard = _load("copy_guard")
        out = io.StringIO()
        with redirect_stdout(out):
            code = guard.guard(ROOT, "cabinet", BASELINE, update=False)
        self.assertEqual(code, 0, out.getvalue())

    def test_baseline_has_no_high_or_medium(self) -> None:
        # H and M are fixed in the text; only L (to look at by eye) may stay in the list
        for entry in json.loads(BASELINE.read_text(encoding="utf-8")):
            self.assertTrue(entry.startswith("L|"), f"fix the text, do not baseline it: {entry}")

    def test_baseline_only_shrinks(self) -> None:
        self.assertLessEqual(len(json.loads(BASELINE.read_text(encoding="utf-8"))), BASELINE_CEILING)

    def test_allow_list_is_short_explained_and_exact(self) -> None:
        lines = [x for x in ALLOW.read_text(encoding="utf-8").splitlines() if x.strip() and not x.startswith("#")]
        self.assertLessEqual(len(lines), ALLOW_CEILING)
        for line in lines:
            key, cls, reason = (line.split("\t") + ["", ""])[:3]
            self.assertTrue(key and cls and reason.strip(), f"key, class and reason are required: {line!r}")
            self.assertNotIn(".*", key, f"no wildcard patterns: {line!r}")
            self.assertNotIn(".+", key, f"no wildcard patterns: {line!r}")

    def test_rules_catch_what_the_cabinet_was_cleaned_of(self) -> None:
        guard = _load("copy_guard")
        rules = guard.load_rules()

        def classes(text: str, lang: str = "ru") -> set[str]:
            return {f.cls for f in guard.check_row(_row(text, lang), rules, None)}

        self.assertIn("audience", classes("КП {{number}} ждёт решения"))
        self.assertIn("audience", classes("Сделка"))
        self.assertIn("audience", classes("Договор придёт вам в ЭДО"))
        self.assertIn("audience", classes("Contract comes via e-document exchange", "en"))
        self.assertIn("jargon", classes("Respond to RFQ", "en"))
        self.assertIn("audience", classes("Contract comes via EDI", "en"))
        self.assertIn("gender", classes("Согласен(на) на обработку"))
        self.assertIn("promise", classes("Файлы в чат пока не прикладываются"))
        self.assertIn("jargon", classes("Рег. номер / Tax ID"))

    def test_rules_do_not_flag_plain_words(self) -> None:
        guard = _load("copy_guard")
        rules = guard.load_rules()
        for text, lang in (
            ("Предложение {{number}} ждёт вашего решения", "ru"),
            ("Договор будет выставлен на подписание", "ru"),
            ("Lead time is a whole number of days.", "en"),
            ("Hisob-faktura", "uz"),
            ("Drop PDF here or click to select", "en"),
        ):
            found = [f for f in guard.check_row(_row(text, lang), rules, None) if f.severity in ("H", "M")]
            self.assertEqual(found, [], text)


if __name__ == "__main__":
    unittest.main()
