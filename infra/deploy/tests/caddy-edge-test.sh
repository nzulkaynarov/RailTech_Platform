#!/usr/bin/env bash
# Тест S0-5: граница наружу в Caddyfile.prod и Caddyfile.dev.
#  1. Домен ERP: /api/integration (машинный API, ходит только CRM по сети compose) и /admin (Django admin) снаружи — 404;
#     /api/v1/* (включая /api/v1/admin/email-templates/ — это API, не /admin), /api/portal/*, /ws/*, /static/*, /media/*,
#     /health работают как раньше (доходят до erp-backend), остальное — SPA (erp-web).
#  2. Через домены Cabinet и Платформы эти пути до erp-backend не доходят.
#  3. Служебные пути не обходятся через двойной слэш, регистр и кодирование.
# Без полного стенда: один контейнер caddy из образа make deploy-check + заглушки апстримов (тот же образ, `caddy respond`)
# в одноразовой сети. Все имена с суффиксом процесса, всё удаляется при выходе. Секретов не требует. Запуск: bash этот-файл
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
image="${CADDY_IMAGE:-caddy:2.11.7-alpine}"
tag="rt-s0-5-edge-$$"
cleanup() {
  docker rm -f "$tag-caddy" "$tag-erp-backend" "$tag-erp-web" "$tag-cabinet-web" "$tag-platform-web" "$tag-platform-bff" \
    "$tag-crm-api" >/dev/null 2>&1 || true
  docker network rm "$tag" >/dev/null 2>&1 || true
}
trap cleanup EXIT
fail() { echo "FAIL: $*"; exit 1; }

docker network create "$tag" >/dev/null
stub() { # имя сервиса (алиас в сети), порт, тело ответа
  docker run -d --rm --name "$tag-$1" --network "$tag" --network-alias "$1" "$image" \
    caddy respond --listen ":$2" --status 200 --body "$3" >/dev/null
}
stub erp-backend 8000 ERP-BACKEND
stub erp-web 80 ERP-WEB
stub cabinet-web 80 CABINET-WEB
stub platform-web 8080 PLATFORM-WEB
stub platform-bff 8000 PLATFORM-BFF
stub crm-api 8000 CRM-API

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

# get <Host> <путь> -> «код тело»; --path-as-is: curl не нормализует ../ и // в пути
get() {
  local out
  out="$(curl -s --path-as-is --max-time 5 -H "Host: $1" -w ' %{http_code}' "http://127.0.0.1:$port$2" 2>/dev/null || true)"
  printf '%s %s' "${out##* }" "${out% *}"
}
expect() { # <Host> <путь> <код> [тело]
  local got; got="$(get "$1" "$2")"
  [[ "${got%% *}" == "$3" ]] || fail "$label: $1 $2 -> ${got%% *} (ожидается $3)"
  [[ -z "${4:-}" || "${got#* }" == "$4" ]] || fail "$label: $1 $2 -> тело «${got#* }» (ожидается «$4»)"
  echo "  ok  $1 $2 -> ${got%% *} ${got#* }"
}
expect_not_erp() { # <Host> <путь>: код любой, но ответ не от erp-backend
  local got; got="$(get "$1" "$2")"
  [[ "${got#* }" != ERP-BACKEND ]] || fail "$label: $1 $2 дошёл до erp-backend"
  echo "  ok  $1 $2 -> ${got%% *} ${got#* } (не erp-backend)"
}

check_edge() { # <ERP-host> <Cabinet-host> <Platform-host>
  local erp="$1" cab="$2" plat="$3" p h
  echo "[$label]"
  # 1. ERP: закрыто снаружи.
  for p in /api/integration /api/integration/ /api/integration/v1/health /api/integration/v1/deals/1 \
           /admin /admin/ /admin/login/ /admin/core/user/ /mcp /mcp/erp/; do
    expect "$erp" "$p" 404
  done
  # ERP: прежние маршруты работают (до erp-backend доходят).
  for p in /api/v1/health /api/v1/admin/email-templates/ /api/v1/admin/email-templates/1/preview/ /api/portal/v1/me \
           /ws/notifications/ /static/admin/css/base.css /media/catalog/a.jpg /health /health/; do
    expect "$erp" "$p" 200 ERP-BACKEND
  done
  expect "$erp" / 200 ERP-WEB
  expect "$erp" /requests 200 ERP-WEB
  expect "$erp" /administrator 200 ERP-WEB   # префикс по сегменту пути: /administrator — не /admin
  # 3. Обходы: двойной слэш, регистр, кодирование, ../ — 404 либо не erp-backend.
  for p in //admin/ //api/integration/v1/health /ADMIN/ /Admin/ /API/integration/v1/health /%61dmin/ /api/%69ntegration/v1/health \
           /static/../admin/ /./admin/; do
    expect_not_erp "$erp" "$p"
  done
  # 2. Cabinet и Платформа: машинный API и admin ERP не проксируются.
  for h in "$cab" "$plat"; do
    for p in /api/integration/v1/health /api/integration /admin /admin/ /admin/login/; do
      expect_not_erp "$h" "$p"
    done
  done
  expect "$cab" /admin/ 200 CABINET-WEB
  expect "$cab" /api/portal/v1/me 200 ERP-BACKEND
  expect "$cab" /media/catalog/a.jpg 200 ERP-BACKEND
  expect "$plat" /admin/ 200 PLATFORM-WEB
  expect "$plat" /api/integration/v1/health 200 PLATFORM-BFF
}

# Prod: адреса сайтов — http://…, чтобы Caddy не пытался получить сертификат; маршруты те же.
label="Caddyfile.prod"
start_caddy "$root/infra/caddy/Caddyfile.prod" -e ACME_EMAIL=a@example.com \
  -e CRM_DOMAIN=http://crm.example.org -e ERP_DOMAIN=http://erp.example.org \
  -e CABINET_DOMAIN=http://cabinet.example.org -e PLATFORM_DOMAIN=http://platform.example.org
check_edge erp.example.org cabinet.example.org platform.example.org

label="Caddyfile.dev"
start_caddy "$root/infra/caddy/Caddyfile.dev"
check_edge erp.localhost cabinet.localhost platform.localhost

echo "caddy-edge-test: ok"
