#!/usr/bin/env bash
# Детерминированные проверки архитектурных инвариантов бэкенда RailTech.
# Печатает находки в формате "FILE:LINE  сообщение"; всегда выходит с кодом 0 —
# интерпретация (реальное нарушение или допустимое исключение) — за ревьюером.
set -uo pipefail

cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

if ! command -v rg >/dev/null 2>&1; then
  echo "ERROR: ripgrep (rg) не найден — brew install ripgrep" >&2
  exit 1
fi

B=backend
# Исключения: миграции, тесты, management-команды — там свои правила
X=(--glob '!**/migrations/**' --glob '!**/tests/**' --glob '!**/test_*.py' --glob '!**/conftest.py' --glob '!**/management/**')

section() { echo; echo "== $1 =="; }
found=0
run() { # run <заголовок> <rg-args...>
  local title="$1"; shift
  local out
  out=$(rg -n --no-heading "$@" 2>/dev/null)
  if [ -n "$out" ]; then
    section "$title"
    echo "$out"
    found=1
  fi
}

# 1. Rule 8: ORM-записи в views/admin — бизнес-логика обязана жить в services.
#    serializer.save() в perform_create/perform_update — DRF-идиома, не флагуем.
R8=$(rg -n --no-heading "${X[@]}" \
  -e '\.save\(' -e 'objects\.create\(' -e '\.delete\(' -e 'bulk_create\(' -e 'bulk_update\(' \
  "$B"/*/views "$B"/*/views.py "$B"/*/admin.py "$B"/*/admin 2>/dev/null \
  | grep -Ev 'serializer\.save\(|wb\.save\(')
if [ -n "$R8" ]; then
  section "Rule 8 ПОДОЗРЕНИЕ: ORM-запись в views/ или admin (логика должна быть в services)"
  echo "$R8"
  found=1
fi

# 2. Error shape: только {"detail": "<CODE>"}, никогда {"error": ...}.
#    sourcing/tasks_ai.py — задокументированное исключение (результаты Celery-джоб, не HTTP).
run 'Error shape: найден {"error": ...} — должен быть {"detail": "<CODE>"}' \
  "${X[@]}" --glob '!**/sourcing/tasks_ai.py' -e '"error":' -e "'error':" "$B" 2>/dev/null

# 3. Bare except Exception — запрещено конвенциями
run "Широкий except Exception (нужны конкретные исключения)" \
  "${X[@]}" -e 'except Exception' "$B" 2>/dev/null

# 4. Rule 1: get_or_create по code в горячем пути (seed = data migrations)
run "Rule 1 ПОДОЗРЕНИЕ: get_or_create вне миграций (lookup-коды создаёт только миграция)" \
  "${X[@]}" -e 'get_or_create\(' "$B" 2>/dev/null

# 5. AI: клиент Anthropic только через фабрику _client() в sourcing/services_ai.py
run "AI: инстанс Anthropic вне sourcing/services_ai.py (единая фабрика _client())" \
  "${X[@]}" --glob '!**/sourcing/services_ai.py' -e 'anthropic\.Anthropic' -e 'from anthropic import' "$B" 2>/dev/null

# 6. print() в продакшн-коде — используем logging
run "print() в бэкенд-коде (использовать logging)" \
  "${X[@]}" -e '^\s*print\(' "$B" 2>/dev/null

# 7. Celery: задачи без time_limit (конвенция: time_limit=600, soft_time_limit=540)
CELERY_OUT=$(python3 - <<'PY'
import pathlib, re
root = pathlib.Path("backend")
skip = ("migrations", "tests", "management")
for path in sorted(root.rglob("tasks*.py")):
    if any(part in skip or part.startswith("test_") for part in path.parts):
        continue
    src = path.read_text(encoding="utf-8", errors="replace")
    for match in re.finditer(r"@shared_task\s*(\(([^)]*)\))?\s*\ndef\s+(\w+)", src):
        args = match.group(2) or ""
        name = match.group(3)
        line = src[: match.start()].count("\n") + 1
        if "time_limit" not in args:
            print(f"{path}:{line}  задача {name} без time_limit/soft_time_limit")
PY
)
if [ -n "$CELERY_OUT" ]; then
  section "Celery: задачи без time_limit"
  echo "$CELERY_OUT"
  found=1
fi

# 8. Транзакции вокруг многомодельных записей: transaction.atomic импортирован, но send/dispatch внутри?
#    (только маркер для ручной проверки on_commit — грепом надёжно не поймать)

echo
if [ "$found" -eq 0 ]; then
  echo "OK: скриптовые проверки нарушений не нашли."
else
  echo "ГОТОВО: выше — кандидаты в нарушения. Каждый требует вердикта ревьюера (допустимые исключения существуют)."
fi
exit 0
