#!/usr/bin/env bash
# Проверка восстановления бэкапа (VPS 2): каждый дамп разворачивается во временную базу на работающем PostgreSQL,
# проверяется число таблиц (и расширение vector для crm), база удаляется. Боевые базы не затрагиваются.
#   infra/db/restore-check.sh [каталог-бэкапа]     по умолчанию — последний в $RT_BACKUP_DIR (/var/backups/rt)
# Для зашифрованной внешней копии сначала расшифруйте файлы (команда — в шапке backup.sh) в каталог и укажите его.
set -euo pipefail

BACKUP_ROOT="${RT_BACKUP_DIR:-/var/backups/rt}"
PG_CONTAINER="${PG_CONTAINER:-rt-db-postgres-1}"
dir="${1:-}"
if [[ -z "$dir" ]]; then
  dir="$(find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -name '20*' ! -name '*.partial' | sort | tail -1)"
fi
[[ -d "$dir" ]] || { echo "restore-check: нет каталога бэкапа: ${dir:-$BACKUP_ROOT}" >&2; exit 1; }
echo "restore-check: $dir"

(cd "$dir" && sha256sum -c SHA256SUMS >/dev/null) || { echo "restore-check: SHA256SUMS не сходится" >&2; exit 1; }

psql_su() { docker exec -i -u postgres "$PG_CONTAINER" psql -v ON_ERROR_STOP=1 -U postgres -d postgres "$@"; }
failed=0
for dump in "$dir"/*.dump; do
  name="$(basename "$dump" .dump)"
  tmp="restore_check_${name}_$$"
  psql_su -c "CREATE DATABASE \"$tmp\"" >/dev/null
  # Ошибки pg_restore про роли/владельцев ожидаемы (--no-owner); считаем по содержимому.
  docker exec -i -u postgres "$PG_CONTAINER" pg_restore -U postgres -d "$tmp" --no-owner --exit-on-error < "$dump" \
    || { echo "  ✘ $name: pg_restore завершился с ошибкой"; failed=1; psql_su -c "DROP DATABASE IF EXISTS \"$tmp\"" >/dev/null; continue; }
  tables="$(psql_su -d "$tmp" -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog','information_schema')")"
  extra=""
  if [[ "$name" == crm ]]; then
    if psql_su -d "$tmp" -tAc "SELECT 1 FROM pg_extension WHERE extname='vector'" | grep -q 1; then
      extra=", vector ok"
    else
      extra=", НЕТ vector"; failed=1
    fi
  fi
  if [[ "$tables" -gt 0 ]]; then echo "  ✔ $name: таблиц $tables$extra"
  elif [[ "$name" == crm || "$name" == erp || "$name" == eds ]]; then echo "  ✘ $name: таблиц нет"; failed=1
  else echo "  ! $name: таблиц нет (служебная база ещё не использовалась?)"; fi
  psql_su -c "DROP DATABASE IF EXISTS \"$tmp\"" >/dev/null
done
if [[ $failed -eq 0 ]]; then echo "restore-check: ok"; else echo "restore-check: FAIL" >&2; exit 1; fi
