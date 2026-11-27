#!/usr/bin/env bash
# Тест scripts/heavy-lock.sh на временном каталоге слотов: два держателя, третий ждёт; повторный вход; CI=true и RT_HEAVY_LOCK=0.
# Запуск: bash scripts/tests/heavy-lock-test.sh (входит в make deploy-check)
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
lock="$here/../heavy-lock.sh"
tmp="$(mktemp -d)"
trap 'kill $(jobs -p) 2>/dev/null || true; rm -rf "$tmp"' EXIT
export RT_HEAVY_LOCK_DIR="$tmp/slots" RT_HEAVY_SLEEP=0.2
unset RT_HEAVY_LOCK_HELD CI RT_HEAVY_LOCK
fail() { echo "FAIL: $*"; exit 1; }
wait_file() { for _ in $(seq 100); do [[ -e "$1" ]] && return 0; sleep 0.1; done; fail "нет $1"; }

command -v flock >/dev/null || { echo "heavy-lock-test: пропуск (нет flock)"; exit 0; }

# два держателя занимают оба слота, пока нет файла release
for n in 1 2; do
  bash "$lock" bash -c "touch '$tmp/held$n'; while [ ! -e '$tmp/release' ]; do sleep 0.1; done" 2>/dev/null &
done
wait_file "$tmp/held1"; wait_file "$tmp/held2"

# третий ждёт
bash "$lock" touch "$tmp/third" 2>/dev/null &
third=$!
sleep 1
[[ ! -e "$tmp/third" ]] || fail "третий взял слот, пока заняты два"

# освободили: третий проходит
touch "$tmp/release"
wait_file "$tmp/third"
wait "$third"
wait

# повторный вход: внутри держателя вложенный вызов не ждёт, даже если оба слота заняты им самим
out="$(bash "$lock" bash -c "bash '$lock' bash -c 'bash \"$lock\" echo nested' " 2>/dev/null)"
[[ "$out" == nested ]] || fail "повторный вход: $out"
out="$(bash "$lock" bash -c 'echo $RT_HEAVY_LOCK_HELD' 2>/dev/null)"
[[ "$out" == 1 ]] || fail "RT_HEAVY_LOCK_HELD не выставлен: $out"

# source берёт слот на время жизни скрипта и освобождает по выходу
bash -c ". '$lock'; [ \"\$RT_HEAVY_LOCK_HELD\" = 1 ]" 2>/dev/null || fail "source"

# CI=true и RT_HEAVY_LOCK=0: слот не берётся (оба слота заняты, команда всё равно идёт сразу)
rm -f "$tmp/release" "$tmp/held1" "$tmp/held2"
for n in 1 2; do
  bash "$lock" bash -c "touch '$tmp/held$n'; while [ ! -e '$tmp/release' ]; do sleep 0.1; done" 2>/dev/null &
done
wait_file "$tmp/held1"; wait_file "$tmp/held2"
[[ "$(CI=true timeout 5 bash "$lock" echo ci)" == ci ]] || fail "CI=true должен быть no-op"
[[ "$(RT_HEAVY_LOCK=0 timeout 5 bash "$lock" echo off)" == off ]] || fail "RT_HEAVY_LOCK=0 должен быть no-op"
touch "$tmp/release"
wait

# внешний держатель (прежняя обёртка): слот взят через FD без RT_HEAVY_LOCK_HELD, вложенный вызов не ждёт даже при двух занятых слотах
mkdir -p "$tmp/slots"
( exec 8>"$tmp/slots/slot1.lock"; flock -n 8
  exec 9>"$tmp/slots/slot2.lock"; flock -n 9
  [[ "$(env -u RT_HEAVY_LOCK_HELD timeout 5 bash "$lock" echo inner 2>/dev/null)" == inner ]] ) || fail "внешний держатель с открытым FD: вложенный вызов ждёт"

# каталог слотов недоступен на запись: одно предупреждение и no-op (форма с командой и форма source под set -euo pipefail)
if [[ "$(id -u)" != 0 ]]; then
  mkdir -p "$tmp/ro" && chmod 555 "$tmp/ro"
  [[ "$(RT_HEAVY_LOCK_DIR="$tmp/ro" timeout 5 bash "$lock" echo ro 2>/dev/null)" == ro ]] || fail "каталог только для чтения: команда должна идти"
  warns="$(RT_HEAVY_LOCK_DIR="$tmp/ro" timeout 5 bash "$lock" true 2>&1 >/dev/null | wc -l)"
  [[ "$warns" == 1 ]] || fail "ожидалось одно предупреждение, получено $warns"
  RT_HEAVY_LOCK_DIR="$tmp/ro" timeout 5 bash -c "set -euo pipefail; . '$lock'; true" 2>/dev/null || fail "source под set -e в каталоге только для чтения"
  chmod 755 "$tmp/ro"
fi
# после взятия слота stderr команды доходит до вызывающего (регрессия: exec ... 2>/dev/null глушил stderr навсегда)
[[ "$(RT_HEAVY_LOCK_DIR="$tmp/err" bash "$lock" bash -c 'echo e >&2' 2>&1 >/dev/null | grep -c '^e$')" == 1 ]] || fail "stderr команды под замком потерян"
[[ "$(RT_HEAVY_LOCK_DIR="$tmp/err" bash -c "set -euo pipefail; . '$lock'; readlink /proc/\$\$/fd/2" 2>&1 | tail -1)" != /dev/null ]] || fail "source-форма: stderr скрипта ушёл в /dev/null"

echo "heavy-lock-test: ok"
