#!/usr/bin/env bash
# Выкладка prod на VPS (PLAN Фаза 8; вызывает deploy-prod.yml по ssh, можно и вручную).
# Шаги: бэкап → checkout тега → IMAGE_TAG в .env → pull + up (migrate внутри) → smoke.
# Smoke провален → откат на предыдущие тег и образы, повторный smoke, код выхода 1.
set -euo pipefail

usage() {
  cat <<USAGE
Использование: scripts/deploy.sh <git-тег> <IMAGE_TAG> [--no-backup]

  <git-тег>     ревизия репозитория (compose, Caddyfile, скрипты), например v1.2.0
  <IMAGE_TAG>   тег образов в GHCR (git sha коммита тега)
  --no-backup   не делать бэкап перед выкладкой (не рекомендуется)
Запускать в каталоге репозитория на VPS (там же .env). Откат вручную:
  scripts/deploy.sh <предыдущий-тег> <его sha>   — см. docs/runbooks/crm/deploy.md
USAGE
}
[[ "${1:-}" == "-h" || "${1:-}" == "--help" || $# -lt 2 ]] && { usage; exit 0; }

# git checkout ниже заменит этот файл, а bash читает скрипт по ходу выполнения —
# поэтому выполняемся из временной копии.
if [[ -z "${DEPLOY_ROOT:-}" ]]; then
  DEPLOY_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
  copy="$(mktemp)"
  cp "$0" "$copy"
  DEPLOY_ROOT="$DEPLOY_ROOT" exec bash "$copy" "$@"
fi
cd "$DEPLOY_ROOT"
ref="$1"; image_tag="$2"; backup=1
[[ "${3:-}" == "--no-backup" ]] && backup=0
[[ -f .env ]] || { echo "Нет .env на сервере (runbook deploy.md, шаг «первичная настройка»)" >&2; exit 1; }

current_env() { grep -E "^$1=" .env | tail -n 1 | cut -d= -f2-; }
set_env() {
  if grep -qE "^$1=" .env; then sed -i "s|^$1=.*|$1=$2|" .env; else echo "$1=$2" >> .env; fi
}
apply() {
  git fetch --tags --force --quiet origin
  git checkout --quiet --force "$1"
  set_env IMAGE_TAG "$2"
  make up-prod
}

prev_ref="$(git describe --tags --exact-match 2>/dev/null || git rev-parse HEAD)"
prev_tag="$(current_env IMAGE_TAG)"
echo "Текущее: $prev_ref / $prev_tag → новое: $ref / $image_tag"

if [[ "$backup" == 1 && -n "$prev_tag" ]]; then
  scripts/backup.sh --prod
fi

if apply "$ref" "$image_tag" && scripts/smoke_prod.sh; then
  echo "DEPLOY_OK $ref $image_tag"
  docker image prune -f --filter "until=168h" > /dev/null || true
  exit 0
fi

echo "⚠️ Выкладка $ref не прошла smoke — откат на $prev_ref / $prev_tag" >&2
if [[ -n "$prev_tag" ]]; then
  apply "$prev_ref" "$prev_tag" && scripts/smoke_prod.sh || echo "Откат тоже не прошёл smoke — нужен человек (runbook deploy.md)" >&2
fi
echo "Миграции БД не откатываются автоматически: схема должна быть обратно совместима (runbook deploy.md)." >&2
exit 1
