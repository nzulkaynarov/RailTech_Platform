#!/usr/bin/env bash
# Тест S0-2: Redis раздельно (ADR-0013 п. 5, ADR-0017). Секретов не требует: env — копия примеров с заглушками.
#  1. Старого сервиса `redis` и общей переменной REDIS_PASSWORD нет; есть `redis-broker` и `redis-cache`, у каждого свой пароль.
#  2. Брокер: appendonly yes, noeviction, maxmemory, том для AOF. Кэш: volatile-lru, maxmemory; healthcheck у обоих.
#  3. Потребители смотрят на «свой» экземпляр со «своим» паролем: Celery и Channels ERP — брокер, кэш ERP, сессии BFF и
#     Langfuse (BullMQ, отдельной БД 3, S0-9) — брокер (noeviction); ни один адрес не ведёт на `redis`.
#  4. Прод: лимиты памяти больше maxmemory; erp-backend ждёт брокер по здоровью и кэш только по запуску (ERP живёт без кэша).
#  5. Dev: оба экземпляра опубликованы на 127.0.0.1 на разных портах.
#  6. make-env-prod.sh init выдаёт разные случайные пароли двум экземплярам.
# Запуск: bash этот-файл
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fail() { echo "FAIL: $*"; exit 1; }
base="$root/infra/compose/base.yml"; prod="$root/infra/compose/prod.yml"; dev="$root/infra/compose/dev.yml"

for example in "$root/.env.example" "$root/infra/.env.prod.example"; do
  grep -q '^REDIS_BROKER_PASSWORD=CHANGE_ME$' "$example" || fail "$example: нет REDIS_BROKER_PASSWORD=CHANGE_ME"
  grep -q '^REDIS_CACHE_PASSWORD=CHANGE_ME$' "$example" || fail "$example: нет REDIS_CACHE_PASSWORD=CHANGE_ME"
  ! grep -q '^REDIS_PASSWORD=' "$example" || fail "$example: остался общий REDIS_PASSWORD"
done

# Окружение с РАЗНЫМИ паролями: по ним видно, какой экземпляр кому достался.
mkenv() { # mkenv <пример> <выход>
  sed 's/CHANGE_ME/ci-only-value/' "$1" | grep -vE '^REDIS_(BROKER|CACHE)_PASSWORD=' > "$2"
  printf 'REDIS_BROKER_PASSWORD=brokerpw\nREDIS_CACHE_PASSWORD=cachepw\n' >> "$2"
}
mkenv "$root/infra/.env.prod.example" "$tmp/env.prod"
grep -v '^#' "$root/.env.example" | grep -v '^$' > "$tmp/env.dev.raw"; mkenv "$tmp/env.dev.raw" "$tmp/env.dev"

export RT_IMAGE_TAG=redis-split-test
profiles=(--profile observability --profile kb-ingest --profile mcp)
docker compose -f "$base" -f "$prod" --env-file "$tmp/env.prod" "${profiles[@]}" config --format json > "$tmp/prod.json"
docker compose -f "$base" -f "$dev" --env-file "$tmp/env.dev" --profile observability config --format json > "$tmp/dev.json"
q() { jq -r "$@" "$tmp/prod.json"; }
qd() { jq -r "$@" "$tmp/dev.json"; }

# 1. Состав.
for f in prod dev; do
  [[ "$(jq -r '.services | has("redis")' "$tmp/$f.json")" == false ]] || fail "$f: остался сервис redis"
  for svc in redis-broker redis-cache; do
    [[ "$(jq -r --arg s "$svc" '.services | has($s)' "$tmp/$f.json")" == true ]] || fail "$f: нет сервиса $svc"
  done
done
[[ "$(q '.services["redis-broker"].image')" == "$(q '.services["redis-cache"].image')" ]] || fail "образы экземпляров разные"

# 2. Политики.
args() { q --arg s "$1" '.services[$s].command | join(" ")'; }
b="$(args redis-broker)"; c="$(args redis-cache)"
grep -q -- '--requirepass brokerpw' <<<"$b" || fail "redis-broker: пароль не REDIS_BROKER_PASSWORD"
grep -q -- '--requirepass cachepw' <<<"$c" || fail "redis-cache: пароль не REDIS_CACHE_PASSWORD"
[[ "$b" != *cachepw* && "$c" != *brokerpw* ]] || fail "пароль одного экземпляра попал в команду другого"
grep -q -- '--appendonly yes' <<<"$b" || fail "redis-broker: нет appendonly yes"
grep -q -- '--maxmemory-policy noeviction' <<<"$b" || fail "redis-broker: политика не noeviction"
grep -qE -- '--maxmemory [0-9]+mb' <<<"$b" || fail "redis-broker: не задан maxmemory"
grep -q -- '--maxmemory-policy volatile-lru' <<<"$c" || fail "redis-cache: политика не volatile-lru"
grep -qE -- '--maxmemory [0-9]+mb' <<<"$c" || fail "redis-cache: не задан maxmemory"
grep -q -- '--appendonly no' <<<"$c" || fail "redis-cache: AOF должен быть выключен (кэш)"
[[ "$(q '.services["redis-broker"].volumes[0].source')" == redis_broker_data ]] || fail "redis-broker: нет тома для AOF"
[[ "$(q '.services["redis-broker"].volumes[0].target')" == /data ]] || fail "redis-broker: том не в /data"
for svc in redis-broker redis-cache; do
  [[ "$(q --arg s "$svc" '.services[$s].healthcheck.test | length')" -gt 0 ]] || fail "$svc: нет healthcheck"
  [[ "$(q --arg s "$svc" '.services[$s].ports // "none"')" == none ]] || fail "$svc: на проде порты наружу не публикуются"
  [[ "$(q --arg s "$svc" '.services[$s].restart')" == unless-stopped ]] || fail "$svc: restart не unless-stopped"
done

# 3. Потребители.
env_of() { q --arg s "$1" --arg k "$2" '.services[$s].environment[$k] // "none"'; }
[[ "$(env_of erp-backend REDIS_CACHE_URL)" == redis://:cachepw@redis-cache:6379/0 ]] || fail "erp-backend: REDIS_CACHE_URL"
[[ "$(env_of erp-backend REDIS_CHANNELS_URL)" == redis://:brokerpw@redis-broker:6379/2 ]] || fail "erp-backend: REDIS_CHANNELS_URL"
[[ "$(env_of erp-backend CELERY_BROKER_URL)" == redis://:brokerpw@redis-broker:6379/1 ]] || fail "erp-backend: CELERY_BROKER_URL"
[[ "$(env_of erp-backend CELERY_RESULT_BACKEND)" == redis://:brokerpw@redis-broker:6379/1 ]] || fail "erp-backend: CELERY_RESULT_BACKEND"
[[ "$(env_of platform-bff REDIS_URL)" == redis://:cachepw@redis-cache:6379/3 ]] || fail "platform-bff: REDIS_URL"
for svc in langfuse-web langfuse-worker; do
  # Очередь BullMQ вытеснять нельзя: брокер (noeviction, AOF), своя БД 3 — не Celery (1) и не Channels (2).
  [[ "$(env_of "$svc" REDIS_CONNECTION_STRING)" == redis://:brokerpw@redis-broker:6379/3 ]] || fail "$svc: Langfuse не на redis-broker БД 3"
  [[ "$(env_of "$svc" REDIS_HOST)" == none ]] || fail "$svc: остался REDIS_HOST (БД не выбрать)"
done
# Все ERP-сервисы на одном образе получают те же адреса (воркеры, Beat, MCP): окружение общее.
for svc in erp-worker erp-worker-ai erp-beat erp-mcp erp-ai-gateway; do
  [[ "$(env_of "$svc" CELERY_BROKER_URL)" == redis://:brokerpw@redis-broker:6379/1 ]] || fail "$svc: CELERY_BROKER_URL"
  [[ "$(env_of "$svc" REDIS_CACHE_URL)" == redis://:cachepw@redis-cache:6379/0 ]] || fail "$svc: REDIS_CACHE_URL"
done
# Нигде не осталось адреса старого сервиса, и пароль экземпляра не уходит чужим потребителям.
[[ "$(jq -r '[.services[] | .environment // {} | to_entries[] | select(.value | tostring | test("@redis:|REDIS_HOST"))] | length' "$tmp/prod.json")" == 0 ]] \
  || fail "в окружении остался адрес старого сервиса redis"
leak="$(jq -r '[.services | to_entries[] | select(.value.environment // {} | tostring | test("brokerpw")) | .key] | sort | join(",")' "$tmp/prod.json")"
[[ "$leak" == erp-ai-gateway,erp-backend,erp-beat,erp-mcp,erp-worker,erp-worker-ai,langfuse-web,langfuse-worker,redis-broker ]] || fail "пароль брокера у лишних сервисов: $leak"
leak="$(jq -r '[.services | to_entries[] | select(.value.environment // {} | tostring | test("cachepw")) | .key] | sort | join(",")' "$tmp/prod.json")"
[[ "$leak" == erp-ai-gateway,erp-backend,erp-beat,erp-mcp,erp-worker,erp-worker-ai,platform-bff,redis-cache ]] || fail "пароль кэша у лишних сервисов: $leak"

# 4. Прод: лимиты, зависимости.
[[ "$(q '.services["redis-broker"].deploy.resources.limits.memory')" == 268435456 ]] || fail "redis-broker: лимит памяти не 256M"
[[ "$(q '.services["redis-cache"].deploy.resources.limits.memory')" == 201326592 ]] || fail "redis-cache: лимит памяти не 192M"
[[ "$(q '.services["erp-backend"].depends_on["redis-broker"].condition')" == service_healthy ]] || fail "erp-backend: не ждёт брокер по здоровью"
[[ "$(q '.services["erp-backend"].depends_on["redis-cache"].condition')" == service_started ]] || fail "erp-backend: кэш должен ждаться только по запуску (ERP живёт без кэша)"
for svc in langfuse-web langfuse-worker; do
  [[ "$(q --arg s "$svc" '.services[$s].depends_on["redis-broker"].condition')" == service_healthy ]] || fail "$svc: не ждёт redis-broker"
  [[ "$(q --arg s "$svc" '.services[$s].depends_on | has("redis-cache")')" == false ]] || fail "$svc: зависит от redis-cache, а Langfuse теперь на брокере"
done

# 5. Dev: порты на 127.0.0.1, разные.
bp="$(qd '.services["redis-broker"].ports[0] | "\(.host_ip):\(.published)"')"; cp="$(qd '.services["redis-cache"].ports[0] | "\(.host_ip):\(.published)"')"
[[ "$bp" == 127.0.0.1:* && "$cp" == 127.0.0.1:* && "$bp" != "$cp" ]] || fail "dev: порты redis-broker/redis-cache: $bp / $cp"

# 6. Генерация паролей.
file="$tmp/generated.env"
bash "$root/infra/deploy/make-env-prod.sh" init "$file" >/dev/null
gb="$(grep '^REDIS_BROKER_PASSWORD=' "$file" | cut -d= -f2-)"; gc="$(grep '^REDIS_CACHE_PASSWORD=' "$file" | cut -d= -f2-)"
[[ -n "$gb" && -n "$gc" && "$gb" != CHANGE_ME && "$gc" != CHANGE_ME ]] || fail "make-env-prod.sh init не сгенерировал пароли Redis"
[[ "$gb" != "$gc" ]] || fail "make-env-prod.sh init выдал одинаковые пароли двум экземплярам"
echo "redis-split-test: ok"
