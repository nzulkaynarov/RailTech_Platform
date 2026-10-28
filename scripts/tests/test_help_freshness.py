"""Мягкая проверка актуальности помощи (W-REL): экран изменён, статья нет -> предупреждение, не ошибка."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import help_freshness as hf  # noqa: E402

WEB = "apps/platform/web/src"
ARTICLES = {
    "docs/kb/help/inbox.md": ["/eds/inbox"],
    "docs/kb/help/queue.md": ["/dashboard/queue"],
    "docs/kb/help/profile.md": ["/me"],
}


class Freshness(unittest.TestCase):
    def test_screen_paths_map_to_code(self) -> None:
        self.assertTrue(hf.code_of("/eds/inbox", f"{WEB}/modules/eds/inbox/InboxPage.tsx"))
        self.assertTrue(hf.code_of("/dashboard/queue", f"{WEB}/modules/dashboard/QueuePage.tsx"))
        self.assertTrue(hf.code_of("/me", f"{WEB}/features/profile/ProfilePage.tsx"))
        self.assertFalse(hf.code_of("/eds/inbox", f"{WEB}/modules/eds/drafts/DraftsPage.tsx"))
        self.assertFalse(hf.code_of("/dashboard/queue", f"{WEB}/modules/dashboard/projects/x.tsx"))

    def test_screen_changed_article_not_warns(self) -> None:
        out = hf.check([f"{WEB}/modules/eds/inbox/InboxPage.tsx"], ARTICLES, None)
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].startswith("::warning file=docs/kb/help/inbox.md::Экран /eds/inbox"))

    def test_article_changed_too_is_quiet(self) -> None:
        changed = [f"{WEB}/modules/eds/inbox/InboxPage.tsx", "docs/kb/help/inbox.md"]
        self.assertEqual(hf.check(changed, ARTICLES, "Для пользователей (директор): …"), [])

    def test_reminds_about_the_user_line(self) -> None:
        changed = [f"{WEB}/modules/eds/inbox/InboxPage.tsx", "docs/kb/help/inbox.md"]
        out = hf.check(changed, ARTICLES, "## Что\n- правка")
        self.assertEqual(len(out), 1)
        self.assertIn("Для пользователей", out[0])

    def test_front_matter_screens(self) -> None:
        text = "---\ntitle: x\nscreens: [/a/b, /c]\n---\nтекст"
        self.assertEqual(hf.screens_of(text), ["/a/b", "/c"])
        self.assertEqual(hf.screens_of("---\ntitle: x\nscreens: []\n---\n"), [])


if __name__ == "__main__":
    unittest.main()
