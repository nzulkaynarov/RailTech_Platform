#!/usr/bin/env bash
# Восстановление из бэкапа (ADR-0013). ⚠️ Перезаписывает БД и объекты S3.
# Перед запуском остановите api, worker и MCP (scripts/restore.sh делает это сам).
#
#   restore.sh --list            список бэкапов
#   restore.sh <штамп|latest>    проверить SHA256SUMS, pg_restore --clean, загрузить S3
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/backups}"
PG_BIN="${PG_BIN:-/usr/lib/postgresql/16/bin}"

if [[ "${1:-}" == "--list" || -z "${1:-}" ]]; then
  ls -1 "$BACKUP_DIR" | grep -E '^20[0-9]{6}T[0-9]{6}Z$' || echo "бэкапов нет в $BACKUP_DIR"
  exit 0
fi
stamp="$1"
if [[ "$stamp" == "latest" ]]; then
  stamp="$(ls -1 "$BACKUP_DIR" | grep -E '^20[0-9]{6}T[0-9]{6}Z$' | tail -n 1)"
fi
dir="$BACKUP_DIR/$stamp"
[[ -f "$dir/db.dump" ]] || { echo "нет $dir/db.dump — см. restore.sh --list" >&2; exit 1; }

echo "Проверка целостности $stamp…"
(cd "$dir" && sha256sum --check --quiet SHA256SUMS)
echo "pg_restore → $POSTGRES_DB…"
PGPASSWORD="$POSTGRES_PASSWORD" "$PG_BIN/pg_restore" -h "$POSTGRES_HOST" -p "${POSTGRES_PORT:-5432}" \
  -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --exit-on-error "$dir/db.dump"
if [[ -f "$dir/litellm.dump" ]]; then
  echo "pg_restore → litellm (модели и ключи из «Модели ИИ»; нужен тот же LITELLM_SALT_KEY)…"
  PGPASSWORD="$POSTGRES_PASSWORD" "$PG_BIN/pg_restore" -h "$POSTGRES_HOST" -p "${POSTGRES_PORT:-5432}" \
    -U "$POSTGRES_USER" -d litellm --clean --if-exists --no-owner --exit-on-error "$dir/litellm.dump"
fi
echo "S3 → RustFS…"
python -m app s3-mirror --restore "$dir/s3"
echo "Готово: восстановлен $stamp. Дальше: запустите сервисы и проверьте /ready (runbook backup-restore)."
