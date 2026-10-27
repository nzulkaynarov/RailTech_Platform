#!/usr/bin/env bash
# Тест волны 12 (E2): сервис EDS в compose, инфраструктуре и деплое. Секретов не требует: env — копии примеров с заглушками,
# у каждого секрета своё значение, чтобы по значению было видно, кому оно досталось.
#  1. Примеры env: переменные EDS есть, секреты — CHANGE_ME; make-env.sh и make-env-prod.sh генерируют их, в том числе в уже
#     существующем файле (обновление прода), и не печатают.
#  2. Compose (dev и prod): eds-migrate/eds-api/eds-worker, образ rt-eds (prod), порты наружу не публикуются, миграция идёт
#     до api и воркера, healthcheck есть; ключ S3, секрет токена и секреты пар шины — только у тех, кому положены.
#  3. Внешнего маршрута нет: ни один домен в Caddyfile.dev/prod не проксирует на EDS; Caddy не ждёт EDS.
#  4. База eds (VPS 2): роль eds_app, pg_hba, бэкап, WAL-G, pg_dump-гейт; бакет eds-private и ключ с доступом только к нему.
#  5. Деплой: образ rt-eds в deploy.yml, миграция EDS после pg_dump-гейта и до up, EDS в откате.
# Запуск: bash этот-файл
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fail() { echo "FAIL: $*"; exit 1; }
base="$root/infra/compose/base.yml"; prod="$root/infra/compose/prod.yml"; dev="$root/infra/compose/dev.yml"
EDS_VARS=(EDS_ACCESS_SECRET S3_EDS_ACCESS_KEY S3_EDS_SECRET_KEY RT_BUS_SECRET_CRM_EDS RT_BUS_SECRET_ERP_EDS RT_BUS_SECRET_EDS_ERP RT_BUS_SECRET_EDS_PLATFORM_BFF)

# 1. Примеры env и генерация.
for example in "$root/.env.example" "$root/infra/.env.prod.example"; do
  for v in "${EDS_VARS[@]}"; do grep -q "^$v=CHANGE_ME$" "$example" || fail "$example: нет $v=CHANGE_ME"; done
  grep -q '^RT_BUS_ENDPOINT_EDS=$' "$example" || fail "$example: нет RT_BUS_ENDPOINT_EDS= (необязательное переопределение адреса)"
done
grep -q '^DB_EDS_PASSWORD=CHANGE_ME$' "$root/infra/.env.prod.example" || fail "infra/.env.prod.example: нет DB_EDS_PASSWORD=CHANGE_ME"

# make-env-prod.sh: свежий файл и обновление существующего (прод до волны 12 — без переменных EDS).
fresh="$tmp/fresh.env"
out="$(bash "$root/infra/deploy/make-env-prod.sh" init "$fresh")"
legacy="$tmp/legacy.env"
grep -vE '^(EDS_ACCESS_SECRET|S3_EDS_(ACCESS|SECRET)_KEY|DB_EDS_PASSWORD|RT_BUS_SECRET_(CRM_EDS|ERP_EDS|EDS_ERP|EDS_PLATFORM_BFF)|RT_BUS_ENDPOINT_EDS)=' \
  "$root/infra/.env.prod.example" | sed 's/CHANGE_ME/legacy-value/' > "$legacy"
chmod 600 "$legacy"
out_legacy="$(bash "$root/infra/deploy/make-env-prod.sh" init "$legacy")"
for file in "$fresh" "$legacy"; do
  seen=""
  for v in DB_EDS_PASSWORD "${EDS_VARS[@]}"; do
    value="$(grep "^$v=" "$file" | cut -d= -f2-)"
    [[ -n "$value" && "$value" != CHANGE_ME && "$value" != legacy-value ]] || fail "make-env-prod.sh init не сгенерировал $v ($file)"
    [[ "$out$out_legacy" != *"$value"* ]] || fail "make-env-prod.sh init напечатал значение $v"
    seen+="$value"$'\n'
  done
  [[ -z "$(sort <<<"${seen%$'\n'}" | uniq -d)" ]] || fail "секреты EDS в $file совпадают друг с другом"
done
grep -q '^RT_BUS_ENDPOINT_EDS=$' "$legacy" || fail "обновление: RT_BUS_ENDPOINT_EDS не дописан пустым"
# extract-db отдаёт VPS 2 пароль роли eds_app, но не секреты и ключи EDS.
bash "$root/infra/deploy/make-env-prod.sh" extract-db "$fresh" > "$tmp/env.db"
grep -q '^DB_EDS_PASSWORD=' "$tmp/env.db" || fail "extract-db не отдаёт DB_EDS_PASSWORD на VPS 2"
for v in EDS_ACCESS_SECRET S3_EDS_SECRET_KEY RT_BUS_SECRET_CRM_EDS; do
  ! grep -qF -- "$(grep "^$v=" "$fresh" | cut -d= -f2-)" "$tmp/env.db" || fail "extract-db отдал VPS 2 $v"
done
# s3-keys дописывает ключ EDS в файл, где остальные ключи уже есть.
sk="$tmp/s3keys.env"; grep -vE '^S3_EDS_(ACCESS|SECRET)_KEY=' "$fresh" > "$sk"
bash "$root/infra/deploy/make-env-prod.sh" s3-keys "$sk" >/dev/null
grep -qE '^S3_EDS_SECRET_KEY=[0-9a-f]{48}$' "$sk" || fail "s3-keys не создал ключ EDS в существующем файле"

# make-env.sh (dev): копия скрипта в одноразовом корне; существующий .env без EDS получает новые переменные со случайными значениями.
dev_root="$tmp/devroot"; mkdir -p "$dev_root/infra/compose"
cp "$root/infra/compose/make-env.sh" "$dev_root/infra/compose/"; cp "$root/.env.example" "$dev_root/.env.example"
grep -vE '^(EDS_ACCESS_SECRET|S3_EDS_(ACCESS|SECRET)_KEY|RT_BUS_SECRET_(CRM_EDS|ERP_EDS|EDS_ERP|EDS_PLATFORM_BFF))=' "$root/.env.example" \
  | sed 's/CHANGE_ME/old-value/' > "$dev_root/.env"
bash "$dev_root/infra/compose/make-env.sh" >/dev/null
for v in "${EDS_VARS[@]}"; do
  value="$(grep "^$v=" "$dev_root/.env" | cut -d= -f2-)"
  [[ -n "$value" && "$value" != CHANGE_ME && "$value" != old-value ]] || fail "make-env.sh не сгенерировал $v в существующем .env"
done
grep -q '^POSTGRES_PASSWORD=old-value$' "$dev_root/.env" || fail "make-env.sh перезаписал существующее значение"

# 2. Compose. Окружения с РАЗНЫМИ значениями секретов EDS.
mkenv() { # mkenv <пример> <выход>
  sed 's/CHANGE_ME/ci-only-value/' "$1" | grep -vE '^(EDS_ACCESS_SECRET|S3_EDS_(ACCESS|SECRET)_KEY|RT_BUS_SECRET_(CRM_EDS|ERP_EDS|EDS_ERP|EDS_PLATFORM_BFF))=' > "$2"
  for v in "${EDS_VARS[@]}"; do printf '%s=val-%s\n' "$v" "$v" >> "$2"; done
}
mkenv "$root/infra/.env.prod.example" "$tmp/env.prod"
grep -v '^#' "$root/.env.example" | grep -v '^$' > "$tmp/env.dev.raw"; mkenv "$tmp/env.dev.raw" "$tmp/env.dev"
export RT_IMAGE_TAG=eds-test
docker compose -f "$base" -f "$prod" --env-file "$tmp/env.prod" --profile observability --profile kb-ingest --profile mcp config --format json > "$tmp/prod.json"
docker compose -f "$base" -f "$dev" --env-file "$tmp/env.dev" --profile observability config --format json > "$tmp/dev.json"

for f in prod dev; do
  j="$tmp/$f.json"
  holders() { jq -r --arg v "$1" '[.services | to_entries[] | select(.value.environment // {} | tostring | test($v)) | .key] | sort | join(",")' "$j"; }
  for svc in eds-migrate eds-api eds-worker; do
    jq -e --arg s "$svc" '.services[$s] != null' "$j" >/dev/null || fail "$f: нет сервиса $svc"
    [[ "$(jq -r --arg s "$svc" '(.services[$s].ports // []) | length' "$j")" == 0 ]] || fail "$f: $svc публикует порт — у EDS нет внешнего доступа"
  done
  [[ "$(jq -r '.services["eds-api"].command | join(" ")' "$j")" == python\ -m\ app\ api* ]] || fail "$f: eds-api не запускает python -m app api"
  [[ "$(jq -r '.services["eds-worker"].command | join(" ")' "$j")" == "python -m app worker" ]] || fail "$f: eds-worker не запускает python -m app worker"
  [[ "$(jq -r '.services["eds-migrate"].command | join(" ")' "$j")" == "alembic upgrade head" ]] || fail "$f: eds-migrate не alembic upgrade head"
  [[ "$(jq -r '.services["eds-migrate"].restart' "$j")" == no ]] || fail "$f: eds-migrate должен быть одноразовым"
  for svc in eds-api eds-worker; do
    [[ "$(jq -r --arg s "$svc" '.services[$s].depends_on["eds-migrate"].condition' "$j")" == service_completed_successfully ]] || fail "$f: $svc не ждёт eds-migrate"
    [[ "$(jq -r --arg s "$svc" '.services[$s].healthcheck.test != null' "$j")" == true ]] || fail "$f: у $svc нет healthcheck"
    [[ "$(jq -r --arg s "$svc" '.services[$s].depends_on["s3-init"].condition' "$j")" == service_completed_successfully ]] || fail "$f: $svc не ждёт s3-init"
  done
  # Ключ S3, секрет токена и секреты пар — только у тех, кому положены. (EDS_ACCESS_SECRET нет ни у кого, кроме EDS.)
  [[ "$(holders 'val-S3_EDS_ACCESS_KEY|val-S3_EDS_SECRET_KEY')" == eds-api,eds-migrate,eds-worker,s3-init ]] || fail "$f: ключ S3 EDS у лишних сервисов: $(holders 'val-S3_EDS_ACCESS_KEY|val-S3_EDS_SECRET_KEY')"
  [[ "$(holders 'val-EDS_ACCESS_SECRET')" == eds-api,eds-migrate,eds-worker ]] || fail "$f: EDS_ACCESS_SECRET у лишних сервисов: $(holders 'val-EDS_ACCESS_SECRET')"
  for svc in eds-api eds-worker eds-migrate; do
    jq -e --arg s "$svc" --arg ak val-S3_EDS_ACCESS_KEY --arg sk val-S3_EDS_SECRET_KEY \
      '.services[$s].environment | .S3_ACCESS_KEY == $ak and .S3_SECRET_KEY == $sk and .S3_BUCKET == "eds-private"' "$j" >/dev/null \
      || fail "$f: $svc не на ключе EDS и бакете eds-private"
  done
  crm_pair="$(holders 'val-RT_BUS_SECRET_CRM_EDS')"
  [[ "$crm_pair" == *crm-api* && "$crm_pair" == *crm-worker* && "$crm_pair" == *eds-api* && "$crm_pair" == *eds-worker* && "$crm_pair" != *erp-* ]] || fail "$f: секрет пары CRM→EDS: $crm_pair"
  erp_pair="$(holders 'val-RT_BUS_SECRET_ERP_EDS|val-RT_BUS_SECRET_EDS_ERP')"
  [[ "$erp_pair" == *erp-backend* && "$erp_pair" == *erp-worker* && "$erp_pair" == *eds-api* && "$erp_pair" == *eds-worker* && "$erp_pair" != *crm-* ]] || fail "$f: секреты пар ERP↔EDS: $erp_pair"
  bff_pair="$(holders 'val-RT_BUS_SECRET_EDS_PLATFORM_BFF')"
  [[ "$bff_pair" == *platform-bff* && "$bff_pair" == *eds-worker* && "$bff_pair" != *crm-* && "$bff_pair" != *erp-* ]] || fail "$f: секрет пары EDS→BFF: $bff_pair"
  # Каталог схем и подписки шины вшиты в образ (L14); подписки не монтируются с хоста.
  jq -e '.services["eds-api"].environment | has("RT_BUS_CONTRACTS_DIR") | not' "$j" >/dev/null || fail "$f: RT_BUS_CONTRACTS_DIR должен задавать образ, а не compose"
  # 3. Caddy не ждёт EDS и не получает его в окружение.
  jq -e '[.services.caddy.depends_on | keys[] | select(startswith("eds"))] | length == 0' "$j" >/dev/null || fail "$f: Caddy зависит от EDS"
done
jq -e '[.services["eds-api"].build.additional_contexts | .rtbus, .contracts | select(endswith("/packages/rt-bus") or endswith("/packages/contracts"))] | length == 2' "$tmp/dev.json" >/dev/null \
  || fail "dev: у eds-api нет additional_contexts rtbus и contracts"
[[ "$(jq -r '.services["eds-api"].build.target' "$tmp/dev.json")" == dev ]] || fail "dev: eds-api собирается не target dev"
for svc in eds-api eds-worker eds-migrate; do
  [[ "$(jq -r --arg s "$svc" '.services[$s].image' "$tmp/prod.json")" == "ghcr.io/nzulkaynarov/rt-eds:eds-test" ]] || fail "prod: $svc не на образе rt-eds:<тег>"
  jq -e --arg s "$svc" '.services[$s].build == null' "$tmp/prod.json" >/dev/null || fail "prod: $svc собирается на сервере"
  jq -e --arg s "$svc" '.services[$s].environment | .APP_ENV == "prod" and (.EDS_DATABASE_URL | test("^postgresql\\+psycopg://eds_app:.+@.+:5432/eds\\?sslmode=require$"))' "$tmp/prod.json" >/dev/null \
    || fail "prod: $svc не на базе eds роли eds_app по TLS"
done
jq -e '.services["eds-api"].environment.EDS_DATABASE_URL | contains("ci-only-value")' "$tmp/prod.json" >/dev/null || fail "prod: пароль роли eds_app не из DB_EDS_PASSWORD"
[[ "$(jq -r '.services["eds-api"].deploy.resources.limits.memory' "$tmp/prod.json")" != null ]] || fail "prod: у eds-api нет лимита памяти"
[[ "$(jq -r '.services["eds-worker"].deploy.resources.limits.memory' "$tmp/prod.json")" != null ]] || fail "prod: у eds-worker нет лимита памяти"

# 3. Caddyfile: ни одного упоминания EDS, и в разобранной конфигурации Caddy нет апстримов eds-*.
for file in "$root/infra/caddy/Caddyfile.dev" "$root/infra/caddy/Caddyfile.prod"; do
  ! grep -qiE 'eds' "$file" || fail "$(basename "$file"): упоминание EDS — внешнего маршрута быть не должно"
done
if command -v docker >/dev/null; then
  for file in Caddyfile.dev Caddyfile.prod; do
    adapted="$(docker run --rm -e ACME_EMAIL=a@example.com -e CRM_DOMAIN=crm.example.org -e ERP_DOMAIN=erp.example.org -e CABINET_DOMAIN=cabinet.example.org -e PLATFORM_DOMAIN=platform.example.org \
      -v "$root/infra/caddy/$file:/etc/caddy/Caddyfile:ro" "${CADDY_IMAGE:-caddy:2.11.7-alpine}" caddy adapt --config /etc/caddy/Caddyfile 2>/dev/null)"
    [[ -n "$adapted" ]] || fail "$file: caddy adapt не отработал"
    ! grep -qi 'eds' <<<"$adapted" || fail "$file: в конфигурации Caddy есть апстрим EDS"
  done
fi

# 4. База eds и S3.
grep -q '^ensure_role eds_app DB_EDS_PASSWORD$' "$root/infra/db/prod-init.sh" || fail "prod-init.sh: нет роли eds_app"
grep -q '^ensure_db eds eds_app$' "$root/infra/db/prod-init.sh" || fail "prod-init.sh: нет базы eds"
grep -qE '^for db in .*\beds\b' "$root/infra/db/prod-init.sh" || fail "prod-init.sh: eds не закрыта от чужих ролей (REVOKE CONNECT)"
grep -qE '^hostssl +eds +eds_app +@APP_INTERNAL_IP@/32 +scram-sha-256$' "$root/infra/db/pg_hba.conf.tpl" || fail "pg_hba.conf.tpl: нет строки eds/eds_app"
grep -q 'DB_EDS_PASSWORD' "$root/infra/compose/db.yml" || fail "db.yml: postgres не получает DB_EDS_PASSWORD"
[[ "$(grep -c 'DB_NAMES: crm erp eds litellm langfuse' "$root/infra/compose/db.yml")" == 2 ]] || fail "db.yml: eds не в DB_NAMES у walg и backup"
grep -q 'DB_NAMES:-crm erp eds litellm langfuse' "$root/infra/db/backup.sh" || fail "backup.sh: eds не в списке баз"
grep -q 'DB_NAMES:-crm erp eds litellm langfuse' "$root/infra/db/rt-pitr.sh" || fail "rt-pitr.sh: eds не в списке баз проверки"
grep -q 'dump_db eds eds_app DB_EDS_PASSWORD' "$root/infra/deploy/predeploy-dump.sh" || fail "predeploy-dump.sh: eds не в pg_dump-гейте"
grep -q '"$name" == eds' "$root/infra/db/restore-check.sh" || fail "restore-check.sh: пустая eds не считается ошибкой"
init="$root/infra/s3/init.sh"
grep -qE '^    eds\) echo "eds-private" ;;' "$init" || fail "init.sh: EDS не ограничен бакетом eds-private"
grep -qE '^SERVICES=.*\beds\b' "$init" || fail "init.sh: eds не в SERVICES"
for f in prod dev; do
  buckets="$(jq -r '.services["s3-init"].environment.S3_BUCKETS' "$tmp/$f.json")"
  [[ " $buckets " == *" eds-private "* ]] || fail "$f: s3-init не создаёт бакет eds-private"
done
docker compose -f "$root/infra/compose/db.yml" --env-file "$tmp/env.prod" config --format json \
  | jq -e '.services.postgres.environment.DB_EDS_PASSWORD == "ci-only-value"' >/dev/null || fail "db.yml: пароль eds_app не доходит до postgres"
# init-databases.sh (dev) создаёт базу по имени из аргументов; db-init вызывает её с eds.
jq -r '.services["db-init"].command | join(" ")' "$tmp/dev.json" | grep -qE 'init-databases.sh crm erp eds ' || fail "dev: db-init не создаёт базу eds"

# 5. Деплой.
workflow="$root/.github/workflows/deploy.yml"
# shellcheck source=deploy-images.sh
source "$here/deploy-images.sh"
deploy_image_names "$workflow" | grep -qx rt-eds || fail "deploy.yml: нет сборки образа rt-eds"
[[ "$(deploy_image_field "$workflow" rt-eds context)" == "apps/eds" ]] || fail "deploy.yml: rt-eds собирается не из apps/eds"
eds_ctx="$(deploy_image_field "$workflow" rt-eds contexts)"
grep -q 'rtbus=packages/rt-bus' <<<"$eds_ctx" && grep -q 'contracts=packages/contracts' <<<"$eds_ctx" || fail "deploy.yml: rt-eds без build-contexts rtbus и contracts"
[[ "$(deploy_image_field "$workflow" rt-eds target)" == "prod" ]] || fail "deploy.yml: rt-eds собирается не target prod"
deploy="$root/infra/deploy/deploy.sh"
dump="$(grep -n 'predeploy-dump.sh' "$deploy" | grep -v '^[0-9]*:#' | head -1 | cut -d: -f1)"
mig="$(grep -n 'run --rm --no-deps eds-migrate' "$deploy" | head -1 | cut -d: -f1)"
up="$(grep -n '^up_stack' "$deploy" | head -1 | cut -d: -f1)"
[[ -n "$dump" && -n "$mig" && -n "$up" && "$dump" -lt "$mig" && "$mig" -lt "$up" ]] || fail "deploy.sh: миграция EDS должна идти после pg_dump-гейта и до up"
grep -qE 'pull .* eds-api' "$deploy" || fail "deploy.sh: eds-api не входит в pull"
grep -q 'wait_healthy "$rel" "$svc"' "$deploy" && grep -q 'for svc in eds-api eds-worker' "$deploy" || fail "deploy.sh: нет проверки здоровья eds-api и eds-worker (у EDS нет домена для smoke)"
grep -q 'eds-api' "$root/infra/deploy/rollback.sh" || fail "rollback.sh: EDS не учтён при откате"
grep -q 'platform-web|eds)' "$root/infra/deploy/lib.sh" || fail "lib.sh: cleanup_old не чистит образы rt-eds"
echo "eds-prod-test: ok"
