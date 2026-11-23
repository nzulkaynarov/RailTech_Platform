#!/usr/bin/env bash
# Тест scripts/maintenance-notice.sh: set/clear/show во временном каталоге. Запуск: bash scripts/tests/maintenance-notice-test.sh
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
script="$here/../maintenance-notice.sh"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
export MAINTENANCE_DIR="$tmp/m"
fail() { echo "FAIL: $*"; exit 1; }

# 12:00 по Ташкенту = 07:00 UTC; 19:15 ещё впереди - сегодня
MAINTENANCE_NOW="2026-11-23T07:00:00Z" bash "$script" set 19:15 >/dev/null
[[ "$(cat "$MAINTENANCE_DIR/maintenance.json")" == '{"starts_at":"2026-11-23T19:15:00+05:00","minutes":3,"kind":"planned"}' ]] \
  || fail "set 19:15: $(cat "$MAINTENANCE_DIR/maintenance.json")"
python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$MAINTENANCE_DIR/maintenance.json" || fail "не JSON"

# время прошло (21:00 по Ташкенту, 19:15 уже было) - завтра; минуты и kind
MAINTENANCE_NOW="2026-11-23T16:00:00Z" bash "$script" set 19:15 5 urgent >/dev/null
[[ "$(cat "$MAINTENANCE_DIR/maintenance.json")" == '{"starts_at":"2026-11-24T19:15:00+05:00","minutes":5,"kind":"urgent"}' ]] \
  || fail "set завтра: $(cat "$MAINTENANCE_DIR/maintenance.json")"

# без временных файлов, права читаемы
ls -A "$MAINTENANCE_DIR" | grep -qx maintenance.json && [[ "$(ls -A "$MAINTENANCE_DIR" | wc -l)" == 1 ]] || fail "остались временные файлы"
[[ "$(stat -c %a "$MAINTENANCE_DIR/maintenance.json")" == 644 ]] || fail "права не 644"

bash "$script" show | grep -q starts_at || fail "show"

# плохие входы не трогают файл
before="$(cat "$MAINTENANCE_DIR/maintenance.json")"
for args in "set 25:00" "set 19:15 0" "set 19:15 3 weird" "set abc" "nope"; do
  # shellcheck disable=SC2086
  if bash "$script" $args >/dev/null 2>&1; then fail "'$args' должен падать"; fi
done
[[ "$(cat "$MAINTENANCE_DIR/maintenance.json")" == "$before" ]] || fail "плохой вход изменил файл"

bash "$script" clear >/dev/null
[[ ! -e "$MAINTENANCE_DIR/maintenance.json" ]] || fail "clear не удалил файл"
bash "$script" clear >/dev/null || fail "повторный clear должен проходить"
echo "maintenance-notice-test: ok"
