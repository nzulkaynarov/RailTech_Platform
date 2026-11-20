#!/usr/bin/env bash
# Тест СЦ-3: пустой или заглушка …@example.com/.org адрес поддержки (SUPPORT_EMAIL) — предупреждение в журнале выкладки,
# не остановка (основной адрес задаётся в Платформе). Проверка — до pull образов; откат её не вызывает. Секретов не требует.
# Запуск: bash этот-файл
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fail() { echo "FAIL: $*"; exit 1; }
deploy="$root/infra/deploy/deploy.sh"; rollback="$root/infra/deploy/rollback.sh"

check() { # check <содержимое env> → вывод warn_placeholder_email; код выхода всегда 0
  printf '%b' "$1" >"$tmp/prod.env"
  (RT_ENV_FILE="$tmp/prod.env"; source "$root/infra/deploy/lib.sh"; warn_placeholder_email SUPPORT_EMAIL "подсказка") 2>&1
}

for bad in 'SUPPORT_EMAIL=support@example.com\n' 'SUPPORT_EMAIL=Support@Example.ORG\n' 'SUPPORT_EMAIL=\n' 'A=1\n' \
  'SUPPORT_EMAIL=  \n'; do
  out="$(check "$bad")" || fail "предупреждение не должно останавливать выкладку: $bad"
  [[ "$out" == *"внимание"* ]] || fail "заглушка или пусто без предупреждения: $bad"
done
for good in 'A=1\nSUPPORT_EMAIL=help@rt.uz\n' 'SUPPORT_EMAIL=help@rt.uz\r\n'; do
  out="$(check "$good")" || fail "настоящий адрес: ненулевой код"
  [[ -z "$out" ]] || fail "настоящий адрес с предупреждением: $good"
done

call="$(grep -nE '^warn_placeholder_email SUPPORT_EMAIL' "$deploy" | head -1 | cut -d: -f1 || true)"
pull="$(grep -nE 'retry "pull образов"' "$deploy" | head -1 | cut -d: -f1 || true)"
[[ -n "$call" && -n "$pull" && "$call" -lt "$pull" ]] || fail "deploy.sh: проверка адреса поддержки должна идти до pull образов"
if grep -q 'warn_placeholder_email\|require_real_email' "$rollback"; then fail "rollback.sh не должен проверять адрес поддержки"; fi
echo "support-email: OK"
