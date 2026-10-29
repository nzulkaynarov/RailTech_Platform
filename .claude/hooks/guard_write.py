#!/usr/bin/env python3
"""PreToolUse(Write) Claude Code: новый `.md` вне `docs/` не создаётся (ORCHESTRATOR §3 п. 17).

Исключения — то, что читают код и генераторы, и указатели (docs/README.md, «Что не документация»): `CLAUDE.md`,
`README.md`, `GEMINI.md`, `AGENTS.md`, `SKILL.md`, всё под `.claude/` и `.github/`, каталоги `prompts/`, `templates/`,
`fixtures/`, `generated/`. Правка существующего файла не проверяется. Выход 2 — запись отменена, причину видит агент;
ошибка разбора — выход 0. Только stdlib, Python ≥ 3.9.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

POINTERS = {"CLAUDE.md", "README.md", "GEMINI.md", "AGENTS.md", "SKILL.md"}
CODE_DIRS = (".claude", ".github", "prompts", "templates", "fixtures", "generated")


def repo_root(path: str) -> str | None:
    d = os.path.dirname(path)
    while d and not os.path.isdir(d):
        d = os.path.dirname(d)
    try:
        out = subprocess.run(
            ["git", "-C", d or ".", "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=3
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def allowed(rel: str) -> bool:
    parts = rel.split("/")
    return parts[0] == "docs" or parts[-1] in POINTERS or any(p in CODE_DIRS for p in parts[:-1])


def check(path: str) -> str | None:
    """Причина отказа или None."""
    if not path.lower().endswith(".md") or os.path.exists(path):
        return None
    root = repo_root(path)
    if not root:
        return None
    rel = os.path.relpath(os.path.realpath(path), os.path.realpath(root)).replace(os.sep, "/")
    if rel.startswith("..") or allowed(rel):
        return None
    return (
        f"Новый «{rel}» вне docs/: документация — только в docs/ (ORCHESTRATOR §3 п. 17, карта — docs/README.md). "
        f"Положи документ в docs/<раздел>/ и добавь строку в таблицу docs/README.md, если это новая тема."
    )


def main() -> int:
    try:
        data = json.load(sys.stdin)
        path = data.get("tool_input", {}).get("file_path") or ""
        cwd = data.get("cwd") or os.getcwd()
        reason = check(os.path.join(cwd, path)) if path else None
    except Exception:  # noqa: BLE001
        return 0
    if reason:
        print(f"Сторож записи (.claude/hooks/guard_write.py): {reason}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
