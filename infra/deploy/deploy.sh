#!/usr/bin/env bash
# Деплой на VPS 1 (запускается на сервере из каталога релиза; deploy.yml кладёт его туда и вызывает по SSH,
# вручную — так же: /opt/rt/releases/<тег>/infra/deploy/deploy.sh <тег>).
# Порядок: проверка env → pull образов → pg_dump-гейт обеих баз → миграции CRM и ERP → up → state → smoke.
# Нет дампа — нет миграций: при сбое pg_dump скрипт останавливается до первой миграции, сервисы не трогаются.
# Откат кода — rollback.sh; откат данных — восстановление из дампа (docs/runbooks/deploy.md), автоматически не делается.
set -euo pipefail
# shellcheck source=infra/deploy/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

tag="${1:?usage: deploy.sh <тег-образов>}"
[[ "$tag" =~ ^[A-Za-z0-9_.-]+$ ]] || die "недопустимый тег: $tag"
rel="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
[[ "$(basename "$rel")" == "$tag" ]] || log "внимание: каталог релиза ($(basename "$rel")) не совпадает с тегом образов ($tag)"

require_env_file
export RT_IMAGE_TAG="$tag"
prev="$(state_get current_tag)"

log "тег $tag, релиз $rel, предыдущий: ${prev:-нет}"
compose "$rel" config -q

log "pull образов"
compose "$rel" pull crm-api crm-web erp-backend erp-web cabinet-web

log "pg_dump-гейт (crm, erp)"
"$rel/infra/deploy/predeploy-dump.sh" "$tag"

log "миграции (после гейта)"
compose "$rel" run --rm --no-deps crm-migrate
compose "$rel" run --rm --no-deps erp-backend python manage.py migrate --noinput

log "up"
compose "$rel" up -d --remove-orphans

if [[ "$prev" != "$tag" ]]; then
  [[ -n "$prev" ]] && state_set previous_tag "$prev"
  state_set current_tag "$tag"
fi
ln -sfn "$rel" "$RT_ROOT/current"

log "smoke на сервере (по IP 127.0.0.1; сертификат при первом запуске может ещё выпускаться)"
"$rel/infra/deploy/smoke.sh" --domains "$(env_get CRM_DOMAIN)" "$(env_get ERP_DOMAIN)" "$(env_get CABINET_DOMAIN)" \
  --resolve-ip 127.0.0.1 --insecure --retries 30 \
  || die "smoke не прошёл: смотрите 'docker compose logs', откат кода — rollback.sh"

cleanup_old "$tag" "$(state_get previous_tag)"
log "деплой $tag завершён"
