#!/usr/bin/env python3
"""PreToolUse(Bash) Claude Code: блокирует команды, которые нарушают правила проекта, до их запуска.

Что запрещено и почему — docs/systems/infra/claude-code.md §3; правила — ORCHESTRATOR §4 и §4.1, HANDOFF §5:
- push в `main` (refspec, `HEAD` или без refspec из ветки `main`, `--all`, `--mirror`), force-push, `--no-verify`;
- commit, merge (кроме `--ff-only`), cherry-pick, revert, am в ветке `main`;
- `git clean` с `-x`/`-X` (удаляет `.env` и зависимости);
- общие очистки Docker (`docker * prune`) и `docker compose down -v` без своего проекта `-p`;
- `rm -r` по корню, домашнему каталогу, `.`, `..`, `*`, `.git`;
- вывод файлов с секретами целиком (`cat .env`, `~/.ssh/…`, `~/RailTech-secrets/…`).

Вход — JSON хука на stdin; выход 2 и причина в stderr — команда не запускается, причину видит агент. Ошибка разбора —
выход 0 (сторож не ломает работу; второй рубеж — `permissions.deny` в `.claude/settings.json`). Только stdlib,
Python ≥ 3.9 (системный python3 macOS).
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from collections.abc import Iterator

MAIN = "main"
SEPARATORS = {";", "&", "&&", "|", "||", "|&", "(", ")", "\n"}
WRAPPERS = {"sudo", "env", "command", "time", "nohup", "exec", "builtin"}
READERS = {"cat", "less", "more", "head", "tail", "bat", "strings", "xxd", "od", "hexdump", "base64", "nl", "tac"}
SHELLS = {"bash", "sh", "zsh"}
PUSH_OPTS_WITH_VALUE = {"--repo", "-o", "--push-option", "--receive-pack", "--exec"}
GIT_OPTS_WITH_VALUE = {"-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env"}
HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1[^\n]*\n.*?\n\s*\2\s*(?=\n|$)", re.S)


class Blocked(Exception):
    pass


def segments(command: str) -> Iterator[list[str]]:
    """Команда → простые команды (токены), по разделителям `;`, `&&`, `||`, `|`, `&`, скобкам и переводам строк.
    Тела heredoc выбрасываются: текст сообщения коммита — не команды."""
    command = HEREDOC.sub("<<HEREDOC\n", command)
    lex = shlex.shlex(command, posix=True, punctuation_chars=";&|()\n")
    lex.whitespace = " \t\r"
    lex.whitespace_split = True
    lex.commenters = ""
    current: list[str] = []
    try:
        tokens = list(lex)
    except ValueError:  # незакрытая кавычка — разбираем грубо, по пробелам в каждой строке
        for line in command.splitlines():
            yield line.split()
        return
    for tok in tokens:
        if tok == "&" and current and current[-1].endswith(">"):  # 2>&1 — перенаправление, а не фон
            current[-1] += tok
            continue
        if tok in SEPARATORS or (tok and set(tok) <= set(";&|()\n")):
            if current:
                yield current
            current = []
        else:
            current.append(tok)
    if current:
        yield current


def strip_prefix(tokens: list[str]) -> list[str]:
    """Убирает присваивания `VAR=…` и обёртки (`sudo`, `env`, `time` …) перед командой."""
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tok):
            i += 1
        elif tok in WRAPPERS:
            i += 1
            while i < len(tokens) and tokens[i].startswith("-"):  # env -i, sudo -E …
                i += 1
        else:
            break
    return tokens[i:]


def resolve(cwd: str, path: str) -> str:
    return os.path.normpath(os.path.join(cwd, os.path.expanduser(os.path.expandvars(path))))


def current_branch(cwd: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, timeout=3
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def short_flags(args: list[str]) -> str:
    """Склеенные короткие флаги: `-fdx` → `fdx`."""
    return "".join(a[1:] for a in args if a.startswith("-") and not a.startswith("--") and len(a) > 1)


def check_push(args: list[str], cwd: str) -> None:
    if "--no-verify" in args:
        raise Blocked("git push --no-verify обходит хуки (gitleaks) — запрещено.")
    if any(a.startswith(("--force", "--force-with-lease", "--force-if-includes")) for a in args) or "f" in short_flags(
        [a for a in args if a not in PUSH_OPTS_WITH_VALUE]
    ):
        raise Blocked(
            "force-push запрещён любому агенту (ORCHESTRATOR §4). Конфликт — `git merge origin/main` в свою ветку."
        )
    if "--all" in args or "--mirror" in args:
        raise Blocked("git push --all/--mirror затрагивает main — пушь только свою ветку.")
    positional: list[str] = []
    skip = False
    for a in args:
        if skip:
            skip = False
            continue
        if a in PUSH_OPTS_WITH_VALUE:
            skip = True
            continue
        if not a.startswith("-"):
            positional.append(a)
    refspecs = positional[1:]
    if not refspecs:
        if current_branch(cwd) == MAIN:
            raise Blocked("git push из ветки main запрещён (ORCHESTRATOR §4): main — только через PR.")
        return
    for spec in refspecs:
        if spec.startswith("+"):
            raise Blocked(f"refspec «{spec}» — это force-push, запрещён (ORCHESTRATOR §4).")
        src, _, dst = spec.partition(":")
        dst = dst or src
        dst = dst[len("refs/heads/") :] if dst.startswith("refs/heads/") else dst
        if dst == MAIN or (dst in ("HEAD", "@") and current_branch(cwd) == MAIN):
            raise Blocked("push в main запрещён (ORCHESTRATOR §4): main защищена, только PR из своей ветки.")


def check_git(tokens: list[str], cwd: str) -> None:
    i = 1
    while i < len(tokens) and tokens[i].startswith("-"):
        opt = tokens[i]
        if opt == "-C" and i + 1 < len(tokens):
            cwd = resolve(cwd, tokens[i + 1])
            i += 2
        elif opt in GIT_OPTS_WITH_VALUE:
            i += 2
        else:
            i += 1
    if i >= len(tokens):
        return
    sub, args = tokens[i], tokens[i + 1 :]
    if sub == "push":
        check_push(args, cwd)
    elif sub == "commit":
        if "--no-verify" in args or "n" in short_flags([a for a in args if a not in ("-m", "-F", "-c", "-C")]):
            raise Blocked("git commit --no-verify обходит pre-commit (gitleaks) — запрещено.")
        if current_branch(cwd) == MAIN:
            raise Blocked(
                "Коммит в main запрещён (ORCHESTRATOR §4): работа — в worktree .claude/worktrees/<задача>, своя ветка."
            )
    elif sub in ("merge", "cherry-pick", "revert", "am"):
        if sub == "merge" and ("--ff-only" in args or "--abort" in args):
            return
        if current_branch(cwd) == MAIN:
            raise Blocked(
                f"git {sub} в ветке main запрещён (ORCHESTRATOR §4): merge origin/main — только в свою ветку."
            )
    elif sub == "clean":
        flags = short_flags(args)
        if "x" in flags or "X" in flags:
            raise Blocked("git clean -x/-X удаляет .env и зависимости — запрещено; удаляй конкретные пути.")


def check_docker(tokens: list[str]) -> None:
    words = [t for t in tokens[1:] if not t.startswith("-")]
    if "prune" in words:
        raise Blocked(
            "Общие очистки Docker запрещены (HANDOFF §5): удаляй только свои контейнеры и тома по префиксу "
            "(rt-itest-*, rt-erp-test-*, rt-<задача>)."
        )
    compose = tokens[0] == "docker-compose" or (len(words) > 0 and words[0] == "compose")
    if compose and "down" in words:
        volumes = "--volumes" in tokens or "v" in short_flags([t for t in tokens if t not in ("-p", "-f")])
        project = any(t in ("-p", "--project-name") or t.startswith(("--project-name=", "-p=")) for t in tokens)
        if volumes and not project:
            raise Blocked(
                "docker compose down -v без своего проекта (-p rt-<задача>) сотрёт тома общего стенда — запрещено."
            )


def check_rm(tokens: list[str], cwd: str) -> None:
    args = tokens[1:]
    recursive = "--recursive" in args or any(c in short_flags(args) for c in "rR")
    if not recursive:
        return
    home = os.path.expanduser("~")
    for a in args:
        if a.startswith("-"):
            continue
        target = resolve(cwd, a)
        if (
            a in ("*", ".", "..", "./", "../", "~", "~/", "/", "/*")
            or target in ("/", home)
            or os.path.basename(target) == ".git"
        ):
            raise Blocked(
                f"rm -r «{a}» — слишком широкая цель. Удаляй конкретные каталоги (node_modules, dist, .venv)."
            )


def is_secret_path(path: str) -> bool:
    expanded = os.path.expanduser(path)
    base = os.path.basename(expanded.rstrip("/"))
    if base.startswith(".env") and not base.endswith((".example", ".mock")):
        return True
    return "/.ssh/" in expanded + "/" or "RailTech-secrets" in expanded


def check_reader(tokens: list[str]) -> None:
    for a in tokens[1:]:
        if not a.startswith("-") and is_secret_path(a):
            raise Blocked(
                f"Вывод «{a}» целиком отправит секреты в контекст модели — запрещено. Нужен один несекретный "
                f"ключ — `grep '^ИМЯ=' .env`; шаблон — .env.example."
            )


def check(command: str, cwd: str) -> None:
    for raw in segments(command):
        tokens = strip_prefix(raw)
        if not tokens:
            continue
        name = os.path.basename(tokens[0])
        if name == "cd" and len(tokens) > 1:
            cwd = resolve(cwd, tokens[1])
        elif name == "git":
            check_git(tokens, cwd)
        elif name in ("docker", "docker-compose"):
            check_docker(tokens)
        elif name == "rm":
            check_rm(tokens, cwd)
        elif name in READERS:
            check_reader(tokens)
        elif name in SHELLS and "-c" in tokens[1:-1]:
            check(tokens[tokens.index("-c") + 1], cwd)


def main() -> int:
    try:
        data = json.load(sys.stdin)
        command = data.get("tool_input", {}).get("command") or ""
        cwd = data.get("cwd") or os.getcwd()
        check(command, cwd)
    except Blocked as e:
        print(f"Сторож команд (.claude/hooks/guard_bash.py): {e}", file=sys.stderr)
        return 2
    except Exception:  # noqa: BLE001 — сторож не должен ломать работу из-за ошибки разбора
        return 0
    return 0


def verdict(command: str, cwd: str = ".") -> tuple[bool, str]:
    """Для тестов: (заблокировано, причина)."""
    try:
        check(command, cwd)
    except Blocked as e:
        return True, str(e)
    return False, ""


if __name__ == "__main__":
    sys.exit(main())
