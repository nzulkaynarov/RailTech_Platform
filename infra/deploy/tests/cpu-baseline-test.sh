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
  printf '%s\n' ghcr.io/o/rt-litellm:T ghcr.io/o/rt-crm-backend:T ghcr.io/o/rt-erp-backend:T ghcr.io/o/rt-cabinet:T \
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
grep -q 'langfuse/langfuse' "$tmp/run.log" && fail "образ без правила не должен запускаться"
grep -q 'без правила.*langfuse' "$tmp/out" || fail "образ без правила не попал в список непроверенных"

# 2. Один образ падает — отказ, в сообщении имя образа.
if RT_TEST_FAIL=rt-litellm run > "$tmp/out" 2>&1; then fail "ожидался отказ, когда rt-litellm падает на CPU без v2"; fi
if ! grep -q 'rt-litellm' "$tmp/out" || ! grep -q 'x86-64' "$tmp/out"; then cat "$tmp/out"; fail "сообщение об отказе не называет образ и причину"; fi

# 3. deploy.sh: проверка стоит после pull и до pg_dump-гейта и миграций.
pull="$(grep -n 'pull crm-api' "$root/infra/deploy/deploy.sh" | head -1 | cut -d: -f1)"
chk="$(grep -n 'cpu-baseline-check.sh' "$root/infra/deploy/deploy.sh" | grep -v '^[0-9]*:#' | head -1 | cut -d: -f1)"
dump="$(grep -n 'predeploy-dump.sh' "$root/infra/deploy/deploy.sh" | grep -v '^[0-9]*:#' | head -1 | cut -d: -f1)"
[[ -n "$pull" && -n "$chk" && -n "$dump" && "$pull" -lt "$chk" && "$chk" -lt "$dump" ]] \
  || fail "deploy.sh: cpu-baseline-check.sh должен идти между pull и pg_dump-гейтом"
grep -q 'pull .* litellm' "$root/infra/deploy/deploy.sh" || fail "deploy.sh: rt-litellm не входит в pull"
grep -q 'name: Образ rt-litellm' "$root/.github/workflows/deploy.yml" || fail "deploy.yml: нет сборки rt-litellm"
echo "cpu-baseline-test: ok"
