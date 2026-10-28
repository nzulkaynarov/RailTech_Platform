#!/usr/bin/env python3
"""Мягкая проверка актуальности помощи (W-REL): PR меняет экран, а статью о нём — нет.

У статьи `docs/kb/help/*.md` во front matter — `screens: [/crm/leads, /crm/clients]`. Адрес экрана сопоставляется с кодом
Платформы: `/crm/leads` -> `apps/platform/web/src/modules/crm/leads/` и файлы `modules/crm/Leads*`; `/me` — профиль,
`/help/...` — помощь и обращения. Если PR трогает код экрана, а статью — нет, в лог CI идёт предупреждение
(`::warning::`), а не ошибка: устарела ли статья, решает ревьюер (ORCHESTRATOR §7, DoD). Там же — напоминание о строке
«Для пользователей», если экран менялся, а в описании PR её нет (описание — из `$GITHUB_EVENT_PATH`).

    scripts/help_freshness.py [--base origin/main] [--head HEAD]

Код выхода всегда 0. Только stdlib.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELP = "docs/kb/help"
WEB = "apps/platform/web/src"
SPECIAL = {
    "me": [f"{WEB}/features/profile/", f"{WEB}/features/profile-notifications/"],
    "help": [f"{WEB}/features/help/", f"{WEB}/features/tickets/"],
}
USER_LINE = re.compile(r"^\s*(?:[-*]\s+)?(?:\*\*)?Для пользователей", re.MULTILINE | re.IGNORECASE)


def screens_of(text: str) -> list[str]:
    head = text.split("\n---", 1)[0]
    match = re.search(r"^screens:\s*\[(.*)\]\s*$", head, re.MULTILINE)
    return [s.strip() for s in match.group(1).split(",") if s.strip()] if match else []


def code_of(screen: str, path: str) -> bool:
    """Файл `path` — код экрана `screen`."""
    parts = [p for p in screen.strip("/").split("/") if p]
    if not parts:
        return False
    if parts[0] in SPECIAL:
        return any(path.startswith(prefix) for prefix in SPECIAL[parts[0]])
    module = f"{WEB}/modules/{parts[0]}/"
    if len(parts) == 1:
        return path.startswith(module)
    section = parts[1]
    if path.startswith(f"{module}{section}/"):
        return True
    name = path.removeprefix(module)
    return "/" not in name and name.lower().startswith(section.lower())


def check(changed: list[str], articles: dict[str, list[str]], pr_body: str | None) -> list[str]:
    warnings: list[str] = []
    screen_touched = False
    for article, screens in sorted(articles.items()):
        hits = sorted({s for s in screens for path in changed if code_of(s, path)})
        if not hits:
            continue
        screen_touched = True
        if article in changed:
            continue
        files = sorted({p for p in changed if any(code_of(s, p) for s in hits)})
        shown = ", ".join(files[:3]) + (" …" if len(files) > 3 else "")
        warnings.append(
            f"::warning file={article}::Экран {', '.join(hits)} изменён ({shown}), а статья помощи {article} — нет. "
            "Проверьте, не устарела ли она (ORCHESTRATOR §7, DoD); если не устарела — ничего делать не нужно."
        )
    if screen_touched and pr_body is not None and not USER_LINE.search(pr_body):
        warnings.append(
            "::warning::PR меняет экран Платформы, а в описании нет строки «Для пользователей (кому): …» — "
            "без неё изменение не попадёт в «Что нового». Если пользователи разницы не заметят, строка не нужна."
        )
    return warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args(argv)
    try:
        changed = subprocess.run(
            ["git", "-C", str(ROOT), "diff", "--name-only", f"{args.base}...{args.head}"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.split()
    except subprocess.CalledProcessError as exc:
        print(f"help-freshness: не удалось сравнить с {args.base} ({exc.stderr.strip()}) — проверка пропущена")
        return 0
    articles = {
        f"{HELP}/{p.name}": screens_of(p.read_text(encoding="utf-8"))
        for p in sorted((ROOT / HELP).glob("*.md"))
    }
    body: str | None = None
    event = os.environ.get("GITHUB_EVENT_PATH")
    if event and Path(event).is_file():
        payload = json.loads(Path(event).read_text(encoding="utf-8"))
        body = (payload.get("pull_request") or {}).get("body") or ("" if "pull_request" in payload else None)
    warnings = check(changed, articles, body)
    for line in warnings:
        print(line)
    print(f"help-freshness: файлов в PR {len(changed)}, предупреждений {len(warnings)} (не ошибка)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
