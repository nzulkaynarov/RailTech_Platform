#!/usr/bin/env bash
# Тест S0-4: бот Telegram — отдельный процесс crm-bot, а не часть crm-api.
#  * crm-bot: тот же образ, что crm-api; команда `python -m app bot`; healthcheck; лимит памяти; одна реплика;
#  * crm-api команды бота не получает;
#  * Caddy (prod и dev) отдаёт /telegram/webhook в crm-bot, а не в crm-api;
#  * crm-bot получает те же TELEGRAM_* и тот же адрес вебхука, что воркер и API.
# Секретов не требует: env — копия .env.prod.example с заглушками. Запуск: bash этот-файл
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fail() { echo "FAIL: $*"; exit 1; }

sed 's/CHANGE_ME/ci-only-value/' "$root/infra/.env.prod.example" > "$tmp/env.prod"
RT_IMAGE_TAG=crm-bot-test docker compose -f "$root/infra/compose/base.yml" -f "$root/infra/compose/prod.yml" \
  --env-file "$tmp/env.prod" config --format json > "$tmp/prod.json"
q() { jq -r "$1" "$tmp/prod.json"; }

[[ "$(q '.services["crm-bot"].command | join(" ")')" == "python -m app bot" ]] || fail "crm-bot: команда не 'python -m app bot'"
[[ "$(q '.services["crm-api"].command | join(" ")')" == "python -m app api" ]] || fail "crm-api: команда изменилась"
[[ "$(q '.services["crm-bot"].image')" == "$(q '.services["crm-api"].image')" ]] || fail "crm-bot и crm-api — не один образ"
[[ "$(q '.services["crm-bot"].healthcheck.test | join(" ")')" == *":8001/health"* ]] || fail "crm-bot: нет healthcheck на :8001/health"
[[ "$(q '.services["crm-bot"].deploy.resources.limits.memory')" != null ]] || fail "crm-bot: нет лимита памяти"
[[ "$(q '.services["crm-bot"].restart')" == unless-stopped ]] || fail "crm-bot: restart не unless-stopped"
# Один потребитель getUpdates: ни scale, ни replicas > 1.
[[ "$(q '.services["crm-bot"].deploy.replicas // 1')" == 1 ]] || fail "crm-bot: replicas != 1 (409 Conflict от Telegram)"
[[ "$(q '.services["crm-bot"].ports // [] | length')" == 0 ]] || fail "crm-bot: порт опубликован наружу"
for var in TELEGRAM_MODE TELEGRAM_WEBHOOK_URL TELEGRAM_WEBHOOK_SECRET; do
  [[ "$(q ".services[\"crm-bot\"].environment.$var // \"unset\"")" == "$(q ".services[\"crm-api\"].environment.$var // \"unset\"")" ]] \
    || fail "crm-bot: $var отличается от crm-api"
done

# Маршрут вебхука в обоих Caddyfile: handle /telegram/webhook → crm-bot:8001.
for f in Caddyfile.prod Caddyfile.dev; do
  block="$(awk '/handle \/telegram\/webhook \{/{f=1} f{print} f&&/\}/{exit}' "$root/infra/caddy/$f")"
  grep -q 'reverse_proxy crm-bot:8001' <<<"$block" || fail "$f: /telegram/webhook не ведёт в crm-bot:8001"
  ! grep -q 'crm-api' <<<"$block" || fail "$f: /telegram/webhook ведёт в crm-api"
done

# dev: crm-bot есть и там.
RT_IMAGE_TAG=crm-bot-test docker compose -f "$root/infra/compose/base.yml" -f "$root/infra/compose/dev.yml" \
  --env-file "$tmp/env.prod" config --format json > "$tmp/dev.json"
[[ "$(jq -r '.services["crm-bot"].command | join(" ")' "$tmp/dev.json")" == "python -m app bot" ]] || fail "dev: crm-bot без команды бота"
[[ "$(jq -r '.services["crm-api"].command | join(" ")' "$tmp/dev.json")" != *bot* ]] || fail "dev: crm-api запускает бота"
echo "crm-bot-test: ok"
