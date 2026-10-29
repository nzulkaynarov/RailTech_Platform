"""Хуки Claude Code (`.claude/hooks/`) и проверка сообщения коммита (`scripts/check_commit_msg.py`), W-AGENT1. Запуск:
python3 -m unittest discover -s scripts/tests"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(ROOT / ".claude/hooks"))

import check_commit_msg as cm  # noqa: E402
import format_file  # noqa: E402
import guard_bash  # noqa: E402
import guard_write  # noqa: E402


def git(cwd: str, *args: str) -> None:
    subprocess.run(["git", "-C", cwd, *args], check=True, capture_output=True)


class Repo(unittest.TestCase):
    """Временный репозиторий: ветки main и feat, рабочая копия на нужной ветке."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        git(self.dir, "init", "-q", "-b", "main")
        git(self.dir, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init")
        git(self.dir, "branch", "feat")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def blocked(self, command: str) -> bool:
        return guard_bash.verdict(command, self.dir)[0]


class GuardBashOnFeatureBranch(Repo):
    def setUp(self) -> None:
        super().setUp()
        git(self.dir, "switch", "-q", "feat")

    def test_own_branch_push_and_commit_pass(self) -> None:
        for command in (
            "git push -u origin feat",
            "git push",
            "git push origin HEAD",
            f"git -C {self.dir} push -u origin feat 2>&1 | tail -3",
            "git commit -m 'fix(crm): main меню (X-1)'",
            "git merge origin/main",
            "git push origin feat --follow-tags",
        ):
            self.assertFalse(self.blocked(command), command)

    def test_push_to_main_by_refspec(self) -> None:
        for command in (
            "git push origin main",
            "git push origin HEAD:main",
            "git push origin feat:refs/heads/main",
            "git push origin --delete main",
            "cd /tmp && git push origin main",
            "bash -c 'git push origin main'",
            "FOO=1 git push origin main",
        ):
            self.assertTrue(self.blocked(command), command)

    def test_force_and_no_verify(self) -> None:
        for command in (
            "git push --force origin feat",
            "git push -f origin feat",
            "git push -uf origin feat",
            "git push --force-with-lease origin feat",
            "git push origin +feat",
            "git push --all",
            "git push --no-verify origin feat",
            "git commit --no-verify -m x",
            "git commit -nm x",
        ):
            self.assertTrue(self.blocked(command), command)

    def test_heredoc_body_is_not_a_command(self) -> None:
        command = "git commit -F - <<'EOF'\nfix: текст\ngit push origin main\nEOF\n"
        self.assertFalse(self.blocked(command))


class GuardBashOnMain(Repo):
    def test_main_branch_writes_blocked(self) -> None:
        for command in (
            "git push",
            "git push origin HEAD",
            "git commit -m 'x'",
            "git merge feat",
            "git cherry-pick abc",
        ):
            self.assertTrue(self.blocked(command), command)

    def test_main_branch_reads_and_fast_forward_pass(self) -> None:
        for command in (
            "git status",
            "git log --oneline -3",
            "git pull --ff-only",
            "git merge --ff-only origin/main",
            "git fetch origin main",
            "git worktree add .claude/worktrees/x -b x origin/main",
        ):
            self.assertFalse(self.blocked(command), command)

    def test_git_dash_c_points_to_feature_worktree(self) -> None:
        wt = os.path.join(self.dir, "wt")
        git(self.dir, "worktree", "add", "-q", wt, "feat")
        self.assertFalse(self.blocked(f"git -C {wt} push"))
        self.assertFalse(self.blocked(f"cd {wt} && git commit -m x"))


class GuardBashOther(unittest.TestCase):
    def blocked(self, command: str) -> bool:
        return guard_bash.verdict(command, "/tmp")[0]

    def test_docker(self) -> None:
        for command in (
            "docker system prune -af",
            "docker volume prune",
            "docker builder prune",
            "docker compose down -v",
            "docker compose -f infra/a.yml down --volumes",
        ):
            self.assertTrue(self.blocked(command), command)
        for command in (
            "docker compose -p rt-x down -v",
            "docker compose down",
            "docker ps",
            "make down",
            "docker compose --env-file .env up -d",
        ):
            self.assertFalse(self.blocked(command), command)

    def test_rm(self) -> None:
        for command in ("rm -rf /", "rm -rf ~", "rm -rf .", "rm -fr *", "rm -r ..", "rm -rf .git", "rm -rf $HOME"):
            self.assertTrue(self.blocked(command), command)
        for command in ("rm -rf node_modules", "rm -rf apps/crm/backend/.venv", "rm .", "rm -f ~/x.log"):
            self.assertFalse(self.blocked(command), command)

    def test_secrets(self) -> None:
        for command in (
            "cat .env",
            "cat infra/.env.prod",
            "head -50 apps/x/.env",
            "cat ~/.ssh/id_ed25519",
            "tail ~/RailTech-secrets/prod.txt",
            "cat .env | grep X",
        ):
            self.assertTrue(self.blocked(command), command)
        for command in (
            "cat .env.example",
            "cat infra/.env.prod.example",
            "cat apps/platform/web/.env.mock",
            "grep '^HTTP_PORT=' .env",
            "set -a && . ./.env && make up",
            "make env",
        ):
            self.assertFalse(self.blocked(command), command)

    def test_hook_protocol(self) -> None:
        def run(command: str) -> subprocess.CompletedProcess:
            payload = json.dumps({"tool_input": {"command": command}, "cwd": "/tmp"})
            return subprocess.run(
                [sys.executable, str(ROOT / ".claude/hooks/guard_bash.py")],
                input=payload,
                capture_output=True,
                text=True,
            )

        bad = run("docker system prune")
        self.assertEqual(bad.returncode, 2)
        self.assertIn("HANDOFF §5", bad.stderr)
        self.assertEqual(run("ls -la").returncode, 0)
        self.assertEqual(run("echo 'unbalanced").returncode, 0)


class GuardWrite(Repo):
    """Пути — без «.md»: суффикс добавляет `md`, иначе scripts/check-doc-links.sh принял бы примеры за ссылки."""

    def reason(self, rel: str):
        return guard_write.check(os.path.join(self.dir, rel))

    def md(self, rel: str):
        return self.reason(rel + ".md")

    def test_new_md_outside_docs_blocked(self) -> None:
        self.assertIsNotNone(self.md("apps/crm/NOTES"))
        self.assertIsNotNone(self.md("PLAN"))

    def test_allowed_places(self) -> None:
        for rel in (
            "docs/runbooks/x",
            "apps/x/CLAUDE",
            "packages/y/README",
            ".claude/skills/a/SKILL",
            ".claude/agents/executor",
            "apps/crm/backend/prompts/p",
            "apps/crm/backend/templates/email/a",
            "apps/platform/web/src/generated/help-articles/a",
            ".github/PULL_REQUEST_TEMPLATE",
        ):
            self.assertIsNone(self.md(rel), rel)
        self.assertIsNone(self.reason("apps/crm/main.py"))

    def test_existing_file_and_outside_repo_pass(self) -> None:
        Path(self.dir, "OLD.md").write_text("x")
        self.assertIsNone(self.reason("OLD.md"))
        with tempfile.TemporaryDirectory() as other:
            self.assertIsNone(guard_write.check(os.path.join(other, "notes.md")))


class FormatFile(Repo):
    def test_picks_formatter_of_the_app(self) -> None:
        d = Path(self.dir)
        for rel in (
            "apps/eds/.venv/bin/ruff",
            "apps/erp/.venv-tools/bin/black",
            "apps/erp/.venv-tools/bin/isort",
            "apps/platform/web/node_modules/.bin/prettier",
        ):
            (d / rel).parent.mkdir(parents=True, exist_ok=True)
            (d / rel).write_text("")
        (d / "apps/eds/pyproject.toml").write_text("")
        (d / "apps/platform/web/package.json").write_text('{"scripts": {"format:check": "prettier --check ."}}')
        files = {
            rel: d / rel
            for rel in (
                "apps/eds/app/a.py",
                "apps/erp/backend/b.py",
                "apps/platform/web/src/c.tsx",
                "apps/cabinet/src/d.tsx",
                "docs/e" + ".md",
            )
        }
        for f in files.values():
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("")
        real = os.path.realpath
        tools = {
            rel: [os.path.basename(cmd[0]) for cmd, _ in format_file.commands(real(f))] for rel, f in files.items()
        }
        self.assertEqual(tools["apps/eds/app/a.py"], ["ruff"])
        self.assertEqual(tools["apps/erp/backend/b.py"], ["black", "isort"])
        self.assertEqual(tools["apps/platform/web/src/c.tsx"], ["prettier"])
        self.assertEqual(tools["apps/cabinet/src/d.tsx"], [])
        self.assertEqual(tools["docs/e" + ".md"], [])


class CommitMsg(unittest.TestCase):
    TRAILER = "\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n"

    def test_good_message(self) -> None:
        self.assertEqual(cm.check("feat(crm): лиды (W-AGENT1)" + self.TRAILER), ([], []))
        self.assertEqual(cm.check("docs,test(platform): снимки (D2-3)" + self.TRAILER), ([], []))

    def test_errors_and_warning(self) -> None:
        errors, _ = cm.check("поправил что-то" + self.TRAILER)
        self.assertEqual(len(errors), 1)
        errors, _ = cm.check("fix(erp): тест (W-1)\n")
        self.assertIn("Co-Authored-By", errors[0])
        errors, warnings = cm.check("fix(erp): тест без задачи" + self.TRAILER)
        self.assertEqual((errors, len(warnings)), ([], 1))

    def test_skipped(self) -> None:
        for msg in ("Merge origin/main", "Merge pull request #1 from x/y", "fixup! feat: x", 'Revert "feat: x"', ""):
            self.assertEqual(cm.check(msg), ([], []), msg)

    def test_comments_and_scissors_ignored(self) -> None:
        msg = "fix: x (A-1)\n# Please enter the commit message\n" + self.TRAILER + cm.SCISSORS + "\ndiff --git"
        self.assertEqual(cm.check(msg), ([], []))

    def test_only_agents_are_checked(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write("поправил что-то\n")
        try:
            with mock.patch.dict(os.environ, {"CLAUDECODE": "", "GEMINI_CLI": "", "RT_COMMIT_CHECK": ""}):
                self.assertEqual(cm.main(["x", f.name]), 0)
            with mock.patch.dict(os.environ, {"CLAUDECODE": "1"}):
                self.assertEqual(cm.main(["x", f.name]), 1)
        finally:
            os.unlink(f.name)


if __name__ == "__main__":
    unittest.main()
