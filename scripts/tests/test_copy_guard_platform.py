"""Copy guard for the Platform texts (web i18n ru / uz new Latin / en and the BFF texts): no new finding, the baseline only shrinks.

The tool and its word lists are in scripts/copy_guard/ (stdlib only). Fixed a text — run
`python3 -I scripts/copy_guard/copy_guard.py check . --app platform --baseline scripts/copy_guard/baseline/platform.json --update`
and commit the shorter baseline. A new finding is fixed in the text, not added to the baseline.

Statuses follow docs/architecture/status-dictionary.md. An action is attributed to a capability, not to a job title.
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
BASELINE = GUARD / "baseline/platform.json"
ALLOW = GUARD / "allow.tsv"
# Ceilings only go down: each PR that fixes texts lowers the number (README, «Как работать»).
BASELINE_CEILING = 598
ALLOW_CEILING = 1


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, GUARD / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules[name] = mod  # dataclasses look the module up by name
    spec.loader.exec_module(mod)
    return mod


def _row(text: str, lang: str = "ru", key: str = "x:y", audience: str = "staff", ctx: str = "") -> dict:
    return {"app": "platform", "surface": "ui", "audience": audience, "lang": lang, "source": "x.json:1",
            "key": key, "text": text, "ctx": ctx}


def _entries() -> list[list[str]]:
    # fingerprint: severity|app|source|key|lang|class|match
    return [e.split("|") for e in json.loads(BASELINE.read_text(encoding="utf-8"))]


class PlatformCopyGuard(unittest.TestCase):
    def test_no_new_findings_and_baseline_is_not_stale(self) -> None:
        guard = _load("copy_guard")
        out = io.StringIO()
        with redirect_stdout(out):
            code = guard.guard(ROOT, "platform", BASELINE, update=False)
        self.assertEqual(code, 0, out.getvalue())

    def test_baseline_has_no_high_or_medium(self) -> None:
        # H and M are fixed in the text; only L (to look at by eye) may stay in the list
        for entry in json.loads(BASELINE.read_text(encoding="utf-8")):
            self.assertTrue(entry.startswith("L|"), f"fix the text, do not baseline it: {entry}")

    def test_baseline_only_shrinks(self) -> None:
        self.assertLessEqual(len(_entries()), BASELINE_CEILING)

    def test_bff_texts_have_no_pending_findings(self) -> None:
        # the BFF (errors, event feed, queue) is clean: nothing from apps/platform/bff may be baselined above L
        for e in _entries():
            if "apps/platform/bff/" in e[2]:
                self.assertEqual(e[0], "L", f"fix the BFF text: {e[3]}")

    def test_allow_list_is_short_explained_and_exact(self) -> None:
        lines = [x for x in ALLOW.read_text(encoding="utf-8").splitlines() if x.strip() and not x.startswith("#")]
        # every row of the file is checked (not only this app's): known app, reason, no wildcard patterns
        for line in lines:
            key, cls, reason, app = (line.split("\t") + ["", "", ""])[:4]
            self.assertIn(app, ("cabinet", "platform"), f"a row must name its app in column 4: {line!r}")
            self.assertTrue(key and cls and reason.strip(), f"key, class and reason are required: {line!r}")
            self.assertNotIn(".*", key, f"no wildcard patterns: {line!r}")
            self.assertNotIn(".+", key, f"no wildcard patterns: {line!r}")
            for wide in ("\\w+", "\\w*", "[^"):
                self.assertNotIn(wide, key, f"no wide patterns: {line!r}")
        mine = [x for x in lines if (x.split("\t") + ["", "", "", ""])[3] == "platform"]
        self.assertLessEqual(len(mine), ALLOW_CEILING)

    def test_allow_row_applies_only_to_its_app(self) -> None:
        guard = _load("copy_guard")
        text = "title language source updated tags audience"
        key = "kb:format.rules[0]"  # the one platform row of allow.tsv (class mixed)

        def mixed(app: str) -> bool:
            row = dict(_row(text, key=key), app=app)
            return "mixed" in {f.cls for f in guard.check_row(row, guard.load_rules(), None)}

        self.assertFalse(mixed("platform"))
        self.assertFalse(mixed("platform-bff"))
        self.assertTrue(mixed("cabinet"), "a platform allow row must not pass the same key in another app")

    def test_unknown_app_in_allow_file_is_an_error(self) -> None:
        guard = _load("copy_guard")
        tmp = Path(__file__).with_name("_allow_unknown_app.tsv")
        tmp.write_text("x\tcode\treason\tnobody\n", encoding="utf-8")
        try:
            with self.assertRaises(ValueError):
                guard._load_allow(tmp)
        finally:
            tmp.unlink()

    def test_rules_catch_what_the_platform_was_cleaned_of(self) -> None:
        guard = _load("copy_guard")
        rules = guard.load_rules()

        def classes(text: str, lang: str = "ru", **kw) -> set[str]:
            return {f.cls for f in guard.check_row(_row(text, lang, **kw), rules, None)}

        self.assertIn("jargon", classes("Нет доступа к ERP."))
        self.assertIn("jargon", classes("CRM недоступна, повторите позже."))
        self.assertIn("jargon", classes("Время на ответ (SLA)"))
        self.assertIn("jargon", classes("В маске обязателен токен {seq}"))
        self.assertIn("jargon", classes("Платёжка не найдена."))
        self.assertIn("jargon", classes("Проверка SPF/DKIM/DMARC не прошла"))
        self.assertIn("promise", classes("Автоматической отправки клиенту пока нет"))
        self.assertIn("promise", classes("КП согласовано автоматически"))
        self.assertIn("gender", classes("назначен(а): {{names}}"))
        self.assertIn("jobtitle", classes("Черновик КП у директора"))
        self.assertIn("terms", classes("Invite to the cabinet", "en"))
        self.assertIn("code", classes("Статус: {{status}}"))
        self.assertIn("code", classes("укажите language или active_role"))
        self.assertIn("mixed", classes("Файл нужно передать формой multipart."))
        self.assertIn("mixed", classes("PDF и документы Office"))
        self.assertIn("vendor", classes("Pick a zoom", "en"))

    def test_rules_do_not_flag_plain_words(self) -> None:
        guard = _load("copy_guard")
        rules = guard.load_rules()
        for text, lang, key in (
            ("Ожидает подписания", "ru", "dictionary:status.contract.issued"),
            ("Оплата на проверке", "ru", "dictionary:status.invoice.proof_received"),
            ("Передана на оплату", "ru", "dictionary:status.memo.passed_to_accountant"),
            ("Click a role column in the matrix", "en", "modules:panel.role.text"),
            ("Drag the photo and set the scale", "en", "profile:photo.cropHint"),
            ("PDF, images and Word and Excel files", "en", "documents:form.files.hint"),
            ("Загрузить файл Markdown", "ru", "kb:create.upload.title"),
            ("English", "ru", "shell:languages.en"),
            ("Русский", "en", "shell:languages.ru"),
            ("Платёжное поручение не найдено.", "ru", "x:y"),
        ):
            found = [f for f in guard.check_row(_row(text, lang, key=key), rules, None) if f.severity in ("H", "M")]
            self.assertEqual(found, [], text)


if __name__ == "__main__":
    unittest.main()
