#!/usr/bin/env bash
# Тест W15-H8b: CRM видит источники для строк «Состояния системы» — архив WAL, Redis брокера и кэша. Секретов не требует.
#  1. crm-api, crm-worker, crm-bot получают REDIS_BROKER_URL / REDIS_CACHE_URL (пароли — из REDIS_*_PASSWORD окружения, а не
#     литералом в репозитории) и WAL_S3_PREFIX; на проде и на стенде.
#  2. Ключ CRM читает бакет `wal` (только чтение: список и объекты, без записи и удаления) — политика, собранная из init.sh.
#  3. deploy.sh запускает s3-init на каждом деплое до up: хранилище на проде уже инициализировано, политику не доставит один init.
# Запуск: bash этот-файл
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fail() { echo "FAIL: $*"; exit 1; }
base="$root/infra/compose/base.yml"; prod="$root/infra/compose/prod.yml"; dev="$root/infra/compose/dev.yml"
init="$root/infra/s3/init.sh"; deploy="$root/infra/deploy/deploy.sh"

mkenv() { # mkenv <пример> <выход>
  sed 's/CHANGE_ME/ci-only-value/' "$1" | grep -vE '^(REDIS_(BROKER|CACHE)_PASSWORD|WAL_S3_PREFIX)=' > "$2"
  printf 'REDIS_BROKER_PASSWORD=brokerpw\nREDIS_CACHE_PASSWORD=cachepw\nWAL_S3_PREFIX=pgtest\n' >> "$2"
}
mkenv "$root/infra/.env.prod.example" "$tmp/env.prod"
grep -v '^#' "$root/.env.example" | grep -v '^$' > "$tmp/env.dev.raw"; mkenv "$tmp/env.dev.raw" "$tmp/env.dev"
export RT_IMAGE_TAG=crm-status-sources-test
profiles=(--profile observability --profile kb-ingest --profile mcp)
docker compose -f "$base" -f "$prod" --env-file "$tmp/env.prod" "${profiles[@]}" config --format json > "$tmp/prod.json"
docker compose -f "$base" -f "$dev" --env-file "$tmp/env.dev" --profile observability config --format json > "$tmp/dev.json"

# 1. Окружение CRM.
for f in prod dev; do
  j="$tmp/$f.json"
  for svc in crm-api crm-worker crm-bot; do
    env_of() { jq -r --arg s "$svc" --arg k "$1" '.services[$s].environment[$k] // "none"' "$j"; }
    [[ "$(env_of REDIS_BROKER_URL)" == redis://:brokerpw@redis-broker:6379/0 ]] || fail "$f/$svc: REDIS_BROKER_URL: $(env_of REDIS_BROKER_URL)"
    [[ "$(env_of REDIS_CACHE_URL)" == redis://:cachepw@redis-cache:6379/0 ]] || fail "$f/$svc: REDIS_CACHE_URL: $(env_of REDIS_CACHE_URL)"
    [[ "$(env_of WAL_S3_PREFIX)" == pgtest ]] || fail "$f/$svc: WAL_S3_PREFIX: $(env_of WAL_S3_PREFIX)"
  done
done
# Пароли в репозитории не лежат: адреса собираются из переменных.
grep -qE '^    REDIS_BROKER_URL: redis://:\$\{REDIS_BROKER_PASSWORD:\?set in \.env\}@redis-broker:6379/0$' "$base" || fail "base.yml: REDIS_BROKER_URL не из REDIS_BROKER_PASSWORD"
grep -qE '^    REDIS_CACHE_URL: redis://:\$\{REDIS_CACHE_PASSWORD:\?set in \.env\}@redis-cache:6379/0$' "$base" || fail "base.yml: REDIS_CACHE_URL не из REDIS_CACHE_PASSWORD"

# 2. Политика CRM на бакет wal — только чтение.
grep -qE '^    crm\) echo "backups wal" ;;' "$init" || fail "init.sh: CRM должен читать backups и wal"
grep -qE '^    crm\) echo "kb-sources client-documents tg-attachments" ;;$' "$init" || fail "init.sh: rw-бакеты CRM изменились"
fn="$(sed -n '/^policy_json() {/,/^}/p' "$init")"
pol="$(bash -c "$fn; policy_json 'kb-sources client-documents tg-attachments' 'backups wal'")"
jq -e '[.Statement[] | select(.Action | index("s3:GetObject")) | select(.Action | index("s3:PutObject") | not) | .Resource[]] | index("arn:aws:s3:::wal/*")' <<<"$pol" >/dev/null \
  || fail "политика CRM: объекты бакета wal не читаются"
jq -e '[.Statement[] | select(.Action | index("s3:ListBucket")) | .Resource[]] | index("arn:aws:s3:::wal")' <<<"$pol" >/dev/null \
  || fail "политика CRM: список бакета wal недоступен"
! jq -e '[.Statement[] | select(.Action | index("s3:PutObject") or index("s3:DeleteObject")) | .Resource[]] | map(select(test("wal"))) | length > 0' <<<"$pol" >/dev/null \
  || fail "политика CRM: бакет wal открыт на запись или удаление"

# 3. s3-init на каждом деплое и до up.
run_line="$(grep -nE '^compose "\$rel" run --rm s3-init$' "$deploy" | head -1 | cut -d: -f1)"
up_line="$(grep -nE '^up_stack "\$rel"$' "$deploy" | head -1 | cut -d: -f1)"
[[ -n "$run_line" && -n "$up_line" && "$run_line" -lt "$up_line" ]] || fail "deploy.sh: s3-init должен запускаться на каждом деплое до up_stack"
bash -n "$deploy" || fail "deploy.sh: синтаксис"
echo "crm-status-sources-test: ok"
