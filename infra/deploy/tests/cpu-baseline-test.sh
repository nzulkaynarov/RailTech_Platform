#!/usr/bin/env bash
# Тест M5-INF-02: cpu-baseline-check.sh останавливает деплой, если образ не запускается на CPU с базой x86-64 v1,
# проходит, когда все образы запускаются, а deploy.sh вызывает его после pull и до pg_dump-гейта и миграций.
# Docker подменён заглушкой; секретов не требует. Запуск: bash этот-файл
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fail() { echo "FAIL: $*"; exit 1; }

mkdir -p "$tmp/bin"
: > "$tmp/env"; chmod 600 "$tmp/env"
cat > "$tmp/bin/docker" <<'STUB'
#!/usr/bin/env bash
if [[ "$1" == compose ]]; then
  printf '%s\n' ghcr.io/o/rt-litellm:T ghcr.io/o/rt-crm-backend:T ghcr.io/o/rt-erp-backend:T ghcr.io/o/rt-cabinet:T ghcr.io/o/rt-platform-bff:T ghcr.io/o/rt-platform-web:T ghcr.io/o/rt-eds:T \
    caddy:2.11.7-alpine redis:7.4.11 rustfs/rustfs:1.0.1 langfuse/langfuse:4.56.0
  exit 0
fi
# docker run ... <образ> ...: образ из $RT_TEST_FAIL «падает» так, как падает официальный LiteLLM на CPU без v2
for a in "$@"; do
  if [[ -n "${RT_TEST_FAIL:-}" && "$a" == *"$RT_TEST_FAIL"* ]]; then echo "Fatal glibc error: CPU does not support x86-64-v2" >&2; exit 127; fi
done
echo "$*" >> "$RT_TEST_LOG"
STUB
chmod +x "$tmp/bin/docker"
run() { PATH="$tmp/bin:$PATH" RT_ENV_FILE="$tmp/env" RT_TEST_LOG="$tmp/run.log" bash "$root/infra/deploy/cpu-baseline-check.sh" "$tmp" T; }

# 1. Все образы запускаются — успех; каждому известному образу своя команда.
: > "$tmp/run.log"
run > "$tmp/out" 2>&1 || { cat "$tmp/out"; fail "ожидался успех, когда все образы запускаются"; }
grep -q 'litellm.proxy.proxy_server' "$tmp/run.log" || fail "LiteLLM не проверяется импортом litellm.proxy.proxy_server"
grep -q 'rt-crm-backend:T -c' "$tmp/run.log" || fail "CRM не проверяется импортом numpy"
grep -q 'rt-platform-bff:T -c' "$tmp/run.log" || fail "BFF Платформы не проверяется импортом numpy (нативные колёса)"
grep -q 'rt-eds:T -c' "$tmp/run.log" || fail "EDS не проверяется импортом нативных колёс (numpy/pandas/scipy, если есть)"
grep -q 'без правила.*rt-eds' "$tmp/out" && fail "образ EDS попал в список без правила"
grep -q 'entrypoint caddy .*rt-platform-web:T version' "$tmp/run.log" || fail "web Платформы не проверяется запуском caddy"
grep -q 'без правила.*rt-platform' "$tmp/out" && fail "образы Платформы попали в список без правила"
grep -q 'langfuse/langfuse' "$tmp/run.log" && fail "образ без правила не должен запускаться"
grep -q 'без правила.*langfuse' "$tmp/out" || fail "образ без правила не попал в список непроверенных"

# 2. Один образ падает — отказ, в сообщении имя образа.
if RT_TEST_FAIL=rt-litellm run > "$tmp/out" 2>&1; then fail "ожидался отказ, когда rt-litellm падает на CPU без v2"; fi
if ! grep -q 'rt-litellm' "$tmp/out" || ! grep -q 'x86-64' "$tmp/out"; then cat "$tmp/out"; fail "сообщение об отказе не называет образ и причину"; fi

if RT_TEST_FAIL=rt-eds run > "$tmp/out" 2>&1; then fail "ожидался отказ, когда rt-eds падает на CPU без v2"; fi
grep -q 'rt-eds' "$tmp/out" || { cat "$tmp/out"; fail "сообщение об отказе не называет rt-eds"; }

if RT_TEST_FAIL=rt-platform-bff run > "$tmp/out" 2>&1; then fail "ожидался отказ, когда rt-platform-bff падает на CPU без v2"; fi
grep -q 'rt-platform-bff' "$tmp/out" || { cat "$tmp/out"; fail "сообщение об отказе не называет rt-platform-bff"; }

# 3. deploy.sh: проверка стоит после pull и до pg_dump-гейта и миграций.
pull="$(grep -n 'pull crm-api' "$root/infra/deploy/deploy.sh" | head -1 | cut -d: -f1)"
chk="$(grep -n 'cpu-baseline-check.sh' "$root/infra/deploy/deploy.sh" | grep -v '^[0-9]*:#' | head -1 | cut -d: -f1)"
dump="$(grep -n 'predeploy-dump.sh' "$root/infra/deploy/deploy.sh" | grep -v '^[0-9]*:#' | head -1 | cut -d: -f1)"
[[ -n "$pull" && -n "$chk" && -n "$dump" && "$pull" -lt "$chk" && "$chk" -lt "$dump" ]] \
  || fail "deploy.sh: cpu-baseline-check.sh должен идти между pull и pg_dump-гейтом"
grep -q 'pull .* litellm' "$root/infra/deploy/deploy.sh" || fail "deploy.sh: rt-litellm не входит в pull"
grep -q 'pull .* platform-bff platform-web' "$root/infra/deploy/deploy.sh" || fail "deploy.sh: образы Платформы не входят в pull"
grep -q 'pull .* eds-api' "$root/infra/deploy/deploy.sh" || fail "deploy.sh: образ EDS не входит в pull"
grep -q 'platform-bff' "$root/infra/deploy/rollback.sh" || fail "rollback.sh: образы Платформы не входят в pull"
# shellcheck source=deploy-images.sh
source "$here/deploy-images.sh"
deploy_yml="$root/.github/workflows/deploy.yml"
deploy_images="$(deploy_image_names "$deploy_yml")" || fail "в deploy.yml не найдена таблица образов (images='[…]' в job prepare)"
for img in rt-platform-bff rt-platform-web rt-litellm; do
  grep -qx "$img" <<<"$deploy_images" || fail "deploy.yml: нет сборки $img"
done

# 4. S0-7: одна таблица правил на два места (деплой на сервере и CI под qemu64), и она согласована с тем, что собирает deploy.yml,
#    с матрицей ci.yml и с образами VPS 2. Docker не нужен: list/params только читают таблицы.
qcheck="$root/scripts/qemu_cpu_check.sh"
rules_names="$(bash -c 'source "$1"; cpu_baseline_names' _ "$root/infra/deploy/cpu-baseline-rules.sh")"
for n in $rules_names; do
  bash -c 'source "$1"; cpu_baseline_rules "$2" true' _ "$root/infra/deploy/cpu-baseline-rules.sh" "$n" || fail "cpu-baseline-rules.sh: для $n в списке имён нет правила"
done
built="$("$qcheck" list built)"
for img in $deploy_images; do
  grep -qx "$img" <<<"$built" || fail "$img собирается в deploy.yml, но scripts/qemu_cpu_check.sh не умеет его собирать и проверять (таблица build_spec)"
  # контекст сборки в deploy.yml и в таблице проверки совпадают
  ctx_deploy="$(deploy_image_field "$deploy_yml" "$img" context)"
  ctx_check="$("$qcheck" params "$img" | sed -n 's/^context=//p')"
  [[ "$ctx_deploy" == "$ctx_check" ]] || fail "$img: контекст сборки в deploy.yml ($ctx_deploy) и в qemu_cpu_check.sh ($ctx_check) расходятся"
  grep -q "^ *- $img\$" "$root/.github/workflows/ci.yml" || fail "$img нет в матрице задания cpu-image в ci.yml"
done
for img in $built; do
  grep -qx "$img" <<<"$deploy_images" || [[ "$img" == rt-db-postgres || "$img" == rt-db-backup ]] \
    || fail "$img есть в таблице проверки, но не в deploy.yml и не образ VPS 2"
  grep -q "^ *- $img\$" "$root/.github/workflows/ci.yml" || fail "$img нет в матрице задания cpu-image в ci.yml"
done
for img in rt-db-postgres rt-db-backup; do
  grep -q "image: $img:local" "$root/infra/compose/db.yml" || fail "db.yml: образ $img:local не найден — таблица проверки устарела"
done
for n in $("$qcheck" list pulled); do
  [[ -n "$("$qcheck" ref "$n")" ]] || fail "сторонний образ $n не найден в infra/compose/base.yml и prod.yml"
done
# в матрице ci.yml нет лишних образов
while read -r img; do
  grep -qx "$img" <<<"$built" || fail "ci.yml: в матрице cpu-image лишний образ $img"
done < <(sed -n '/^  cpu-image:/,/^    steps:/p' "$root/.github/workflows/ci.yml" | sed -n 's/^ *- \(rt-[a-z-]*\)$/\1/p')
echo "cpu-baseline-test: ok"
