#!/usr/bin/env bash
# Проверка базы CPU (M5-INF-02): ни один образ прода не должен требовать больше базового x86-64 (v1).
# Прод-VPS (Eskiz, KVM) отдают «QEMU Virtual CPU version 2.5+» без SSE4.2/SSSE3/POPCNT/AVX (docs/runbooks/servers.md,
# «CPU прод-VPS»): официальный образ LiteLLM (Wolfi) и numpy 2.4+ на нём падают при запуске/import. Скрипт запускает в каждом
# образе короткую команду, которая исполняет нативный код (import numpy, litellm.proxy, версия бинаря), — ловит это ДО миграций.
# Вызывается из deploy.sh после pull и до pg_dump-гейта; вручную: infra/deploy/cpu-baseline-check.sh <каталог-релиза> <тег>.
# Образы берутся из compose-конфигурации релиза (с учётом RT_PROFILES); образ без правила не проверяется, а печатается в списке.
set -euo pipefail
# shellcheck source=infra/deploy/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

rel="${1:?usage: cpu-baseline-check.sh <каталог-релиза> <тег-образов>}"
export RT_IMAGE_TAG="${2:?usage: cpu-baseline-check.sh <каталог-релиза> <тег-образов>}"

# Нативные колёса, если они есть в образе: отсутствие модуля — не ошибка, падение при import — ошибка.
py_native='import importlib.util as u; [__import__(m) for m in ("numpy","pandas","scipy") if u.find_spec(m)]'

failed=()
skipped=()

# probe <образ> <entrypoint> <аргументы...>
probe() {
  local image="$1" entry="$2" out
  shift 2
  if out="$(docker run --rm --network none -e LITELLM_LOCAL_MODEL_COST_MAP=True --entrypoint "$entry" "$image" "$@" 2>&1)"; then
    log "cpu-baseline: ok    $image"
  else
    failed+=("$image")
    printf '✘ cpu-baseline: %s\n%s\n' "$image" "$(printf '%s' "$out" | tail -n 4 | sed 's/^/    /')" >&2
  fi
}

images="$(compose "$rel" config --images)" || die "cpu-baseline: не удалось получить список образов (docker compose config)"
[[ -n "$images" ]] || die "cpu-baseline: пустой список образов"

while read -r image; do
  [[ -n "$image" ]] || continue
  name="${image##*/}"; name="${name%%:*}"
  case "$name" in
    rt-crm-backend)  probe "$image" python -c "$py_native" ;;
    rt-platform-bff) probe "$image" python -c "$py_native" ;;
    rt-erp-backend)  probe "$image" python -c "$py_native" ;;
    rt-litellm)      probe "$image" python -c "import numpy; import litellm.proxy.proxy_server" ;;
    rt-crm-frontend|rt-platform-web|caddy) probe "$image" caddy version ;;
    rt-erp-frontend|rt-cabinet) probe "$image" nginx -v ;;
    redis)           probe "$image" redis-server --version ;;
    rustfs)          probe "$image" rustfs --version ;;
    *)               skipped+=("$image") ;;
  esac
done < <(printf '%s\n' "$images" | sort -u)

[[ ${#skipped[@]} -eq 0 ]] || log "cpu-baseline: без правила (не проверены): ${skipped[*]}"

if [[ ${#failed[@]} -gt 0 ]]; then
  die "образ(ы) не запускаются на CPU с базой x86-64 v1: ${failed[*]} — прод-VPS без x86-64-v2 (docs/runbooks/servers.md, «CPU прод-VPS»); деплой остановлен до миграций"
fi
log "cpu-baseline: все образы запускаются"
