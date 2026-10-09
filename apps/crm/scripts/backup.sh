#!/usr/bin/env bash
# Внеочередной бэкап (ADR-0013): pg_dump + копия бакетов в том backups.
# Плановый бэкап делает сервис backup ежедневно в 03:00 Asia/Tashkent.
set -euo pipefail

usage() {
  cat <<USAGE
Использование: scripts/backup.sh [--prod] [--list]

  (без флагов)  бэкап dev-стенда
  --prod        бэкап prod-стенда (на VPS)
  --list        показать имеющиеся бэкапы
Бэкапы лежат в docker-томе railtech_backups (/backups в контейнере), хранятся 14 дней.
USAGE
}

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
overlay="infra/docker-compose.dev.yml"
action=(/app/ops/backup.sh --once)
for arg in "$@"; do
  case "$arg" in
    --prod) overlay="infra/docker-compose.prod.yml" ;;
    --list) action=(/app/ops/restore.sh --list) ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done
[[ -f "$ROOT/.env" ]] || { echo "Нет .env — сначала scripts/bootstrap_dev.sh" >&2; exit 1; }

cd "$ROOT"
docker compose -f infra/docker-compose.yml -f "$overlay" --env-file .env --profile backup \
  run --rm --no-deps backup "${action[@]}"
echo "Дальше: scripts/backup.sh --list; копию тома railtech_backups храните и вне VPS (runbook backup-restore)."
