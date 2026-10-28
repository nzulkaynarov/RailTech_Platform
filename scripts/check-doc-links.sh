#!/usr/bin/env bash
# Ссылки на документацию целы и ведут в docs/ (DOCS-1, docs/ORCHESTRATOR.md §7). Логика — check_doc_links.py.
# Заодно — ID строк docs/BACKLOG.md уникальны и по формату (scripts/backlog.py --check; DECISIONS 2026-10-28):
# два PR с одной строкой B-… git сливает молча, здесь это красное.
set -euo pipefail
python3 "$(dirname "$0")/backlog.py" --check
exec python3 "$(dirname "$0")/check_doc_links.py" "$@"
