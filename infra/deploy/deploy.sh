#!/usr/bin/env bash
# Деплой на VPS 1 (запускается на сервере из каталога релиза; deploy.yml кладёт его туда и вызывает по SSH,
# вручную — так же: /opt/rt/releases/<тег>/infra/deploy/deploy.sh <тег>).
# Порядок: проверка env → pull образов → проверка базы CPU образов → pg_dump-гейт баз crm, erp и eds → миграции CRM, ERP и EDS → up → state → smoke.
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
# Домен Платформы (INF-P0-5): без него Caddy не получит сертификат, а compose упал бы на `:?` уже при разборе конфигурации.
require_env_var PLATFORM_DOMAIN "добавьте строку PLATFORM_DOMAIN=platform.railtech.uz (см. infra/.env.prod.example; A-запись домена на VPS 1 должна уже быть) и запустите деплой снова"
# Схемы событий и подписки шины rt_bus вшиты в образ ERP (/opt/rt/contracts, B3, L14): файлов контрактов в релизе
# больше не требуется (общий файл схемы событий снят вместе с вебхуками ERP → CRM).
export RT_IMAGE_TAG="$tag"
prev="$(state_get current_tag)"

log "тег $tag, релиз $rel, предыдущий: ${prev:-нет}"
compose "$rel" config -q

log "pull образов"
# Сбой сети к ghcr.io плавающий (TLS handshake timeout): до пяти попыток с паузами 5/10/20/40 с, затем прежнее поведение — ошибка (set -e).
retry "pull образов" compose "$rel" pull crm-api crm-web erp-backend erp-web cabinet-web litellm platform-bff platform-web eds-api

# Прод-CPU — база x86-64 v1 (servers.md): образ, которому нужен v2, ловим здесь, до дампа и миграций.
log "проверка базы CPU образов (cpu-baseline-check.sh)"
"$rel/infra/deploy/cpu-baseline-check.sh" "$rel" "$tag"

log "pg_dump-гейт (crm, erp, eds)"
"$rel/infra/deploy/predeploy-dump.sh" "$tag"

log "миграции (после гейта)"
compose "$rel" run --rm --no-deps crm-migrate
compose "$rel" run --rm --no-deps erp-backend python manage.py migrate --noinput
# EDS (волна 12): база `eds` и роль eds_app на VPS 2 создаются db-up.sh (docs/runbooks/deploy.md, «EDS на проде»); миграции — Alembic.
compose "$rel" run --rm --no-deps eds-migrate

log "up (сначала CRM, ERP, EDS, Cabinet и Caddy, затем Платформа: её сбой не должен останавливать остальное — INF-P1-0)"
up_stack "$rel"

if [[ "$prev" != "$tag" ]]; then
  [[ -n "$prev" ]] && state_set previous_tag "$prev"
  state_set current_tag "$tag"
fi
ln -sfn "$rel" "$RT_ROOT/current"

log "smoke на сервере (по IP 127.0.0.1; сертификат при первом запуске может ещё выпускаться)"
"$rel/infra/deploy/smoke.sh" --domains "$(env_get CRM_DOMAIN)" "$(env_get ERP_DOMAIN)" "$(env_get CABINET_DOMAIN)" "$(env_get PLATFORM_DOMAIN)" \
  --resolve-ip 127.0.0.1 --insecure --retries 30 \
  || die "smoke не прошёл (четыре домена; при сбое только Платформы CRM, ERP и Cabinet уже работают): смотрите 'docker compose logs', откат кода — rollback.sh"

# EDS не имеет домена (внешнего маршрута нет), поэтому smoke его не видит: здоровье — по healthcheck контейнера.
for svc in eds-api eds-worker; do
  wait_healthy "$rel" "$svc" 120 || die "$svc не стал healthy за 120 с: 'docker compose logs eds-api eds-worker'; остальные сервисы уже работают, откат кода — rollback.sh"
done

cleanup_old "$tag" "$(state_get previous_tag)"
log "деплой $tag завершён"
