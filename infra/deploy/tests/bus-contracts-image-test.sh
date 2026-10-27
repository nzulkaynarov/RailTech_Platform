#!/usr/bin/env bash
# Тест B3 (L14), бывший M5-INF-01c: контракты шины rt_bus доезжают до сервисов ERP в образе, а не монтированием.
#  1. base.yml собирает все сервисы ERP на одном образе с именованными контекстами rtbus и contracts;
#  2. Dockerfile ERP копирует их (COPY --from=rtbus / --from=contracts) и задаёт RT_BUS_CONTRACTS_DIR / RT_BUS_SUBSCRIPTIONS;
#  3. deploy.yml собирает rt-erp-backend с теми же контекстами, а release.tgz не несёт events.schema.json;
#  4. prod.yml не монтирует events.schema.json (файла контрактов событий в релизе нет), deploy.sh его не требует;
#  5. (S0-1) файлы ERP — в RustFS: тома медиа нет, у сервисов ERP заданы MINIO_* и бакеты erp-*.
# Секретов не требует: env — копия .env.prod.example с заглушками. Запуск: bash этот-файл
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fail() { echo "FAIL: $*"; exit 1; }

sed 's/CHANGE_ME/ci-only-value/' "$root/infra/.env.prod.example" > "$tmp/env.prod"

# 1. Контексты сборки образа ERP (dev-конфигурация: build есть) — у каждого сервиса ERP на этом образе.
cp "$tmp/env.prod" "$tmp/env.dev"
cat >> "$tmp/env.dev" <<'ENV'
SERVICE_TOKEN_CRM_TO_ERP=ci-only-value
WEBHOOK_SECRET=ci-only-value
ERP_MCP_CONTEXT_KEY=ci-only-value
PLATFORM_SSO_SECRET=ci-only-value
ERP_SECRET_KEY=ci-only-value
ENV
docker compose -f "$root/infra/compose/base.yml" --env-file "$tmp/env.dev" --profile mcp config --format json > "$tmp/base.json"
for svc in erp-backend erp-mcp erp-worker erp-worker-ai erp-beat erp-ai-gateway; do
  jq -e --arg s "$svc" '.services[$s].build as $b
      | ($b.additional_contexts.rtbus | endswith("/packages/rt-bus"))
        and ($b.additional_contexts.contracts | endswith("/packages/contracts"))' "$tmp/base.json" >/dev/null \
    || fail "$svc: в base.yml нет build.additional_contexts rtbus=packages/rt-bus и contracts=packages/contracts"
done

# 2. Dockerfile ERP.
dockerfile="$root/apps/erp/backend/Dockerfile"
grep -qE '^COPY --from=rtbus ' "$dockerfile" || fail "Dockerfile ERP: нет COPY --from=rtbus"
grep -qE '^COPY --from=contracts events ' "$dockerfile" || fail "Dockerfile ERP: нет COPY --from=contracts events"
grep -qE '^COPY --from=contracts bus ' "$dockerfile" || fail "Dockerfile ERP: нет COPY --from=contracts bus"
grep -q 'RT_BUS_CONTRACTS_DIR=/opt/rt/contracts/events' "$dockerfile" || fail "Dockerfile ERP: нет RT_BUS_CONTRACTS_DIR=/opt/rt/contracts/events"
grep -q 'RT_BUS_SUBSCRIPTIONS=/opt/rt/contracts/bus/subscriptions.yaml' "$dockerfile" || fail "Dockerfile ERP: нет RT_BUS_SUBSCRIPTIONS"

# 3. deploy.yml: контексты сборки образа ERP и состав release.tgz.
workflow="$root/.github/workflows/deploy.yml"
# shellcheck source=deploy-images.sh
source "$(dirname "${BASH_SOURCE[0]}")/deploy-images.sh"
erp_step="$(deploy_image_field "$workflow" rt-erp-backend contexts)"
[[ -n "$erp_step" ]] || fail "deploy.yml: у образа rt-erp-backend нет build-contexts (или образа нет в таблице образов)"
grep -q 'rtbus=packages/rt-bus' <<<"$erp_step" || fail "deploy.yml: образ rt-erp-backend собирается без build-contexts rtbus=packages/rt-bus"
grep -q 'contracts=packages/contracts' <<<"$erp_step" || fail "deploy.yml: образ rt-erp-backend собирается без build-contexts contracts=packages/contracts"
if grep -E 'tar -czf release\.tgz .*events\.schema\.json' "$workflow" >/dev/null; then
  fail "deploy.yml: release.tgz всё ещё несёт packages/contracts/events.schema.json"
fi

# 4. prod.yml без монтирования схемы событий; deploy.sh файл не требует.
RT_IMAGE_TAG=events-test docker compose -f "$root/infra/compose/base.yml" -f "$root/infra/compose/prod.yml" \
  --env-file "$tmp/env.prod" --profile mcp config --format json > "$tmp/prod.json"
for svc in erp-backend erp-worker erp-worker-ai erp-beat erp-mcp; do
  jq -e --arg s "$svc" '[.services[$s].volumes[]? | select((.source // "") | endswith("events.schema.json"))] | length == 0' \
    "$tmp/prod.json" >/dev/null || fail "$svc: prod.yml монтирует events.schema.json — контракты шины вшиты в образ"
done
! grep -q 'events.schema.json' "$root/infra/deploy/deploy.sh" || fail "deploy.sh всё ещё требует events.schema.json в релизе"

# 5. Файлы ERP — в RustFS (S0-1): тома медиа нет, адрес и бакеты заданы всем сервисам ERP, где работают с файлами.
jq -e '(.volumes | has("erp_media") | not)' "$tmp/prod.json" >/dev/null || fail "в prod-конфиге остался том erp_media"
for svc in erp-backend erp-worker erp-worker-ai erp-beat erp-mcp; do
  jq -e --arg s "$svc" '[.services[$s].volumes[]? | select(.target == "/app/media")] | length == 0' "$tmp/prod.json" >/dev/null \
    || fail "$svc: смонтирован /app/media — файлы ERP должны лежать в RustFS, не на диске"
  jq -e --arg s "$svc" '.services[$s].environment as $e
      | $e.MINIO_ENDPOINT == "http://rustfs:9000" and ($e.MINIO_ACCESS_KEY | length > 0) and ($e.MINIO_SECRET_KEY | length > 0)
        and $e.MINIO_PRIVATE_BUCKET == "erp-private" and $e.MINIO_PUBLIC_BUCKET == "erp-public" and $e.MINIO_TEMP_BUCKET == "erp-temp"' \
    "$tmp/prod.json" >/dev/null || fail "$svc: не заданы MINIO_* (RustFS, бакеты erp-private/erp-public/erp-temp)"
done
buckets="$(jq -r '.services["s3-init"].environment.S3_BUCKETS' "$tmp/prod.json")"
for bucket in erp-private erp-public erp-temp; do
  [[ " $buckets " == *" $bucket "* ]] || fail "s3-init не создаёт бакет $bucket"
done
echo "bus-contracts-image-test: ok"
