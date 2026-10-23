#!/usr/bin/env bash
# Тест B5 (ADR-0014): BFF Платформы — подписчик шины rt_bus, подсказки SSE.
#  1. base.yml: platform-bff собирается с контекстами rtbus и contracts; секреты пар «издатель → platform-bff» есть у BFF,
#     у ERP (erp-worker) и у CRM (crm-worker) — издатель подписывает, BFF проверяет;
#  2. prod.yml: те же секреты доезжают до прода (окружение сливается с base.yml); .env.prod.example не содержит значений;
#  3. Dockerfile BFF копирует пакет и контракты (COPY --from=rtbus / --from=contracts) и задаёт RT_BUS_*;
#  4. deploy.yml собирает rt-platform-bff с теми же именованными контекстами;
#  5. подписка platform-bff есть в subscriptions.yaml; /bus/* на домене Платформы в Caddy — 404 (dev и prod).
# Секретов не требует: env — копия .env.prod.example с заглушками. Запуск: bash этот-файл
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fail() { echo "FAIL: $*"; exit 1; }

sed 's/CHANGE_ME/ci-only-value/' "$root/infra/.env.prod.example" > "$tmp/env.prod"
grep -q '^RT_BUS_SECRET_ERP_PLATFORM_BFF=ci-only-value$' "$tmp/env.prod" || fail ".env.prod.example: нет RT_BUS_SECRET_ERP_PLATFORM_BFF=CHANGE_ME"
grep -q '^RT_BUS_SECRET_CRM_PLATFORM_BFF=ci-only-value$' "$tmp/env.prod" || fail ".env.prod.example: нет RT_BUS_SECRET_CRM_PLATFORM_BFF=CHANGE_ME"

# 1. base.yml (dev-конфигурация: build есть); переменные, которые base.yml требует, — заглушки.
cp "$tmp/env.prod" "$tmp/env.dev"
cat >> "$tmp/env.dev" <<'ENV'
SERVICE_TOKEN_CRM_TO_ERP=ci-only-value
WEBHOOK_SECRET=ci-only-value
ERP_MCP_CONTEXT_KEY=ci-only-value
PLATFORM_SSO_SECRET=ci-only-value
ERP_SECRET_KEY=ci-only-value
ENV
docker compose -f "$root/infra/compose/base.yml" --env-file "$tmp/env.dev" config --format json > "$tmp/base.json"
jq -e '.services["platform-bff"].build.additional_contexts as $c
    | ($c.rtbus | endswith("/packages/rt-bus")) and ($c.contracts | endswith("/packages/contracts"))' "$tmp/base.json" >/dev/null \
  || fail "platform-bff: в base.yml нет build.additional_contexts rtbus=packages/rt-bus и contracts=packages/contracts"
for v in RT_BUS_SECRET_ERP_PLATFORM_BFF RT_BUS_SECRET_CRM_PLATFORM_BFF; do
  jq -e --arg v "$v" '.services["platform-bff"].environment[$v] == "ci-only-value"' "$tmp/base.json" >/dev/null \
    || fail "platform-bff: в окружении нет $v"
done
jq -e '.services["erp-worker"].environment.RT_BUS_SECRET_ERP_PLATFORM_BFF == "ci-only-value"' "$tmp/base.json" >/dev/null \
  || fail "erp-worker: ERP не получает секрет пары ERP → platform-bff (RT_BUS_SECRET_ERP_PLATFORM_BFF)"
jq -e '.services["crm-worker"].environment.RT_BUS_SECRET_CRM_PLATFORM_BFF == "ci-only-value"' "$tmp/base.json" >/dev/null \
  || fail "crm-worker: CRM не получает секрет пары CRM → platform-bff (RT_BUS_SECRET_CRM_PLATFORM_BFF)"
# BFF не публикует: чужих секретов у него нет, как и у издателей — секрета пары, где они подписчики не по этому имени.
jq -e '.services["platform-bff"].environment | has("RT_BUS_SECRET_ERP_CRM") | not' "$tmp/base.json" >/dev/null \
  || fail "platform-bff: получил секрет пары ERP → CRM"

# 2. prod.yml.
RT_IMAGE_TAG=platform-bus-test docker compose -f "$root/infra/compose/base.yml" -f "$root/infra/compose/prod.yml" \
  --env-file "$tmp/env.prod" config --format json > "$tmp/prod.json"
for pair in "platform-bff RT_BUS_SECRET_ERP_PLATFORM_BFF" "platform-bff RT_BUS_SECRET_CRM_PLATFORM_BFF" \
            "erp-worker RT_BUS_SECRET_ERP_PLATFORM_BFF" "crm-worker RT_BUS_SECRET_CRM_PLATFORM_BFF"; do
  set -- $pair
  jq -e --arg s "$1" --arg v "$2" '.services[$s].environment[$v] == "ci-only-value"' "$tmp/prod.json" >/dev/null \
    || fail "prod.yml: у $1 нет $2"
done

# 3. Dockerfile BFF.
dockerfile="$root/apps/platform/bff/Dockerfile"
grep -qE '^COPY --from=rtbus ' "$dockerfile" || fail "Dockerfile BFF: нет COPY --from=rtbus"
grep -qE '^COPY --from=contracts events ' "$dockerfile" || fail "Dockerfile BFF: нет COPY --from=contracts events"
grep -qE '^COPY --from=contracts bus ' "$dockerfile" || fail "Dockerfile BFF: нет COPY --from=contracts bus"
grep -q 'RT_BUS_CONTRACTS_DIR=/opt/rt/contracts/events' "$dockerfile" || fail "Dockerfile BFF: нет RT_BUS_CONTRACTS_DIR"
grep -q 'RT_BUS_SUBSCRIPTIONS=/opt/rt/contracts/bus/subscriptions.yaml' "$dockerfile" || fail "Dockerfile BFF: нет RT_BUS_SUBSCRIPTIONS"
grep -q -- '--timeout-graceful-shutdown' "$dockerfile" || fail "Dockerfile BFF: SSE без --timeout-graceful-shutdown задерживает остановку"

# 4. deploy.yml.
step="$(awk '/name: Образ rt-platform-bff/{f=1} f&&/name: Образ rt-platform-web/{exit} f{print}' "$root/.github/workflows/deploy.yml")"
grep -q 'rtbus=packages/rt-bus' <<<"$step" || fail "deploy.yml: образ rt-platform-bff собирается без build-contexts rtbus"
grep -q 'contracts=packages/contracts' <<<"$step" || fail "deploy.yml: образ rt-platform-bff собирается без build-contexts contracts"

# 5. Подписка и граница наружу.
row="$(awk '/- name: platform-bff/{f=1} f{print}' "$root/packages/contracts/bus/subscriptions.yaml")"
grep -q 'endpoint: http://platform-bff:8000/bus/v1/events' <<<"$row" || fail "subscriptions.yaml: нет строки platform-bff с адресом приёмника"
for f in Caddyfile.dev Caddyfile.prod; do
  grep -q '@bus path /bus /bus/\*' "$root/infra/caddy/$f" || fail "$f: на домене Платформы /bus/* не закрыт (404)"
done
echo "platform-bus-test: ok"
