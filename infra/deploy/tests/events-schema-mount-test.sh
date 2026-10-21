#!/usr/bin/env bash
# Тест M5-INF-01c: схема событий ERP → CRM доезжает до сервисов ERP в проде.
#  1. prod.yml монтирует packages/contracts/events.schema.json read-only в /packages/contracts/ сервисов ERP;
#  2. файл входит в release.tgz (deploy.yml);
#  3. deploy.sh отказывается деплоить релиз без этого файла до pull и миграций.
# Секретов не требует: env — копия .env.prod.example с заглушками. Запуск: bash этот-файл
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fail() { echo "FAIL: $*"; exit 1; }

sed 's/CHANGE_ME/ci-only-value/' "$root/infra/.env.prod.example" > "$tmp/env.prod"
target=/packages/contracts/events.schema.json

# 1. Монтирование в сервисах ERP (erp-mcp под профилем mcp — включаем его в проверку).
RT_IMAGE_TAG=events-test docker compose -f "$root/infra/compose/base.yml" -f "$root/infra/compose/prod.yml" \
  --env-file "$tmp/env.prod" --profile mcp config --format json > "$tmp/prod.json"
for svc in erp-backend erp-worker erp-worker-ai erp-beat erp-mcp; do
  ok="$(jq -r --arg s "$svc" --arg t "$target" \
    '[.services[$s].volumes[]? | select(.target == $t and .read_only == true and .type == "bind"
       and (.source | endswith("/packages/contracts/events.schema.json")))] | length' "$tmp/prod.json")"
  [[ "$ok" == 1 ]] || fail "$svc: нет read-only bind-монтирования events.schema.json в $target"
done
# Воркеры не потеряли том медиа (слияние volumes с base.yml).
for svc in erp-worker erp-worker-ai; do
  jq -e --arg s "$svc" '[.services[$s].volumes[]? | select(.target == "/app/media")] | length == 1' "$tmp/prod.json" >/dev/null \
    || fail "$svc: пропал том /app/media"
done

# 2. Файл в архиве релиза.
grep -E 'tar -czf release\.tgz .*packages/contracts/events\.schema\.json' "$root/.github/workflows/deploy.yml" >/dev/null \
  || fail ".github/workflows/deploy.yml: release.tgz не включает packages/contracts/events.schema.json"

# 3. deploy.sh без файла в релизе — отказ до обращения к docker (фейковый docker валит тест при вызове).
rel="$tmp/releases/tag1"; mkdir -p "$rel/infra" "$rel/packages/contracts" "$tmp/bin"
cp -R "$root/infra/deploy" "$rel/infra/deploy"
cp "$root/packages/contracts/mcp-tools.json" "$rel/packages/contracts/"
printf '#!/usr/bin/env bash\necho "docker вызван: $*" >> "%s/docker.log"\nexit 1\n' "$tmp" > "$tmp/bin/docker"; chmod +x "$tmp/bin/docker"
sed -E "s/192\.0\.2\./10.0.0./g" "$tmp/env.prod" > "$tmp/env"; chmod 600 "$tmp/env"
run() { PATH="$tmp/bin:$PATH" RT_ENV_FILE="$tmp/env" RT_STATE="$tmp/state" bash "$rel/infra/deploy/deploy.sh" tag1 >"$tmp/log" 2>&1; }
if run; then fail "deploy.sh прошёл без events.schema.json в релизе"; fi
grep -q 'events.schema.json' "$tmp/log" || { cat "$tmp/log"; fail "deploy.sh: в сообщении нет имени файла"; }
[[ ! -e "$tmp/docker.log" ]] || fail "deploy.sh дошёл до docker до проверки файла"
echo "events-schema-mount-test: ok"
