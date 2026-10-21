#!/usr/bin/env bash
# Тест INF-P0-5: Платформа в проде.
#  1. prod.yml: platform-bff/platform-web — образы GHCR rt-platform-* по RT_IMAGE_TAG без сборки, лимиты памяти, перезапуск,
#     окружение BFF (CRM/ERP по сети compose, Redis БД 3), Caddy получает PLATFORM_DOMAIN и ждёт оба сервиса;
#  2. Caddyfile.prod: сайт {$PLATFORM_DOMAIN}, /api/* -> platform-bff:8000, остальное -> platform-web:8080 (порт образа web);
#  3. deploy.sh без PLATFORM_DOMAIN в .env.prod останавливается с понятным сообщением до обращения к docker;
#  4. smoke.sh: Платформа проверяется как четвёртый домен (/api/v1/health: 200 и status ok), три домена работают как раньше.
# Секретов не требует: env — копия .env.prod.example с заглушками. Запуск: bash этот-файл
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fail() { echo "FAIL: $*"; exit 1; }

sed 's/CHANGE_ME/ci-only-value/' "$root/infra/.env.prod.example" > "$tmp/env.prod"
grep -q '^PLATFORM_DOMAIN=platform\.railtech\.uz$' "$tmp/env.prod" || fail ".env.prod.example: нет PLATFORM_DOMAIN=platform.railtech.uz"
grep -q '^# PLATFORM_SESSION_TTL_HOURS=' "$tmp/env.prod" || fail ".env.prod.example: нет закомментированной PLATFORM_SESSION_TTL_HOURS"

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
[[ "$(q '.services["platform-bff"].environment.REDIS_URL')" == redis://:ci-only-value@redis:6379/3 ]] || fail "platform-bff: REDIS_URL не Redis БД 3 с паролем"
[[ "$(q '.services["platform-bff"].depends_on.redis.condition')" == service_healthy ]] || fail "platform-bff: нет зависимости от redis"
[[ "$(q '.services.caddy.environment.PLATFORM_DOMAIN')" == platform.railtech.uz ]] || fail "caddy: PLATFORM_DOMAIN не передан"
for svc in platform-bff platform-web; do
  [[ "$(q --arg s "$svc" '.services.caddy.depends_on[$s].condition // "none"')" == service_healthy ]] || fail "caddy не ждёт $svc"
done
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
cp "$root/packages/contracts/events.schema.json" "$rel/packages/contracts/"
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
  https://erp.test/mcp/*) code=404; body="" ;;
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
echo "platform-prod-test: ok"
