"""Проверка ссылок на документацию (DOCS-1): вся документация — в docs/, в коде только указатели.

1. Относительные ссылки Markdown `[текст](путь)` во всех *.md ведут на существующий файл или каталог.
2. Упоминания путей `docs/…`, `apps/…`, `packages/…`, `infra/…`, оканчивающиеся на `.md`, — в любом
   отслеживаемом текстовом файле — существуют (путь от корня репозитория).
3. Нет устаревших путей: документы внутри apps/*/docs (кроме сгенерированного apps/crm/docs/api),
   apps/platform/docs, ORCHESTRATOR.md в корне, docs/{ARCHITECTURE,MIGRATION-MAP,BUSINESS,CONTRACTS}.md,
   packages/contracts/sso-token.md, ссылки «CLAUDE.md §N» (правила кода — в docs/systems/<x>/CONVENTIONS.md).

Запуск: scripts/check-doc-links.sh (из корня). Код возврата 1 — есть битые ссылки.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

ROOT = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                      check=True).stdout.strip()
os.chdir(ROOT)

SKIP_PREFIX = ("apps/crm/frontend/src/generated/kb-docs/", "docs/screens/")
TEXT_EXT = (".md", ".py", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".sh", ".yml", ".yaml", ".toml", ".json",
            ".css", ".ini", ".cfg", ".example", ".html", ".txt", "Makefile", "Dockerfile", "Caddyfile")
# История и исследования цитируют пути того времени — в них проверяются только ссылки Markdown.
HISTORY = ("docs/history/", "docs/research/", "docs/audits/")

STALE = [
    (re.compile(r"(?<![\w/.\-])apps/(?:crm|erp|cabinet|platform)/docs/(?!api(?:/|\b))[\w.\-]"),
     "документы приложений переехали в docs/ (docs/systems, docs/adr/crm, docs/runbooks/<x>)"),
    (re.compile(r"(?<![\w/.\-])apps/platform/docs\b"), "apps/platform/docs → docs/architecture, docs/product"),
    (re.compile(r"(?<![\w/.\-])ORCHESTRATOR\.md"), "ORCHESTRATOR.md → docs/ORCHESTRATOR.md"),
    (re.compile(r"(?<![\w/.\-])docs/(?:ARCHITECTURE|MIGRATION-MAP|BUSINESS|CONTRACTS)\.md"),
     "→ docs/product, docs/architecture или docs/history"),
    (re.compile(r"(?<![\w/.\-])packages/contracts/sso-token\.md"), "→ docs/architecture/sso-token.md"),
    (re.compile(r"(?<![\w/.\-])(?:apps/\w+/)?CLAUDE\.md\s*(?:(?:Cabinet|ERP|CRM|Платформы)\s*)?§"),
     "разделы правил — docs/systems/<x>/CONVENTIONS.md §N"),
    (re.compile(r"(?<![\w/.\-])0[1-6]-(?:transformation|architecture|frontend|integration-map|plan|questions)\.md"),
     "документы Платформы переименованы (docs/architecture, docs/history/platform)"),
]
LINK = re.compile(r"\]\(([^)\s]+)\)|^\[[^\]]+\]:\s+(\S+)", re.M)
MENTION = re.compile(r"(?<![\w/.\-@:])((?:docs|apps|packages|infra)/[\w./\-]*?[\w\-]\.md)(?![\w\-])")
CODE_FENCE = re.compile(r"```.*?```", re.S)


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout.splitlines()
    return [f for f in out if not f.startswith(SKIP_PREFIX) and f.endswith(TEXT_EXT) and os.path.isfile(f)]


def main() -> int:
    errors: list[str] = []
    for path in tracked():
        try:
            text = open(path, encoding="utf-8").read()
        except UnicodeDecodeError:
            continue
        lines = text.splitlines()

        def lineno(pos: int) -> int:
            return text.count("\n", 0, pos) + 1

        if path.endswith(".md"):
            body = CODE_FENCE.sub(lambda m: "\n" * m.group(0).count("\n"), text)
            for m in LINK.finditer(body):
                target = m.group(1) or m.group(2)
                if re.match(r"^[a-zA-Z][\w+.\-]*:|^#|^<|^/", target):
                    continue
                p = target.split("#", 1)[0].split("?", 1)[0]
                if not p or set(p) <= {"."}:
                    continue
                full = os.path.normpath(os.path.join(os.path.dirname(path), p))
                if not os.path.exists(full):
                    errors.append(f"{path}:{lineno(m.start())}: битая ссылка ({target})")
        if path.startswith(HISTORY) or path.startswith("docs/PROGRESS.md") or path == "scripts/check_doc_links.py":
            continue
        for rx, hint in STALE:
            for m in rx.finditer(text):
                errors.append(f"{path}:{lineno(m.start())}: устаревший путь «{m.group(0)}» — {hint}")
        # runbook волны называет файлы, которые создадут её задачи, — их наличие не проверяется
        if re.match(r"docs/runbooks/wave\d", path):
            continue
        for m in MENTION.finditer(text):
            p = m.group(1)
            if "<" in p or "*" in p or "NNNN" in p:
                continue
            if not os.path.exists(p):
                errors.append(f"{path}:{lineno(m.start())}: нет файла {p}")
    for e in errors:
        print(e)
    if errors:
        print(f"\ncheck-doc-links: {len(errors)} проблем(ы). Документация — только в docs/ (docs/README.md).")
        return 1
    print("check-doc-links: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
