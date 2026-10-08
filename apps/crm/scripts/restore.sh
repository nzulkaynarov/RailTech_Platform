#!/usr/bin/env bash
# Восстановление из бэкапа (ADR-0013). ⚠️ Перезаписывает БД и файлы S3 стенда.
set -euo pipefail

usage() {
  cat <<USAGE
Использование: scripts/restore.sh [--prod] [--yes] <штамп|latest>

  <штамп>   имя бэкапа из scripts/backup.sh --list (например 20261008T220000Z)
  latest    последний бэкап
  --prod    восстановить prod (по умолчанию dev)
  --yes     не спрашивать подтверждение
Останавливает api/worker/MCP, восстанавливает БД и S3, запускает сервисы, проверяет /ready.
USAGE
}

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
overlay="infra/docker-compose.dev.yml"; smoke="scripts/smoke_dev.sh"; stamp=""; yes=0
for arg in "$@"; do
  case "$arg" in
    --prod) overlay="infra/docker-compose.prod.yml"; smoke="scripts/smoke_prod.sh" ;;
    --yes) yes=1 ;;
    -h|--help) usage; exit 0 ;;
    *) stamp="$arg" ;;
  esac
done
[[ -n "$stamp" ]] || { usage >&2; exit 2; }
[[ -f "$ROOT/.env" ]] || { echo "Нет .env" >&2; exit 1; }
cd "$ROOT"
compose=(docker compose -f infra/docker-compose.yml -f "$overlay" --env-file .env --profile backup)

if [[ "$yes" != 1 ]]; then
  read -r -p "Перезаписать БД и S3 стенда ($overlay) бэкапом $stamp? [yes/N] " answer
  [[ "$answer" == "yes" ]] || { echo "Отменено"; exit 1; }
fi
app_services=(api worker kb-mcp crm-mcp docs-mcp)
"${compose[@]}" stop "${app_services[@]}"
trap 'echo "Ошибка восстановления. Сервисы остановлены; смотрите вывод выше и runbook backup-restore." >&2' ERR
"${compose[@]}" run --rm --no-deps backup /app/ops/restore.sh "$stamp"
"${compose[@]}" up -d "${app_services[@]}"
trap - ERR
"$smoke"
echo "Восстановление $stamp завершено."
