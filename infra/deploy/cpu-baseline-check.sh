#!/usr/bin/env bash
# Проверка базы CPU (M5-INF-02): ни один образ прода не должен требовать больше базового x86-64 (v1).
# Прод-VPS (Eskiz, KVM) отдают «QEMU Virtual CPU version 2.5+» без SSE4.2/SSSE3/POPCNT/AVX (docs/runbooks/servers.md,
# «CPU прод-VPS»): официальный образ LiteLLM (Wolfi) и numpy 2.4+ на нём падают при запуске/import. Скрипт запускает в каждом
# образе короткую команду, которая исполняет нативный код (import numpy, litellm.proxy, версия бинаря), — ловит это ДО миграций.
# Вызывается из deploy.sh после pull и до pg_dump-гейта; вручную: infra/deploy/cpu-baseline-check.sh <каталог-релиза> <тег>.
# Образы берутся из compose-конфигурации релиза (с учётом RT_PROFILES); образ без правила не проверяется, а печатается в списке.
# Таблица правил — infra/deploy/cpu-baseline-rules.sh (общая с CI-проверкой под эмуляцией qemu64: scripts/qemu_cpu_check.sh).
set -euo pipefail
# shellcheck source=infra/deploy/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
# shellcheck source=infra/deploy/cpu-baseline-rules.sh
source "$(dirname "${BASH_SOURCE[0]}")/cpu-baseline-rules.sh"

rel="${1:?usage: cpu-baseline-check.sh <каталог-релиза> <тег-образов>}"
export RT_IMAGE_TAG="${2:?usage: cpu-baseline-check.sh <каталог-релиза> <тег-образов>}"

failed=()
skipped=()

# probe <программа> <аргументы...> — обработчик правил для образа cur_image
cur_image=""
probe() {
  local entry="$1" out
  shift
  if out="$(docker run --rm --network none -e LITELLM_LOCAL_MODEL_COST_MAP=True --entrypoint "$entry" "$cur_image" "$@" 2>&1)"; then
    log "cpu-baseline: ok    $cur_image ($entry)"
  else
    failed+=("$cur_image")
    printf '✘ cpu-baseline: %s\n%s\n' "$cur_image" "$(printf '%s' "$out" | tail -n 4 | sed 's/^/    /')" >&2
  fi
}

images="$(compose "$rel" config --images)" || die "cpu-baseline: не удалось получить список образов (docker compose config)"
[[ -n "$images" ]] || die "cpu-baseline: пустой список образов"

while read -r image; do
  [[ -n "$image" ]] || continue
  name="${image##*/}"; name="${name%%:*}"
  cur_image="$image"
  cpu_baseline_rules "$name" probe || skipped+=("$image")
done < <(printf '%s\n' "$images" | sort -u)

[[ ${#skipped[@]} -eq 0 ]] || log "cpu-baseline: без правила (не проверены): ${skipped[*]}"

if [[ ${#failed[@]} -gt 0 ]]; then
  die "образ(ы) не запускаются на CPU с базой x86-64 v1: ${failed[*]} — прод-VPS без x86-64-v2 (docs/runbooks/servers.md, «CPU прод-VPS»); деплой остановлен до миграций"
fi
log "cpu-baseline: все образы запускаются"
