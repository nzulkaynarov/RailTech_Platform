#!/usr/bin/env python3
"""PostToolUse(Edit|Write|MultiEdit) Claude Code: форматирует изменённый файл тем же форматтером, что проверяет CI.

Только форматирование, без автоисправлений линтера: `ruff check --fix` удалил бы импорт, добавленный раньше своего
использования. Форматтер берётся из окружения приложения (как в его Makefile) и запускается из его каталога, чтобы
читались его настройки:
- `apps/erp/backend/**.py` — black и isort из `apps/erp/.venv-tools` (`make -C apps/erp format`);
- `apps/crm/scripts/**.py` — ruff бэкенда CRM с `--config apps/crm/backend/pyproject.toml` (как pre-commit);
- прочий `.py` — `ruff format` из `.venv` ближайшего каталога с `pyproject.toml` (CRM, EDS, BFF, rt-bus, rt-docs,
  contracts);
- `.ts/.tsx/.js/.jsx/.mjs/.cjs/.css` — prettier ближайшего пакета, где `format:check` входит в lint
  (`apps/crm/frontend`, `apps/platform/web`); `.prettierignore` пакета соблюдается.
Нет окружения (не сделан `make install`) или форматтер упал на незаконченном коде — тихо выходим: проверку сделает
`make check-<приложение>`. Только stdlib, Python ≥ 3.9.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

PY = (".py",)
JS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".css")


def run(cmd: list[str], cwd: str) -> None:
    try:
        subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=25)
    except (OSError, subprocess.SubprocessError):
        pass


def git_root(path: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", os.path.dirname(path), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def ancestors(path: str, root: str) -> list[str]:
    dirs, d = [], os.path.dirname(path)
    while d.startswith(root):
        dirs.append(d)
        if d == root:
            break
        d = os.path.dirname(d)
    return dirs


def python_cmds(path: str, root: str, rel: str) -> list[tuple[list[str], str]]:
    if rel.startswith("apps/erp/backend/"):
        erp = os.path.join(root, "apps/erp")
        tools = os.path.join(erp, ".venv-tools/bin")
        if os.path.exists(os.path.join(tools, "black")):
            return [
                ([os.path.join(tools, "black"), "-q", path], erp),
                ([os.path.join(tools, "isort"), "-q", path], erp),
            ]
        return []
    if rel.startswith("apps/crm/scripts/"):
        ruff = os.path.join(root, "apps/crm/backend/.venv/bin/ruff")
        if os.path.exists(ruff):
            return [([ruff, "format", "--config", os.path.join(root, "apps/crm/backend/pyproject.toml"), path], root)]
        return []
    for d in ancestors(path, root):
        if os.path.exists(os.path.join(d, "pyproject.toml")):
            ruff = os.path.join(d, ".venv/bin/ruff")
            return [([ruff, "format", path], d)] if os.path.exists(ruff) else []
    return []


def js_cmds(path: str, root: str) -> list[tuple[list[str], str]]:
    for d in ancestors(path, root):
        pkg = os.path.join(d, "package.json")
        if not os.path.exists(pkg):
            continue
        try:
            with open(pkg, encoding="utf-8") as f:
                scripts = json.load(f).get("scripts", {})
        except (OSError, ValueError):
            return []
        prettier = os.path.join(d, "node_modules/.bin/prettier")
        if "prettier --check" in scripts.get("format:check", "") and os.path.exists(prettier):
            return [([prettier, "--write", "--ignore-unknown", "--log-level", "warn", path], d)]
        return []
    return []


def commands(path: str) -> list[tuple[list[str], str]]:
    if not path.endswith(PY + JS) or not os.path.isfile(path):
        return []
    root = git_root(path)
    if not root:
        return []
    rel = os.path.relpath(path, root).replace(os.sep, "/")
    if "/node_modules/" in f"/{rel}" or "/.venv" in f"/{rel}":
        return []
    return python_cmds(path, root, rel) if path.endswith(PY) else js_cmds(path, root)


def main() -> int:
    try:
        data = json.load(sys.stdin)
        path = data.get("tool_input", {}).get("file_path") or ""
        if not path:
            return 0
        path = os.path.realpath(os.path.join(data.get("cwd") or os.getcwd(), path))
        for cmd, cwd in commands(path):
            run(cmd, cwd)
    except Exception:  # noqa: BLE001 — форматирование не должно мешать работе
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
