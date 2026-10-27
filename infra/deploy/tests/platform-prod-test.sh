#!/usr/bin/env bash
# Тест INF-P0-5: Платформа в проде.
#  1. prod.yml: platform-bff/platform-web — образы GHCR rt-platform-* по RT_IMAGE_TAG без сборки, лимиты памяти, перезапуск,
#     окружение BFF (CRM/ERP по сети compose, redis-cache БД 3), Caddy получает PLATFORM_DOMAIN и зависит от обоих сервисов
#     только по service_started (INF-P1-0: сбой Платформы не должен лишать входа CRM, ERP и Cabinet);
#  2. Caddyfile.prod: сайт {$PLATFORM_DOMAIN}, /api/* -> platform-bff:8000, остальное -> platform-web:8080 (порт образа web);
#  3. deploy.sh без PLATFORM_DOMAIN в .env.prod останавливается с понятным сообщением до обращения к docker;
#  4. smoke.sh: Платформа проверяется как четвёртый домен (/api/v1/health: 200 и status ok), три домена работают как раньше;
#  5. INF-P1-0: up_stack (lib.sh) — сначала стек без Платформы, затем Платформа, её сбой не роняет деплой/откат; релиз без
#     Платформы — обычный up; задание rollback в deploy.yml проверяет четыре домена, если Платформа есть в релизе отката.
# Секретов не требует: env — копия .env.prod.example с заглушками. Запуск: bash этот-файл
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fail() { echo "FAIL: $*"; exit 1; }

sed 's/CHANGE_ME/ci-only-value/' "$root/infra/.env.prod.example" > "$tmp/env.prod"
grep -q '^PLATFORM_DOMAIN=platform\.railtech\.uz$' "$tmp/env.prod" || fail ".env.prod.example: нет PLATFORM_DOMAIN=platform.railtech.uz"
grep -q '^# PLATFORM_SESSION_TTL_HOURS=' "$tmp/env.prod" || fail ".env.prod.example: нет закомментированной PLATFORM_SESSION_TTL_HOURS"
for v in PLATFORM_ERP_REFRESH_COOKIE PLATFORM_LOGIN_RATE_PER_MINUTE PLATFORM_CRM_TIMEOUT_SECONDS PLATFORM_TRUSTED_PROXIES; do
  grep -q "^# $v=" "$tmp/env.prod" || fail ".env.prod.example: нет закомментированной $v"
done
! grep -qE '^#? ?PLATFORM_COOKIE_SECURE' "$tmp/env.prod" || fail ".env.prod.example: PLATFORM_COOKIE_SECURE на проде не настраивается"

# 1. Прод-конфигурация compose.
RT_IMAGE_TAG=platform-test docker compose -f "$root/infra/compose/base.yml" -f "$root/infra/compose/prod.yml" \
  --env-file "$tmp/env.prod" config --format json > "$tmp/prod.json"
q() { jq -r "$@" "$tmp/prod.json"; }
[[ "$(q '.services["platform-bff"].image')" == ghcr.io/nzulkaynarov/rt-platform-bff:platform-test ]] || fail "platform-bff: образ не rt-platform-bff по RT_IMAGE_TAG"
[[ "$(q '.services["platform-web"].image')" == ghcr.io/nzulkaynarov/rt-platform-web:platform-test ]] || fail "platform-web: образ не rt-platform-web по RT_IMAGE_TAG"
for svc in platform-bff platform-web; do
  [[ "$(q --arg s "$svc" '.services[$s].build // "none"')" == none ]] || fail "$svc: в проде не должно быть сборки"
  [[ "$(q --arg s "$svc" '.services[$s].restart')" == unless-stopped ]] || fail "$svc: restart не unless-stopped"
  [[ "$(q --arg s "$svc" '.services[$s].healthcheck.test | length')" -gt 0 ]] || fail "$svc: нет healthcheck"
  [[ "$(q --arg s "$svc" '.services[$s].ports // "none"')" == none ]] || fail "$svc: порты наружу не публикуются"
done
[[ "$(q '.services["platform-bff"].deploy.resources.limits.memory')" == 268435456 ]] || fail "platform-bff: лимит памяти не 256M"
[[ "$(q '.services["platform-web"].deploy.resources.limits.memory')" == 67108864 ]] || fail "platform-web: лимит памяти не 64M"
[[ "$(q '.services["platform-bff"].environment.PLATFORM_CRM_URL')" == http://crm-api:8000 ]] || fail "platform-bff: PLATFORM_CRM_URL"
[[ "$(q '.services["platform-bff"].environment.PLATFORM_ERP_URL')" == http://erp-backend:8000 ]] || fail "platform-bff: PLATFORM_ERP_URL"
[[ "$(q '.services["platform-bff"].environment.REDIS_URL')" == redis://:ci-only-value@redis-cache:6379/3 ]] || fail "platform-bff: REDIS_URL не redis-cache БД 3 с паролем"
[[ "$(q '.services["platform-bff"].environment.PLATFORM_COOKIE_SECURE')" == true ]] || fail "platform-bff: на проде PLATFORM_COOKIE_SECURE не true"
[[ "$(q '.services["platform-bff"].environment.PLATFORM_ERP_REFRESH_COOKIE')" == refresh_token ]] || fail "platform-bff: PLATFORM_ERP_REFRESH_COOKIE по умолчанию не refresh_token"
[[ "$(q '.services["platform-bff"].environment.PLATFORM_LOGIN_RATE_PER_MINUTE')" == 10 ]] || fail "platform-bff: PLATFORM_LOGIN_RATE_PER_MINUTE по умолчанию не 10"
[[ "$(q '.services["platform-bff"].environment.PLATFORM_CRM_TIMEOUT_SECONDS')" == 5 ]] || fail "platform-bff: PLATFORM_CRM_TIMEOUT_SECONDS по умолчанию не 5"
[[ "$(q '.services["platform-bff"].environment.PLATFORM_TRUSTED_PROXIES')" == *10.0.0.0/8* ]] || fail "platform-bff: PLATFORM_TRUSTED_PROXIES по умолчанию без частных сетей"
# Прод не даёт выключить Secure через .env.prod: даже PLATFORM_COOKIE_SECURE=false в файле остаётся true.
{ cat "$tmp/env.prod"; echo 'PLATFORM_COOKIE_SECURE=false'; } > "$tmp/env.insecure"
[[ "$(RT_IMAGE_TAG=platform-test docker compose -f "$root/infra/compose/base.yml" -f "$root/infra/compose/prod.yml" --env-file "$tmp/env.insecure" \
  config --format json | jq -r '.services["platform-bff"].environment.PLATFORM_COOKIE_SECURE')" == true ]] || fail "prod.yml позволил выключить PLATFORM_COOKIE_SECURE из .env.prod"
# dev-стенд (http): Secure выключен по умолчанию, явное значение в .env побеждает.
grep -v '^#' "$root/.env.example" | sed 's/CHANGE_ME/ci-only-value/' > "$tmp/env.dev"
dev_secure() { docker compose -f "$root/infra/compose/base.yml" -f "$root/infra/compose/dev.yml" --env-file "$1" config --format json \
  | jq -r '.services["platform-bff"].environment.PLATFORM_COOKIE_SECURE'; }
[[ "$(dev_secure "$tmp/env.dev")" == false ]] || fail "dev: на http-стенде PLATFORM_COOKIE_SECURE должен быть false по умолчанию"
dev_crm_env() { docker compose -f "$root/infra/compose/base.yml" -f "$root/infra/compose/dev.yml" --env-file "$1" config --format json \
  | jq -r --arg k "$2" '.services["crm-api"].environment[$k]'; }
[[ "$(dev_crm_env "$tmp/env.dev" PLATFORM_PUBLIC_URL)" == "http://platform.localhost:$(sed -n 's/^HTTP_PORT=//p' "$tmp/env.dev")" ]] \
  || fail "dev: PLATFORM_PUBLIC_URL должен быть http://platform.localhost:\${HTTP_PORT}"
echo 'PLATFORM_COOKIE_SECURE=true' >> "$tmp/env.dev"
[[ "$(dev_secure "$tmp/env.dev")" == true ]] || fail "dev: PLATFORM_COOKIE_SECURE=true из .env не применился"
[[ "$(q '.services["platform-bff"].depends_on["redis-cache"].condition')" == service_healthy ]] || fail "platform-bff: нет зависимости от redis-cache"
[[ "$(q '.services.caddy.environment.PLATFORM_DOMAIN')" == platform.railtech.uz ]] || fail "caddy: PLATFORM_DOMAIN не передан"
# W15-H8a: письма сотрудникам (приглашение, сброс пароля) ведут в Платформу — адрес из PLATFORM_DOMAIN во всех сервисах CRM.
for svc in crm-api crm-worker crm-bot; do
  [[ "$(q --arg s "$svc" '.services[$s].environment.PLATFORM_PUBLIC_URL')" == https://platform.railtech.uz ]] \
    || fail "$svc: PLATFORM_PUBLIC_URL не выведен из PLATFORM_DOMAIN"
  [[ "$(q --arg s "$svc" '.services[$s].environment.CRM_PUBLIC_URL')" == https://crm.railtech.uz ]] \
    || fail "$svc: CRM_PUBLIC_URL не выведен из CRM_DOMAIN"
done
for svc in platform-bff platform-web; do
  [[ "$(q --arg s "$svc" '.services.caddy.depends_on[$s].condition // "none"')" == service_started ]] \
    || fail "caddy должен зависеть от $svc по service_started (не service_healthy: INF-P1-0)"
done
# Остальное, без чего вход бессмыслен, Caddy по-прежнему ждёт по здоровью.
for svc in crm-api crm-web erp-backend erp-web cabinet-web; do
  [[ "$(q --arg s "$svc" '.services.caddy.depends_on[$s].condition // "none"')" == service_healthy ]] || fail "caddy не ждёт $svc по service_healthy"
done
# Ничто критичное, кроме самой Платформы, не зависит от её сервисов.
[[ "$(q '[.services | to_entries[] | select(.key | startswith("platform-") | not) | select(.value.depends_on // {} | has("platform-bff") or has("platform-web")) | .key] | join(",")')" == caddy ]] \
  || fail "от platform-* зависит не только caddy"

# Домен обязателен: без него compose не разбирается (а deploy.sh говорит об этом понятнее — п. 3).
grep -v '^PLATFORM_DOMAIN=' "$tmp/env.prod" > "$tmp/env.nodomain"
if RT_IMAGE_TAG=platform-test docker compose -f "$root/infra/compose/base.yml" -f "$root/infra/compose/prod.yml" \
  --env-file "$tmp/env.nodomain" config -q 2>/dev/null; then fail "compose прод разобрался без PLATFORM_DOMAIN"; fi

# 2. Caddyfile.prod: маршруты и порт образа web.
caddyfile="$root/infra/caddy/Caddyfile.prod"
site="$(awk '/^\{\$PLATFORM_DOMAIN[:}]/{f=1} f{print} f&&/^}/{exit}' "$caddyfile")"
[[ -n "$site" ]] || fail "Caddyfile.prod: нет сайта {\$PLATFORM_DOMAIN}"
grep -q 'reverse_proxy platform-bff:8000' <<<"$site" || fail "Caddyfile.prod: /api/* не ведёт на platform-bff:8000"
grep -q 'flush_interval -1' <<<"$site" || fail "Caddyfile.prod: нет flush_interval -1 для SSE"
grep -q 'reverse_proxy platform-web:8080' <<<"$site" || fail "Caddyfile.prod: статика не ведёт на platform-web:8080"
grep -q 'import security_headers' <<<"$site" || fail "Caddyfile.prod: у Платформы нет security_headers (HSTS)"
grep -q 'import no_mcp' <<<"$site" || fail "Caddyfile.prod: у Платформы нет no_mcp"
grep -q 'Content-Security-Policy' <<<"$site" || fail "Caddyfile.prod: у Платформы нет CSP"
grep -q '^:8080 {' "$root/apps/platform/web/Caddyfile" || fail "порт file-server образа platform-web изменился: поправьте Caddyfile.prod и healthcheck"

# 3. deploy.sh без PLATFORM_DOMAIN — отказ до docker (docker подменён заглушкой, которая фиксирует вызов).
rel="$tmp/releases/tag1"; mkdir -p "$rel/infra" "$rel/packages/contracts" "$tmp/bin"
cp -R "$root/infra/deploy" "$rel/infra/deploy"
cp "$root/packages/contracts/mcp-tools.json" "$rel/packages/contracts/"
printf '#!/usr/bin/env bash\necho "docker вызван: $*" >> "%s/docker.log"\nexit 1\n' "$tmp" > "$tmp/bin/docker"; chmod +x "$tmp/bin/docker"
run() { PATH="$tmp/bin:$PATH" RT_ENV_FILE="$1" RT_STATE="$tmp/state" bash "$rel/infra/deploy/deploy.sh" tag1 >"$tmp/log" 2>&1; }
mkenv() { sed -E "s/192\.0\.2\./10.0.0./g" "$1" > "$tmp/env"; chmod 600 "$tmp/env"; }
mkenv "$tmp/env.nodomain"
if run "$tmp/env"; then fail "deploy.sh прошёл без PLATFORM_DOMAIN"; fi
grep -q 'PLATFORM_DOMAIN' "$tmp/log" || { cat "$tmp/log"; fail "deploy.sh: в сообщении нет имени PLATFORM_DOMAIN"; }
[[ ! -e "$tmp/docker.log" ]] || fail "deploy.sh дошёл до docker до проверки PLATFORM_DOMAIN"
{ cat "$tmp/env.nodomain"; echo 'PLATFORM_DOMAIN='; } > "$tmp/env.empty"; mkenv "$tmp/env.empty"
if run "$tmp/env"; then fail "deploy.sh прошёл с пустым PLATFORM_DOMAIN"; fi
grep -q 'PLATFORM_DOMAIN' "$tmp/log" || fail "deploy.sh: пустое значение не названо в сообщении"
[[ ! -e "$tmp/docker.log" ]] || fail "deploy.sh дошёл до docker при пустом PLATFORM_DOMAIN"
# С доменом проверка проходит: deploy.sh идёт дальше и падает уже на заглушке docker.
mkenv "$tmp/env.prod"
if run "$tmp/env"; then fail "заглушка docker должна была остановить deploy.sh"; fi
[[ -e "$tmp/docker.log" ]] || { cat "$tmp/log"; fail "с PLATFORM_DOMAIN deploy.sh не дошёл до docker"; }
! grep -q 'нет PLATFORM_DOMAIN' "$tmp/log" || fail "deploy.sh ругается на PLATFORM_DOMAIN, хотя он задан"

# 4. smoke.sh: curl подменён; Платформа — четвёртый домен.
cat > "$tmp/bin/curl" <<'STUB'
#!/usr/bin/env bash
url="${*: -1}"; fmt=0; for a in "$@"; do [[ "$a" == -w ]] && fmt=1; done
case "$url" in
  https://plat.test/api/v1/health) code=200; body="${RT_TEST_PLATFORM_BODY:-{\"status\":\"ok\"\}}" ;;
  https://plat.test/mcp/*) code=404; body="" ;;
  https://erp.test/mcp/*|https://erp.test/api/integration/*|https://erp.test/admin/*) code=404; body="" ;;
  *) code=200; body="ok" ;;
esac
if [[ $fmt -eq 1 ]]; then printf '%s' "$code"; else printf '%s' "$body"; fi
STUB
chmod +x "$tmp/bin/curl"
smoke() { PATH="$tmp/bin:$PATH" bash "$root/infra/deploy/smoke.sh" --retries 1 "$@" >"$tmp/smoke.log" 2>&1; }
smoke --domains crm.test erp.test cab.test plat.test || { cat "$tmp/smoke.log"; fail "smoke.sh: четыре домена со status ok должны проходить"; }
grep -q 'plat.test .*/api/v1/health' "$tmp/smoke.log" || fail "smoke.sh: Платформа не проверялась"
smoke --domains crm.test erp.test cab.test || { cat "$tmp/smoke.log"; fail "smoke.sh: три домена (откат на релиз до Платформы) должны проходить"; }
! grep -q 'plat.test' "$tmp/smoke.log" || fail "smoke.sh: при трёх доменах проверяется Платформа"
if RT_TEST_PLATFORM_BODY='{"status":"degraded"}' smoke --domains crm.test erp.test cab.test plat.test; then fail "smoke.sh: status degraded у Платформы должен падать"; fi
if smoke --domains crm.test erp.test; then fail "smoke.sh: два домена должны отвергаться"; fi

# 5. INF-P1-0: up_stack — docker подменён заглушкой, которая пишет вызовы и по переменным имитирует сбои.
mkdir -p "$tmp/bin5"
cat > "$tmp/bin5/docker" <<'STUB'
#!/usr/bin/env bash
echo "$*" >> "$RT_TEST_DOCKER_LOG"
case " $* " in
  *" config --services "*) printf '%s\n' $RT_TEST_SERVICES; exit 0 ;;
  *" --no-deps platform-bff "*) [[ -z "${RT_TEST_FAIL_PLATFORM:-}" ]] || { echo "exec: no such file" >&2; exit 1; } ;;
  *" --scale "*) [[ -z "${RT_TEST_FAIL_CORE:-}" ]] || exit 1 ;;
esac
exit 0
STUB
chmod +x "$tmp/bin5/docker"
cp "$tmp/env.prod" "$tmp/env5"; chmod 600 "$tmp/env5"
up5() { # переменные RT_TEST_* — из окружения вызова; результат — код возврата up_stack
  # Отдельный bash: set -e действует, как в deploy.sh/rollback.sh, даже если up5 вызвана в условии (if/||).
  : > "$tmp/docker5.log"
  PATH="$tmp/bin5:$PATH" RT_ENV_FILE="$tmp/env5" RT_TEST_DOCKER_LOG="$tmp/docker5.log" \
    bash -c 'set -euo pipefail; source "$1/infra/deploy/lib.sh"; up_stack "$2"' _ "$root" "$tmp/rel" >"$tmp/up5.log" 2>&1
}
export RT_TEST_SERVICES="crm-api caddy platform-bff platform-web"
up5 || { cat "$tmp/up5.log"; fail "up_stack: штатный запуск с Платформой упал"; }
[[ "$(grep -c ' up ' "$tmp/docker5.log")" == 2 ]] || fail "up_stack: ожидалось два up (стек без Платформы, затем Платформа)"
grep ' up ' "$tmp/docker5.log" | sed -n 1p | grep -q -- '--scale platform-bff=0 --scale platform-web=0' || fail "up_stack: первый up не выключает Платформу (--scale …=0)"
! grep ' up ' "$tmp/docker5.log" | sed -n 1p | grep -q -- '--no-deps' || fail "up_stack: первый up с --no-deps (потеряется порядок запуска)"
grep ' up ' "$tmp/docker5.log" | sed -n 2p | grep -q -- 'up -d --no-deps platform-bff platform-web' || fail "up_stack: второй up не поднимает только Платформу"
RT_TEST_FAIL_PLATFORM=1 up5 || { cat "$tmp/up5.log"; fail "up_stack: сбой запуска Платформы не должен ронять деплой/откат"; }
grep -q 'Платформа не поднялась' "$tmp/up5.log" || fail "up_stack: сбой Платформы не отмечен в журнале"
if RT_TEST_FAIL_CORE=1 up5; then fail "up_stack: сбой запуска CRM/ERP/Cabinet/Caddy должен ронять деплой"; fi
RT_TEST_SERVICES="crm-api caddy" up5 || fail "up_stack: релиз без Платформы упал"
[[ "$(grep -c ' up ' "$tmp/docker5.log")" == 1 ]] && ! grep -q -- '--scale' "$tmp/docker5.log" || fail "up_stack: релиз без Платформы — ожидался один обычный up"
grep -q 'up -d --remove-orphans' "$tmp/docker5.log" || fail "up_stack: релиз без Платформы — нет up -d --remove-orphans"
grep -q 'up_stack "\$rel"' "$root/infra/deploy/deploy.sh" || fail "deploy.sh не использует up_stack"
grep -q 'up_stack "\$rel"' "$root/infra/deploy/rollback.sh" || fail "rollback.sh не использует up_stack"

# deploy.yml, задание rollback: домен Платформы известен заданию, smoke — четыре домена, если Платформа есть в релизе отката.
rb="$(awk '/^  rollback:/{f=1} f{print}' "$root/.github/workflows/deploy.yml")"
grep -q 'PLATFORM_DOMAIN: ' <<<"$rb" || fail "deploy.yml: у задания rollback нет PLATFORM_DOMAIN"
grep -q 'domains+=("\$PLATFORM_DOMAIN")' <<<"$rb" || fail "deploy.yml: smoke отката не добавляет домен Платформы"
grep -q 'platform-bff:' <<<"$rb" || fail "deploy.yml: smoke отката не различает релиз с Платформой и без"
! grep -q 'Smoke трёх доменов' <<<"$rb" || fail "deploy.yml: в rollback остался smoke только трёх доменов"
echo "platform-prod-test: ok"
