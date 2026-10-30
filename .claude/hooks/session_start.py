#!/usr/bin/env python3
"""SessionStart Claude Code: короткая проверка рабочего места в начале сессии.

Пишет в контекст сессии только найденные проблемы (всё в порядке — ничего): версия uv не та, что в CI; не установлены
git-хуки (`make hooks`: gitleaks, запрет коммита в main, сообщение коммита); не запущен Docker (`ci_local.sh`, тесты
ERP и EDS); в облачной сессии — не авторизован `gh`. Каждая проверка — с таймаутом, ошибка проверки молчит.
Только stdlib, Python ≥ 3.9. Подробно — docs/systems/infra/claude-code.md §5.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

ROOT = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def out(cmd: list[str], timeout: float = 5) -> str | None:
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def uv_problem() -> str | None:
    try:
        with open(os.path.join(ROOT, ".github/workflows/ci.yml"), encoding="utf-8") as f:
            m = re.search(r'UV_VERSION:\s*"([0-9.]+)"', f.read())
    except OSError:
        return None
    if not m:
        return None
    want = m.group(1)
    have = out(["uv", "--version"])
    if have is None:
        return f"uv не найден; CI — uv {want}: curl -LsSf https://astral.sh/uv/{want}/install.sh | sh"
    if want not in have.split():
        return f"{have}, а CI и Dockerfile — uv {want}: uv self update {want} (или установщик с astral.sh)"
    return None


def hooks_problem() -> str | None:
    hooks = out(["git", "rev-parse", "--path-format=absolute", "--git-path", "hooks"])
    if hooks is None:
        return None
    missing = [h for h in ("pre-commit", "commit-msg") if not os.path.exists(os.path.join(hooks, h))]
    if missing:
        return f"нет git-хуков {', '.join(missing)} (gitleaks, запрет коммита в main, сообщение коммита): make hooks"
    return None


def docker_problem() -> str | None:
    if out(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=8) is None:
        return "Docker не отвечает: ci_local.sh, тесты ERP, EDS и rt-bus не пойдут — запусти Docker Desktop"
    return None


def gh_problem() -> str | None:
    if os.environ.get("CLAUDE_CODE_REMOTE") != "true":
        return None
    if out(["gh", "auth", "status"], timeout=8) is None:
        return "gh не авторизован в облачной сессии: PR и статус CI — через GitHub MCP (mcp__github__*)"
    return None


def main() -> int:
    problems = [p for p in (uv_problem(), hooks_problem(), docker_problem(), gh_problem()) if p]
    if problems:
        print("Проверка рабочего места (.claude/hooks/session_start.py):")
        for p in problems:
            print(f"- {p}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        sys.exit(0)
