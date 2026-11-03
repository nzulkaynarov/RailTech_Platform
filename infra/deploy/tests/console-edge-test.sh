#!/usr/bin/env bash
# Тест OPS-CONSOLE: служебные консоли на домене Платформы (/console/<ключ>/) в Caddyfile.prod и Caddyfile.dev.
#  1. Без сессии Платформы консоль недоступна: 302 на /login, до сервиса запрос не доходит; сотрудник без права — 403.
#  2. Администратор доходит до LiteLLM (/console/litellm/*) и Django admin ERP (/console/erp/admin, /console/erp/static);
#     путь уходит в сервис целиком, cookie Платформы (rt_pf_session, rt_pf_csrf) — нет, свои cookie консоли — да.
#  3. Под /console/erp открыт только admin/ и static/; /console/rustfs и прочее — 404 даже администратору.
#  4. CSP консоли ('unsafe-eval') — только на её пути; остальной сайт Платформы — прежняя строгая CSP, X-Frame-Options DENY.
#  5. Обходы (двойной слэш, регистр, кодирование) не открывают консоль без сессии.
# Без стенда: caddy из образа make deploy-check, заглушки BFF (решение forward_auth по cookie) и сервисов (эхо пути и
# Cookie) — тот же образ. Всё с суффиксом процесса, удаляется при выходе. Секретов не требует. Запуск: bash этот-файл
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
image="${CADDY_IMAGE:-caddy:2.11.7-alpine}"
tag="rt-ops-console-$$"
tmp="$(mktemp -d)"
cleanup() {
  docker rm -f "$tag-caddy" "$tag-platform-bff" "$tag-platform-web" "$tag-litellm" "$tag-erp-backend" >/dev/null 2>&1 || true
  docker network rm "$tag" >/dev/null 2>&1 || true
  rm -rf "$tmp"
}
trap cleanup EXIT
fail() { echo "FAIL: $*"; exit 1; }

docker network create "$tag" >/dev/null
stub() { # имя сервиса (алиас в сети), файл Caddyfile заглушки
  docker run -d --rm --name "$tag-$1" --network "$tag" --network-alias "$1" -v "$2:/etc/caddy/Caddyfile:ro" "$image" >/dev/null
}
# BFF: forward_auth решает по cookie (admin — 204, staff — 403, иначе 401), как app/api/consoles.py.
cat >"$tmp/bff" <<'CADDY'
{
	admin off
	auto_https off
}
:8000 {
	@admin header_regexp Cookie (^|;\s*)rt_pf_session=admin(;|$)
	@staff header_regexp Cookie (^|;\s*)rt_pf_session=staff(;|$)
	route /api/v1/consoles/*/auth {
		header Cache-Control no-store
		respond @admin 204
		respond @staff "FORBIDDEN" 403
		respond "SESSION_EXPIRED" 401
	}
	respond "PLATFORM-BFF" 200
}
CADDY
echo_stub() { # имя, порт, метка
  cat >"$tmp/$1" <<CADDY
{
	admin off
	auto_https off
}
:$2 {
	respond "$3 {http.request.uri.path} cookie=[{http.request.header.Cookie}]" 200
}
CADDY
}
echo_stub litellm 4000 LITELLM
echo_stub erp-backend 8000 ERP-BACKEND
echo_stub platform-web 8080 PLATFORM-WEB
stub platform-bff "$tmp/bff"
stub litellm "$tmp/litellm"
stub erp-backend "$tmp/erp-backend"
stub platform-web "$tmp/platform-web"

port=""
label=""
start_caddy() { # Caddyfile, [-e VAR=значение ...]
  local file="$1"; shift
  docker rm -f "$tag-caddy" >/dev/null 2>&1 || true
  docker run -d --name "$tag-caddy" --network "$tag" -p 127.0.0.1::80 "$@" \
    -v "$file:/etc/caddy/Caddyfile:ro" "$image" >/dev/null
  port="$(docker port "$tag-caddy" 80/tcp | head -n1 | sed 's/.*://')"
  local i code
  for i in $(seq 1 30); do
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 -H 'Host: probe.invalid' "http://127.0.0.1:$port/" 2>/dev/null || true)"
    [[ "$code" != 000 && -n "$code" ]] && return 0
    sleep 1
  done
  docker logs "$tag-caddy" 2>&1 | tail -n 20
  fail "caddy не поднялся с $file"
}

# req <Host> <путь> [cookie] -> заголовки и тело в $tmp/h, $tmp/b; печатает код
req() {
  local args=(-s --path-as-is --max-time 5 -H "Host: $1" -D "$tmp/h" -o "$tmp/b" -w '%{http_code}')
  [[ -n "${3:-}" ]] && args+=(-H "Cookie: $3")
  curl "${args[@]}" "http://127.0.0.1:$port$2" 2>/dev/null || true
}
header() { grep -i "^$1:" "$tmp/h" | head -n1 | cut -d' ' -f2- | tr -d '\r' || true; }
body() { cat "$tmp/b"; }

check_consoles() { # <Platform-host>
  local h="$1" code p
  echo "[$label]"
  # 1. Без сессии — на вход, до сервиса не доходит; сотрудник — 403.
  for p in /console/litellm/ui/ /console/litellm/v1/models /console/erp/admin/ /console/erp/static/admin/css/base.css; do
    code="$(req "$h" "$p")"
    [[ "$code" == 302 && "$(header Location)" == /login ]] || fail "$label: аноним $p -> $code $(header Location)"
    [[ "$(body)" != *LITELLM* && "$(body)" != *ERP-BACKEND* ]] || fail "$label: аноним $p дошёл до сервиса"
    code="$(req "$h" "$p" "rt_pf_session=staff")"
    [[ "$code" == 403 && "$(body)" == FORBIDDEN ]] || fail "$label: сотрудник $p -> $code $(body)"
    echo "  ok  $p: аноним 302 /login, сотрудник 403"
  done
  # 2. Администратор — до сервиса, путь целиком, без cookie Платформы.
  code="$(req "$h" /console/litellm/ui/ "rt_pf_session=admin; token=console-own; rt_pf_csrf=c1")"
  [[ "$code" == 200 && "$(body)" == "LITELLM /console/litellm/ui/ cookie=["* && "$(body)" == *token=console-own* \
     && "$(body)" != *rt_pf_* ]] || fail "$label: админ litellm -> $code «$(body)»"
  [[ "$(header Content-Security-Policy)" == *"'unsafe-eval'"* ]] || fail "$label: нет CSP консоли LiteLLM"
  [[ "$(header X-Frame-Options)" == DENY ]] || fail "$label: консоль без X-Frame-Options DENY"
  echo "  ok  админ /console/litellm/ui/ -> LiteLLM, cookie Платформы срезаны, CSP консоли"
  for p in /console/erp/admin /console/erp/admin/login/ /console/erp/static/admin/css/base.css; do
    code="$(req "$h" "$p" "rt_pf_session=admin")"
    [[ "$code" == 200 && "$(body)" == "ERP-BACKEND $p cookie=[]" ]] || fail "$label: админ $p -> $code «$(body)»"
    echo "  ok  админ $p -> erp-backend"
  done
  # 3. Под /console/erp — только admin/ и static/; прочие консоли — 404.
  for p in /console/erp/api/v1/health /console/erp/api/integration/v1/health /console/erp/bus/v1/events /console/erp/ \
           /console/erp/administrator /console/rustfs/ /console/langfuse/ /console/ /console; do
    code="$(req "$h" "$p" "rt_pf_session=admin")"
    [[ "$code" == 404 && "$(body)" != *ERP-BACKEND* && "$(body)" != *LITELLM* ]] || fail "$label: админ $p -> $code «$(body)»"
  done
  echo "  ok  /console/erp/{api,bus,…}, /console/rustfs, /console/langfuse -> 404"
  # 4. Остальной сайт — прежняя строгая CSP.
  code="$(req "$h" /dashboard/queue)"
  [[ "$code" == 200 && "$(body)" == *PLATFORM-WEB* ]] || fail "$label: SPA -> $code"
  [[ "$(header Content-Security-Policy)" != *unsafe-eval* && "$(header Content-Security-Policy)" == *"script-src 'self';"* ]] \
    || fail "$label: CSP SPA ослаблена: $(header Content-Security-Policy)"
  echo "  ok  CSP SPA строгая"
  # 5. Обходы без сессии.
  for p in //console/litellm/ui/ /CONSOLE/litellm/ui/ /Console/erp/admin/ /console/%6citellm/ui/ /console/erp/%61dmin/ \
           /console/./litellm/ui/ /api/../console/litellm/ui/; do
    code="$(req "$h" "$p")"
    [[ "$(body)" != *LITELLM* && "$(body)" != *ERP-BACKEND* ]] || fail "$label: обход $p дошёл до сервиса ($code)"
  done
  echo "  ok  обходы без сессии не доходят до сервисов"
}

label="Caddyfile.prod"
start_caddy "$root/infra/caddy/Caddyfile.prod" -e ACME_EMAIL=a@example.com \
  -e CRM_DOMAIN=http://crm.example.org -e ERP_DOMAIN=http://erp.example.org \
  -e CABINET_DOMAIN=http://cabinet.example.org -e PLATFORM_DOMAIN=http://platform.example.org
check_consoles platform.example.org

label="Caddyfile.dev"
start_caddy "$root/infra/caddy/Caddyfile.dev"
check_consoles platform.localhost

echo "console-edge-test: ok"
