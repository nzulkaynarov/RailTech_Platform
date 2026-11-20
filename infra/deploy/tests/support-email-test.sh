#!/usr/bin/env bash
# Тест СЦ-3: выкладка останавливается, если адрес поддержки (SUPPORT_EMAIL) пуст или заглушка …@example.com/.org, —
# клиенты видят его в письмах. Проверка — до pull образов; откат (rollback.sh) её не вызывает. Секретов не требует.
# Запуск: bash этот-файл
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fail() { echo "FAIL: $*"; exit 1; }
deploy="$root/infra/deploy/deploy.sh"; rollback="$root/infra/deploy/rollback.sh"

check() { # check <содержимое env> → код выхода require_real_email
  printf '%b' "$1" >"$tmp/prod.env"
  (RT_ENV_FILE="$tmp/prod.env"; source "$root/infra/deploy/lib.sh"; require_real_email SUPPORT_EMAIL "подсказка") 2>/dev/null
}

for bad in 'SUPPORT_EMAIL=support@example.com\n' 'SUPPORT_EMAIL=Support@Example.ORG\n' 'SUPPORT_EMAIL=\n' 'A=1\n' \
  'SUPPORT_EMAIL=  \n'; do
  if check "$bad"; then fail "заглушка или пусто пропущены: $bad"; fi
done
check 'A=1\nSUPPORT_EMAIL=help@rt.uz\n' || fail "настоящий адрес не принят"
check 'SUPPORT_EMAIL=help@rt.uz\r\n' || fail "адрес с \\r (файл из Windows) не принят"

call="$(grep -nE '^require_real_email SUPPORT_EMAIL' "$deploy" | head -1 | cut -d: -f1 || true)"
pull="$(grep -nE 'retry "pull образов"' "$deploy" | head -1 | cut -d: -f1 || true)"
[[ -n "$call" && -n "$pull" && "$call" -lt "$pull" ]] || fail "deploy.sh: проверка адреса поддержки должна идти до pull образов"
if grep -q 'require_real_email' "$rollback"; then fail "rollback.sh не должен проверять адрес поддержки"; fi
echo "support-email: OK"
