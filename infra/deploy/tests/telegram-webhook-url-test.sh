#!/usr/bin/env bash
# Тест FIX-66: TELEGRAM_WEBHOOK_URL в проде по умолчанию строится из CRM_DOMAIN и совпадает с путём
# приёмника (Caddyfile.prod → /telegram/webhook); явное значение остаётся переопределением.
# Раньше пустое значение уходило в CRM как есть, set_webhook("") молча удалял вебхук.
# Секретов не требует: env — копия .env.prod.example с заглушками. Запуск: bash этот-файл
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fail() { echo "FAIL: $*"; exit 1; }

# Путь приёмника: тот же, что в Caddyfile.prod и в маршруте FastAPI (app/api/telegram.py).
grep -q 'handle /telegram/webhook' "$root/infra/caddy/Caddyfile.prod" || fail "в Caddyfile.prod нет handle /telegram/webhook"
grep -q 'WEBHOOK_PATH: Final = "/telegram/webhook"' "$root/apps/crm/backend/app/domain/telegram_webhook.py" \
  || fail "путь приёмника в CRM изменился: поправьте prod.yml и Caddyfile.prod"

render() { # $1 — файл env; печатает TELEGRAM_WEBHOOK_URL у crm-api и crm-worker (по одному в строке)
  RT_IMAGE_TAG=webhook-url-test docker compose -f "$root/infra/compose/base.yml" -f "$root/infra/compose/prod.yml" \
    --env-file "$1" config --format json > "$tmp/prod.json"
  for svc in crm-api crm-worker; do
    jq -r --arg s "$svc" '.services[$s].environment.TELEGRAM_WEBHOOK_URL // "unset"' "$tmp/prod.json"
  done
}
check() { # $1 — файл env, $2 — ожидаемое значение
  local svc=crm-api line
  while IFS= read -r line; do
    [[ "$line" == "$2" ]] || fail "$svc: TELEGRAM_WEBHOOK_URL=$line, ожидалось $2"
    svc=crm-worker
  done < <(render "$1")
}

base="$tmp/env.base"
sed 's/CHANGE_ME/ci-only-value/' "$root/infra/.env.prod.example" > "$base"

# 1. Переменная пуста (как в .env.prod.example) — адрес из домена.
sed -e '/^TELEGRAM_WEBHOOK_URL=/d' -e 's/^CRM_DOMAIN=.*/CRM_DOMAIN=crm.example.org/' "$base" > "$tmp/env.empty"
echo 'TELEGRAM_WEBHOOK_URL=' >> "$tmp/env.empty"
check "$tmp/env.empty" "https://crm.example.org/telegram/webhook"

# 2. Переменной нет вовсе — то же самое.
sed -e '/^TELEGRAM_WEBHOOK_URL=/d' -e 's/^CRM_DOMAIN=.*/CRM_DOMAIN=crm.example.org/' "$base" > "$tmp/env.absent"
check "$tmp/env.absent" "https://crm.example.org/telegram/webhook"

# 3. Явное значение — переопределение.
sed -e '/^TELEGRAM_WEBHOOK_URL=/d' -e 's/^CRM_DOMAIN=.*/CRM_DOMAIN=crm.example.org/' "$base" > "$tmp/env.override"
echo 'TELEGRAM_WEBHOOK_URL=https://hook.example.net/tg' >> "$tmp/env.override"
check "$tmp/env.override" "https://hook.example.net/tg"

# 4. Домен другой — адрес следует за ним (не зашит).
sed -e '/^TELEGRAM_WEBHOOK_URL=/d' -e 's/^CRM_DOMAIN=.*/CRM_DOMAIN=crm.other.test/' "$base" > "$tmp/env.other"
check "$tmp/env.other" "https://crm.other.test/telegram/webhook"

# 5. Сам образец окружения: после подстановки адрес не пуст и https.
check "$base" "https://$(sed -n 's/^CRM_DOMAIN=//p' "$base")/telegram/webhook"
echo "telegram-webhook-url-test: ok"
