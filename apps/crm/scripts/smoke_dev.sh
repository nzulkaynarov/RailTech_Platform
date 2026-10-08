#!/usr/bin/env bash
# Smoke-проверка dev-стенда: /health и /ready напрямую в api и через Caddy.
set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"
EDGE_URL="${EDGE_URL:-http://localhost:${HTTP_PORT:-80}}"

usage() {
  cat <<USAGE
Использование: scripts/smoke_dev.sh

Проверяет, что dev-стенд отвечает:
  GET \$API_URL/health, \$API_URL/ready   (по умолчанию ${API_URL})
  GET \$EDGE_URL/ready, \$EDGE_URL/        (по умолчанию ${EDGE_URL}, через Caddy)
Переменные API_URL, EDGE_URL переопределяют адреса.
USAGE
}

[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && { usage; exit 0; }

failed=0
check() {
  local url="$1" code
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$url" || true)"
  if [[ "$code" == "200" ]]; then
    echo "✔ $url → 200"
  else
    echo "✖ $url → ${code:-нет ответа}"
    failed=1
  fi
}

check "$API_URL/health"
check "$API_URL/ready"
check "$EDGE_URL/ready"
check "$EDGE_URL/"

if [[ "$failed" == 1 ]]; then
  echo
  echo "Что делать: make ps (все ли сервисы healthy), make logs s=api,"
  echo "curl -s $API_URL/ready (какая зависимость fail), docs/runbooks/dev-stand.md"
  exit 1
fi
echo "Smoke OK"
