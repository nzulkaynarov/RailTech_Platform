"""Сборщик «Что нового» (W-REL) на примере: строки «Для пользователей» из PR -> запись changelog. Запуск:
python3 -m unittest discover -s scripts/tests"""

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import release_notes as rn  # noqa: E402

FIXTURE = HERE / "fixtures/release_prs.json"


class NotesOf(unittest.TestCase):
    def test_roles_all_and_placeholders(self) -> None:
        prs = json.loads(FIXTURE.read_text(encoding="utf-8"))
        notes = [n for pr in prs for n in rn.notes_of(pr)]
        self.assertEqual(
            notes,
            [
                rn.Note(("Директор",), "Резолюция теперь в одном окне с письмом.", 301),
                rn.Note((), "Версия Платформы — внизу меню аватара.", 303),
                rn.Note(("Снабженец", "Главный инженер"), "Расчёт показывает срок.", 303),
            ],
        )

    def test_comment_of_the_template_is_not_a_note(self) -> None:
        body = "<!--\nДля пользователей (директор): пример из шаблона\n-->"
        self.assertEqual(rn.notes_of({"number": 1, "body": body}), [])


class Render(unittest.TestCase):
    def test_entry_in_the_format_of_the_whats_new_screen(self) -> None:
        notes = [rn.Note(("Директор",), "Резолюция в окне.", 301), rn.Note((), "Версия в меню.", 303)]
        text = rn.render(notes, date(2026, 11, 2))
        self.assertTrue(text.startswith("---\ndate: 2026-11-02\ntitle: Обновление 2 ноября 2026\n---\n"))
        self.assertIn("- **Директор:** Резолюция в окне.\n- **Все:** Версия в меню.\n", text)
        self.assertIn("PR: #301, #303", text)

    def test_second_deploy_of_the_day_appends(self) -> None:
        first = rn.render([rn.Note((), "Первое.", 1)], date(2026, 11, 2))
        both = rn.render([rn.Note((), "Второе.", 2)], date(2026, 11, 2), first)
        self.assertEqual(both.count("date: 2026-11-02"), 1)
        self.assertIn("- **Все:** Первое.", both)
        self.assertIn("- **Все:** Второе.", both)


class Cli(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(HERE.parent / "release_notes.py"), *args],
            capture_output=True,
            text=True,
            check=True,
        )

    def test_writes_the_dated_file(self) -> None:
        with tempfile.TemporaryDirectory() as out:
            self.run_cli("--prs-json", str(FIXTURE), "--date", "2026-11-02", "--out-dir", out)
            text = (Path(out) / "2026-11-02.md").read_text(encoding="utf-8")
        self.assertIn("- **Снабженец, Главный инженер:** Расчёт показывает срок.", text)

    def test_nothing_to_say_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as out:
            empty = Path(out) / "prs.json"
            empty.write_text(json.dumps([{"number": 9, "body": "Для пользователей: нет"}]), "utf-8")
            result = self.run_cli("--prs-json", str(empty), "--out-dir", out)
            self.assertIn("нет строк", result.stdout)
            self.assertEqual(sorted(p.name for p in Path(out).iterdir()), ["prs.json"])


if __name__ == "__main__":
    unittest.main()
