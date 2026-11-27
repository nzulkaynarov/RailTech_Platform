"""Защита от размывания курса в scripts/check_doc_links.py (КУРС-1, DECISIONS 2026-11-27)."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

D = "docs/"  # пути собираются, чтобы проверка упоминаний не искала несуществующие файлы
BASE = ["docs/COURSE.md", "docs/LIST.md", "docs/LATER.md", "docs/README.md"]


def load():
    spec = importlib.util.spec_from_file_location(
        "check_doc_links", Path(__file__).resolve().parents[1] / "check_doc_links.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class GuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = load()

    def test_clean_tree_passes(self) -> None:
        self.assertEqual(self.mod.guard_errors(BASE, lambda p: 40), [])

    def test_course_over_limit_fails(self) -> None:
        errors = self.mod.guard_errors(BASE, lambda p: 46 if p == "docs/COURSE.md" else 5)
        self.assertTrue(any("COURSE.md" in e and "46" in e for e in errors))
        self.assertEqual(self.mod.guard_errors(BASE, lambda p: 45), [])

    def test_missing_control_documents_fail(self) -> None:
        self.assertEqual(len(self.mod.guard_errors(["docs/README.md"], lambda p: 1)), 3)

    def test_new_queue_file_outside_history_fails(self) -> None:
        for name in (D + "runbooks/plan-2026-12-01.md", D + "runbooks/wave20-x.md", D + "план-работ.md",
                     D + "очередь.md", D + "Backlog.md", D + "runbooks/волна-20.md"):
            with self.subTest(name=name):
                self.assertTrue(self.mod.guard_errors([*BASE, name], lambda p: 5))

    def test_history_allowlist_and_unrelated_names_pass(self) -> None:
        ok = [D + "history/runbooks/plan-2026-11-12.md", D + "strategy/2026-11-01-plan-refresh.md",
              D + "research/explanation.md", D + "runbooks/deploy.md", D + "screens/plan-1-1/readme.md"]
        self.assertEqual(self.mod.guard_errors([*BASE, *ok], lambda p: 5), [])


if __name__ == "__main__":
    unittest.main()
