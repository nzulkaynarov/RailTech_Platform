#!/usr/bin/env bash
# Ссылки на документацию целы и ведут в docs/ (DOCS-1, docs/ORCHESTRATOR.md §7). Логика — check_doc_links.py.
set -euo pipefail
exec python3 "$(dirname "$0")/check_doc_links.py" "$@"
