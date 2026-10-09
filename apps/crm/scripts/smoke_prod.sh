#!/usr/bin/env bash
# Smoke-проверка prod (PLAN Фаза 8): TLS, /health, /ready, фронт, заголовки безопасности,
# закрытый API, редирект http→https. Код выхода 1 — деплой считается проваленным
# (deploy-prod.yml откатывает на предыдущий тег).
set -euo pipefail

usage() {
  cat <<USAGE
Использование: scripts/smoke_prod.sh [DOMAIN]

DOMAIN берётся из аргумента, переменной DOMAIN или .env. Проверяет:
  https://DOMAIN/health, /ready, /            → 200 (сертификат проверяется curl)
  заголовки HSTS, X-Content-Type-Options, CSP → есть
  GET /api/v1/me без токена                   → 401
  http://DOMAIN/                              → редирект на https
Повторяет попытки до SMOKE_WAIT секунд (по умолчанию 120) — пока сервисы стартуют.
USAGE
}
[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && { usage; exit 0; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DOMAIN="${1:-${DOMAIN:-}}"
if [[ -z "$DOMAIN" && -f "$ROOT/.env" ]]; then
  DOMAIN="$(grep -E '^DOMAIN=' "$ROOT/.env" | tail -n 1 | cut -d= -f2-)"
fi
[[ -n "$DOMAIN" ]] || { echo "DOMAIN не задан (аргумент, env или .env)" >&2; exit 2; }
BASE="https://$DOMAIN"
WAIT="${SMOKE_WAIT:-120}"

failed=0
ok() { echo "✔ $*"; }
bad() { echo "✖ $*"; failed=1; }

wait_ready() {
  local deadline=$(( $(date +%s) + WAIT ))
  until [[ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$BASE/ready" || true)" == "200" ]]; do
    (( $(date +%s) >= deadline )) && return 1
    sleep 5
  done
}

if wait_ready; then ok "$BASE/ready → 200"; else bad "$BASE/ready не 200 за ${WAIT} с"; fi

expect() {
  local url="$1" want="$2" code
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$url" || true)"
  if [[ "$code" == "$want" ]]; then ok "$url → $code"; else bad "$url → ${code:-нет ответа} (ожидалось $want)"; fi
}
expect "$BASE/health" 200
expect "$BASE/" 200
expect "$BASE/api/v1/me" 401

headers="$(curl -sI --max-time 10 "$BASE/" || true)"
for h in strict-transport-security x-content-type-options content-security-policy; do
  if grep -qi "^$h:" <<<"$headers"; then ok "заголовок $h"; else bad "нет заголовка $h"; fi
done
redirect="$(curl -s -o /dev/null -w '%{http_code} %{redirect_url}' --max-time 10 "http://$DOMAIN/" || true)"
if [[ "$redirect" =~ ^30[178]\ https:// ]]; then ok "http → https"; else bad "нет редиректа http→https ($redirect)"; fi

if [[ "$failed" == 1 ]]; then
  echo
  echo "Что делать: make ps, make logs s=api / s=caddy; curl -s $BASE/ready (какая зависимость fail);"
  echo "docs/runbooks/deploy.md (откат на предыдущий тег)."
  exit 1
fi
echo "Smoke prod OK: $DOMAIN"
