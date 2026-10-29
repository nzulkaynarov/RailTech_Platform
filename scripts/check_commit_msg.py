#!/usr/bin/env python3
"""Хук commit-msg (pre-commit): сообщение коммита агента — по ORCHESTRATOR §4 «Трейлер в каждом коммите».

Проверяется только коммит агента — в его оболочке есть `CLAUDECODE=1` (Claude Code) или `GEMINI_CLI=1` (Gemini CLI);
`RT_COMMIT_CHECK=1` включает проверку вручную. Коммиты человека не проверяются.
- ошибка: первая строка не в Conventional Commits (`тип(область): …`; типы через запятую и `wip` — как в истории);
- ошибка: нет трейлера `Co-Authored-By: <модель> <адрес>` — по нему `git log` отвечает «кто что сделал» (аудит G-13);
- предупреждение: нет суффикса задачи `(ID)` в конце первой строки.
Merge, Revert, fixup!/squash!/amend! пропускаются.

    scripts/check_commit_msg.py <файл сообщения>

Только stdlib.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

TYPES = "feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert|wip"
SUBJECT = re.compile(rf"^(?:{TYPES})(?:,(?:{TYPES}))*(?:\([^()]+\))?!?: \S")
TASK_SUFFIX = re.compile(r"\([A-Za-z0-9][\w.\-]*(?:[ ,;/]+[\w.\-]+)*\)$")
TRAILER = re.compile(r"^Co-Authored-By: .+ <[^<>@\s]+@[^<>\s]+>\s*$", re.I | re.M)
SKIP = ("Merge ", "Revert ", "fixup! ", "squash! ", "amend! ")
SCISSORS = "# ------------------------ >8 ------------------------"


def is_agent() -> bool:
    return any(os.environ.get(v) == "1" for v in ("CLAUDECODE", "GEMINI_CLI", "RT_COMMIT_CHECK"))


def clean(message: str) -> str:
    message = message.split(SCISSORS, 1)[0]
    return "\n".join(line for line in message.splitlines() if not line.startswith("#")).strip()


def check(message: str) -> tuple[list[str], list[str]]:
    """(ошибки, предупреждения)."""
    message = clean(message)
    subject = message.splitlines()[0] if message else ""
    if not subject or subject.startswith(SKIP):
        return [], []
    errors, warnings = [], []
    if not SUBJECT.match(subject):
        errors.append(
            f"первая строка не в Conventional Commits («тип(область): что сделано (ID)», типы: {TYPES}): «{subject}»"
        )
    if not TRAILER.search(message):
        errors.append("нет трейлера «Co-Authored-By: <модель> <noreply@…>» в конце сообщения")
    if not TASK_SUFFIX.search(subject):
        warnings.append("в конце первой строки нет задачи в скобках, например «… (W-AGENT1)»")
    return errors, warnings


def main(argv: list[str]) -> int:
    if len(argv) < 2 or not is_agent():
        return 0
    errors, warnings = check(Path(argv[1]).read_text(encoding="utf-8"))
    for w in warnings:
        print(f"commit-msg: предупреждение — {w}", file=sys.stderr)
    for e in errors:
        print(f"commit-msg: {e} (ORCHESTRATOR §4, «Трейлер в каждом коммите»)", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
