#!/usr/bin/env bash
# Ссылки на документацию целы и ведут в docs/ (DOCS-1, docs/ORCHESTRATOR.md §3 п. 17) и управляющие документы не размылись:
# «Курс» не длиннее 45 строк, «Список» и «Не сейчас» есть, второго файла-очереди в docs/ нет (КУРС-1, DECISIONS 2026-11-27).
# Логика — check_doc_links.py.
set -euo pipefail
exec python3 "$(dirname "$0")/check_doc_links.py" "$@"
