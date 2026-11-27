#!/usr/bin/env bash
# Общий предел тяжёлых проверок на машине: не больше двух одновременно (владелец 2026-11-26, память ПК 21 ГБ).
# Два слота — файлы slot1.lock и slot2.lock, flock; та же семантика, что у прежней внешней обёртки heavy.sh.
#
#   scripts/heavy-lock.sh <команда…>     взять слот, выполнить команду (exec), слот освобождается с её завершением
#   source scripts/heavy-lock.sh         взять слот на всё время жизни текущего bash-скрипта (ci_local.sh, test_*_local.sh)
#
# Вложенные вызовы не берут второй слот (RT_HEAVY_LOCK_HELD=1 уходит в окружение детей). Без слота: CI=true,
# RT_HEAVY_LOCK=0 или нет flock (macOS). Настройки: RT_HEAVY_LOCK_DIR (по умолчанию /tmp/claude-<uid>/rt-heavy),
# RT_HEAVY_SLOTS (2), RT_HEAVY_SLEEP (15 с между кругами ожидания).

_rt_heavy_acquire() {
  [[ "${RT_HEAVY_LOCK_HELD:-}" == 1 || "${CI:-}" == true || "${RT_HEAVY_LOCK:-}" == 0 ]] && return 0
  command -v flock >/dev/null 2>&1 || return 0
  local dir="${RT_HEAVY_LOCK_DIR:-/tmp/claude-$(id -u)/rt-heavy}" slots="${RT_HEAVY_SLOTS:-2}" slot
  mkdir -p "$dir"
  while true; do
    for ((slot = 1; slot <= slots; slot++)); do
      exec {RT_HEAVY_FD}>"$dir/slot$slot.lock"
      if flock -n "$RT_HEAVY_FD"; then
        echo "[heavy] slot $slot" >&2
        export RT_HEAVY_LOCK_HELD=1
        return 0
      fi
      exec {RT_HEAVY_FD}>&-
    done
    sleep "${RT_HEAVY_SLEEP:-15}"
  done
}

_rt_heavy_acquire
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  [[ $# -gt 0 ]] || { echo "usage: heavy-lock.sh <command...>" >&2; exit 2; }
  exec "$@"
fi
