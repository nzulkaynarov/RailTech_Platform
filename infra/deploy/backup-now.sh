#!/usr/bin/env bash
# Внеочередной бэкап на VPS 2 (контейнер `backup` проекта rt-db): дамп всех баз, проверка, выгрузка в RustFS.
#   backup-now.sh [--ext]      --ext: заодно выгрузить зашифрованную копию во внешнее хранилище (вне расписания)
# Запускать на VPS 2 из каталога infra этого репозитория (рядом с .env.db в $RT_DB_DIR, по умолчанию /opt/rt-db).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RT_DB_DIR="${RT_DB_DIR:-/opt/rt-db}"
force=0
[[ "${1:-}" == "--ext" ]] && force=1

docker compose -f "$here/../compose/db.yml" --env-file "$RT_DB_DIR/.env.db" \
  exec -T -e "FORCE_EXT=$force" backup /usr/local/bin/backup.sh --once
echo "backup-now: готово; проверка восстановления — infra/db/restore-check.sh"
