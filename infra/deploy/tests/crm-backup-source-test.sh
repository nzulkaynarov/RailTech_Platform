#!/usr/bin/env bash
# Тест M5-CRM-01: в проде CRM берёт статус бэкапов из бакета RustFS, а не из тома.
# Том crm_backups из base.yml смонтирован и в prod, поэтому BACKUP_SOURCE=auto выбрал бы том;
# prod.yml обязан задавать BACKUP_SOURCE=rustfs у crm-api и crm-worker (а в dev переменной нет).
# Секретов не требует: env — копия .env.prod.example с заглушками. Запуск: bash этот-файл
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fail() { echo "FAIL: $*"; exit 1; }

sed 's/CHANGE_ME/ci-only-value/' "$root/infra/.env.prod.example" > "$tmp/env.prod"
RT_IMAGE_TAG=backup-source-test docker compose -f "$root/infra/compose/base.yml" -f "$root/infra/compose/prod.yml" \
  --env-file "$tmp/env.prod" config --format json > "$tmp/prod.json"
for svc in crm-api crm-worker; do
  got="$(jq -r --arg s "$svc" '.services[$s].environment.BACKUP_SOURCE // "unset"' "$tmp/prod.json")"
  [[ "$got" == rustfs ]] || fail "$svc: BACKUP_SOURCE=$got в prod-конфиге, нужно rustfs"
done
# В dev переменной нет: источник выбирает auto (том, если смонтирован).
RT_IMAGE_TAG=backup-source-test docker compose -f "$root/infra/compose/base.yml" \
  --env-file "$tmp/env.prod" config --format json > "$tmp/dev.json" 2>/dev/null || true
if [[ -s "$tmp/dev.json" ]]; then
  got="$(jq -r '.services["crm-api"].environment.BACKUP_SOURCE // "unset"' "$tmp/dev.json")"
  [[ "$got" == unset ]] || fail "dev (base.yml): BACKUP_SOURCE=$got, ожидалось не задано (auto)"
fi
echo "crm-backup-source-test: ok"
