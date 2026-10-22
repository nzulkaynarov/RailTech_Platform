#!/usr/bin/env bash
# Откат кода на VPS 1 к предыдущему тегу (или к указанному): образы и конфигурация compose того релиза.
# Миграции БД НЕ откатываются и дамп не восстанавливается — это отдельное решение (docs/runbooks/deploy.md,
# «Восстановление из бэкапа»); откат кода безопасен, пока миграции предыдущего релиза обратно совместимы.
#   rollback.sh [тег]
set -euo pipefail
# shellcheck source=infra/deploy/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

cur="$(state_get current_tag)"
target="${1:-$(state_get previous_tag)}"
[[ -n "$target" ]] || die "нет предыдущего тега для отката (state/previous_tag пуст) — укажите тег: rollback.sh <тег>"
[[ "$target" =~ ^[A-Za-z0-9_.-]+$ ]] || die "недопустимый тег: $target"
[[ "$target" != "$cur" ]] || die "тег $target уже текущий"
rel="$(release_dir "$target")"
[[ -d "$rel/infra/compose" ]] || die "каталог релиза $rel не найден (хранятся последние пять релизов)"

require_env_file
export RT_IMAGE_TAG="$target"
log "откат $cur → $target"
compose "$rel" config -q
# Платформа (INF-P0-5) есть не в каждом релизе: откат на тег до неё не должен просить у compose несуществующие сервисы.
pull_services=(crm-api crm-web erp-backend erp-web cabinet-web)
smoke_domains=("$(env_get CRM_DOMAIN)" "$(env_get ERP_DOMAIN)" "$(env_get CABINET_DOMAIN)")
services="$(compose "$rel" config --services)"
if grep -qx platform-bff <<<"$services"; then
  pull_services+=(platform-bff platform-web)
  smoke_domains+=("$(env_get PLATFORM_DOMAIN)")
fi
compose "$rel" pull "${pull_services[@]}" || log "pull не удался — используются локальные образы"
up_stack "$rel"

state_set previous_tag "$cur"
state_set current_tag "$target"
ln -sfn "$rel" "$RT_ROOT/current"

"$rel/infra/deploy/smoke.sh" --domains "${smoke_domains[@]}" \
  --resolve-ip 127.0.0.1 --insecure --retries 30 \
  || die "smoke после отката не прошёл — смотрите docker compose logs"
log "откат на $target завершён (миграции БД не откатывались)"
