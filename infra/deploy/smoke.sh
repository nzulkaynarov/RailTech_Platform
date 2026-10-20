#!/usr/bin/env bash
# Smoke трёх доменов (аналог `make smoke` для прода): /health каждого — 200, /mcp снаружи — 404 (FIX-03).
#   smoke.sh --domains crm.example erp.example cabinet.example [--resolve-ip IP] [--insecure] [--retries N]
# --resolve-ip: ходить на указанный IP вместо DNS (проверка на самом сервере, 127.0.0.1); --insecure: не проверять
# сертификат (первый запуск, пока ACME не выпустил его). Повторяет до --retries раз с паузой 10 с.
set -euo pipefail

domains=() ip="" insecure=0 retries=30
while [[ $# -gt 0 ]]; do
  case "$1" in
    --domains) shift; while [[ $# -gt 0 && "$1" != --* ]]; do domains+=("$1"); shift; done ;;
    --resolve-ip) ip="$2"; shift 2 ;;
    --insecure) insecure=1; shift ;;
    --retries) retries="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
[[ ${#domains[@]} -eq 3 ]] || { echo "usage: smoke.sh --domains <crm> <erp> <cabinet> [--resolve-ip IP] [--insecure] [--retries N]" >&2; exit 2; }

code_of() { # домен, путь, [-L: идти по редиректам] — ERP отдаёт 301 /health -> /health/ (APPEND_SLASH)
  local args=(-sS -o /dev/null -w '%{http_code}' --max-time 10)
  [[ "${3:-}" == -L ]] && args+=(-L --max-redirs 3)
  [[ -n "$ip" ]] && args+=(--resolve "$1:443:$ip")
  [[ $insecure -eq 1 ]] && args+=(-k)
  curl "${args[@]}" "https://$1$2" 2>/dev/null || echo 000
}

attempt() {
  local ok=1 d code
  for d in "${domains[@]}"; do
    code="$(code_of "$d" /health -L)"
    printf '  %-32s /health → %s\n' "$d" "$code"
    [[ "$code" == 200 ]] || ok=0
  done
  code="$(code_of "${domains[1]}" /mcp/erp/)"
  printf '  %-32s /mcp/erp/ → %s (ожидается 404)\n' "${domains[1]}" "$code"
  [[ "$code" == 404 ]] || ok=0
  [[ $ok -eq 1 ]]
}

for ((i = 1; i <= retries; i++)); do
  echo "smoke: попытка $i/$retries"
  if attempt; then echo "smoke: ok"; exit 0; fi
  sleep 10
done
echo "smoke: FAIL" >&2
exit 1
