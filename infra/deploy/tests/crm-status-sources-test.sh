#!/usr/bin/env bash
# Тест W15-H8b: CRM видит источники для строк «Состояния системы» — архив WAL, Redis брокера и кэша. Секретов не требует.
#  1. все сервисы CRM (api, worker, bot, mcp-*, migrate) получают REDIS_BROKER_URL / REDIS_CACHE_URL ТОЛЬКО с паролем пользователя пробы crm-probe
#     (REDIS_PROBE_PASSWORD; PING и INFO, без ключей) — полных паролей Redis у CRM нет — и WAL_S3_PREFIX; прод и стенд; без пароля
#     пробы CRM работает, пользователь выключен; секрет создаёт деплой (make-env-prod.sh ensure-secrets), а не человек.
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
  sed 's/CHANGE_ME/ci-only-value/' "$1" | grep -vE '^(REDIS_(BROKER|CACHE|PROBE)_PASSWORD|WAL_S3_PREFIX)=' > "$2"
  printf 'REDIS_BROKER_PASSWORD=brokerpw\nREDIS_CACHE_PASSWORD=cachepw\nREDIS_PROBE_PASSWORD=probepw\nWAL_S3_PREFIX=pgtest\n' >> "$2"
}
mkenv "$root/infra/.env.prod.example" "$tmp/env.prod"
grep -v '^#' "$root/.env.example" | grep -v '^$' > "$tmp/env.dev.raw"; mkenv "$tmp/env.dev.raw" "$tmp/env.dev"
export RT_IMAGE_TAG=crm-status-sources-test
profiles=(--profile observability --profile kb-ingest --profile mcp)
docker compose -f "$base" -f "$prod" --env-file "$tmp/env.prod" "${profiles[@]}" config --format json > "$tmp/prod.json"
docker compose -f "$base" -f "$dev" --env-file "$tmp/env.dev" "${profiles[@]}" config --format json > "$tmp/dev.json"

# 1. Окружение CRM: только пользователь пробы, полных паролей Redis нет.
for f in prod dev; do
  j="$tmp/$f.json"
  for svc in crm-api crm-worker crm-bot crm-mcp-crm crm-mcp-docs crm-mcp-kb crm-migrate; do
    env_of() { jq -r --arg s "$svc" --arg k "$1" '.services[$s].environment[$k] // "none"' "$j"; }
    [[ "$(env_of REDIS_BROKER_URL)" == redis://crm-probe:probepw@redis-broker:6379/0 ]] || fail "$f/$svc: REDIS_BROKER_URL: $(env_of REDIS_BROKER_URL)"
    [[ "$(env_of REDIS_CACHE_URL)" == redis://crm-probe:probepw@redis-cache:6379/0 ]] || fail "$f/$svc: REDIS_CACHE_URL: $(env_of REDIS_CACHE_URL)"
    [[ "$(env_of WAL_S3_PREFIX)" == pgtest ]] || fail "$f/$svc: WAL_S3_PREFIX: $(env_of WAL_S3_PREFIX)"
    [[ "$(jq -r --arg s "$svc" '.services[$s].environment | tostring | test("brokerpw|cachepw")' "$j")" == false ]] \
      || fail "$f/$svc: у CRM остался полный пароль Redis (сессии Платформы, очереди ERP)"
  done
  # Оба Redis заводят пользователя пробы: только PING и INFO.
  for r in redis-broker redis-cache; do
    [[ "$(jq -c --arg s "$r" '.services[$s].command | .[index("--user"):][:7]' "$j")" == '["--user","crm-probe","on",">probepw","-@all","+ping","+info"]' ]] \
      || fail "$f/$r: нет пользователя crm-probe с правами только PING и INFO"
  done
done
# Пароли в репозитории не лежат: адреса и пользователь собираются из REDIS_PROBE_PASSWORD.
grep -q 'REDIS_PROBE_PASSWORD' "$base" || fail "base.yml: нет REDIS_PROBE_PASSWORD"
! grep -qE 'crm-probe:[A-Za-z0-9]' "$base" || fail "base.yml: пароль пробы записан литералом"
# Без пароля пробы: CRM работает (адреса пусты, строки Redis «не проверено»), пользователь остаётся выключенным (пустые правила).
grep -v '^REDIS_PROBE_PASSWORD=' "$tmp/env.prod" > "$tmp/env.noprobe"
docker compose -f "$base" -f "$prod" --env-file "$tmp/env.noprobe" "${profiles[@]}" config --format json > "$tmp/noprobe.json"
[[ "$(jq -r '.services["crm-worker"].environment | [.REDIS_BROKER_URL, .REDIS_CACHE_URL] | join("|")' "$tmp/noprobe.json")" == "|" ]] || fail "без пароля пробы адреса Redis у CRM должны быть пусты"
[[ "$(jq -c '.services["redis-cache"].command | .[index("--user"):][:7]' "$tmp/noprobe.json")" == '["--user","crm-probe","","","-@all","+ping","+info"]' ]] || fail "без пароля пробы пользователь не должен включаться"

# Секрет создаёт деплой: ensure-secrets добавляет недостающий, не меняет заданный, права 600.
envf="$tmp/prod.env"; printf 'A=1\nREDIS_PROBE_PASSWORD=CHANGE_ME\nB=2\n' >"$envf"; chmod 644 "$envf"
bash "$root/infra/deploy/make-env-prod.sh" ensure-secrets "$envf" >/dev/null
first="$(grep '^REDIS_PROBE_PASSWORD=' "$envf")"
[[ "$first" =~ ^REDIS_PROBE_PASSWORD=[0-9a-f]{48}$ ]] || fail "ensure-secrets: пароль пробы не сгенерирован"
bash "$root/infra/deploy/make-env-prod.sh" ensure-secrets "$envf" >/dev/null
[[ "$(grep '^REDIS_PROBE_PASSWORD=' "$envf")" == "$first" ]] || fail "ensure-secrets: заданный пароль изменился"
printf 'A=1\n' >"$envf"; bash "$root/infra/deploy/make-env-prod.sh" ensure-secrets "$envf" >/dev/null
grep -qE '^REDIS_PROBE_PASSWORD=[0-9a-f]{48}$' "$envf" || fail "ensure-secrets: отсутствующий пароль не добавлен"
[[ "$(grep -c '^A=1$' "$envf")" == 1 ]] || fail "ensure-secrets: тронул чужие переменные"
ens="$(grep -nE 'ensure-secrets' "$deploy" | grep -v '^[0-9]*:#' | head -1 | cut -d: -f1)"
req="$(grep -nE '^require_env_file$' "$deploy" | head -1 | cut -d: -f1)"
[[ -n "$ens" && "$ens" -lt "$req" ]] || fail "deploy.sh: ensure-secrets должен идти до require_env_file (иначе CHANGE_ME остановит деплой)"

# 2. Политика CRM на бакет wal — только СПИСОК (имена и время сегментов), без чтения и записи объектов.
grep -qE '^    crm\) echo "wal" ;;' "$init" || fail "init.sh: CRM должен видеть список бакета wal (ls_of)"
grep -qE '^    crm\) echo "backups" ;;' "$init" || fail "init.sh: ro-бакет CRM: только backups"
grep -qE '^    crm\) echo "offsite/status.json" ;;$' "$init" || fail "init.sh: в offsite CRM читает только status.json"
grep -qE '^    crm\) echo "kb-sources client-documents tg-attachments" ;;$' "$init" || fail "init.sh: rw-бакеты CRM изменились"
fn="$(sed -n '/^policy_json() {/,/^}/p' "$init")"
pol="$(bash -c "$fn; policy_json 'kb-sources client-documents tg-attachments' 'backups' 'wal' 'offsite/status.json'")"
jq -e '[.Statement[] | select(.Action | index("s3:ListBucket")) | .Resource[]] | index("arn:aws:s3:::wal")' <<<"$pol" >/dev/null \
  || fail "политика CRM: список бакета wal недоступен"
[[ "$(jq -r '[.Statement[] | .Resource[] | select(test("wal"))] | length' <<<"$pol")" == 1 ]] \
  || fail "политика CRM: на wal должно быть ровно одно ресурсное правило (только бакет, без /*)"
[[ "$(jq -r '[.Statement[] | select(.Resource | tostring | test("wal")) | .Action[]] | sort | join(",")' <<<"$pol")" == s3:GetBucketLocation,s3:ListBucket ]] \
  || fail "политика CRM: бакет wal открыт не только на список"

# 3. s3-init на каждом деплое и до up.
run_line="$(grep -nE '^compose "\$rel" run --rm s3-init$' "$deploy" | head -1 | cut -d: -f1)"
up_line="$(grep -nE '^up_stack "\$rel"$' "$deploy" | head -1 | cut -d: -f1)"
[[ -n "$run_line" && -n "$up_line" && "$run_line" -lt "$up_line" ]] || fail "deploy.sh: s3-init должен запускаться на каждом деплое до up_stack"
bash -n "$deploy" || fail "deploy.sh: синтаксис"
echo "crm-status-sources-test: ok"
