#!/usr/bin/env bash
# Тест retry из lib.sh: заглушка падает N раз и затем проходит; при исчерпании попыток возвращается код последней неудачи;
# паузы 5/10/20/40 с (sleep подменён, секунды не тратятся); в журнал не попадают аргументы команды.  Запуск: bash этот-файл
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
# shellcheck source=infra/deploy/lib.sh
source "$here/../lib.sh"

sleeps=()
sleep() { sleeps+=("$1"); }   # подмена: паузы только записываются

calls=0
flaky() { calls=$((calls + 1)); (( calls > fail_times )); }   # падает fail_times раз, потом успех

run_retry() { calls=0; sleeps=(); fail_times="$1"; shift; retry "тест" "$@" >"$tmp/log" 2>&1; }

# 1. успех с первой попытки: без пауз, одна попытка
run_retry 0 flaky || { echo "FAIL: успешная команда вернула ошибку"; exit 1; }
[[ $calls -eq 1 && ${#sleeps[@]} -eq 0 ]] || { echo "FAIL: лишние попытки или паузы (calls=$calls)"; exit 1; }

# 2. два сбоя, затем успех: три попытки, паузы 5 и 10
run_retry 2 flaky || { echo "FAIL: retry не дождался успеха"; cat "$tmp/log"; exit 1; }
[[ $calls -eq 3 && "${sleeps[*]}" == "5 10" ]] || { echo "FAIL: calls=$calls sleeps=${sleeps[*]}"; exit 1; }
grep -q 'попытка 1 из 5' "$tmp/log" || { echo "FAIL: в журнале нет номера попытки"; exit 1; }

# 3. четыре сбоя, пятая попытка успешна: паузы 5 10 20 40
run_retry 4 flaky || { echo "FAIL: пятая попытка не засчитана"; exit 1; }
[[ $calls -eq 5 && "${sleeps[*]}" == "5 10 20 40" ]] || { echo "FAIL: calls=$calls sleeps=${sleeps[*]}"; exit 1; }

# 4. исчерпание: пять попыток, код последней неудачи, четыре паузы
rc=0; run_retry 99 flaky || rc=$?
[[ $rc -ne 0 ]] || { echo "FAIL: после исчерпания retry вернул успех"; exit 1; }
[[ $calls -eq 5 && "${sleeps[*]}" == "5 10 20 40" ]] || { echo "FAIL: исчерпание: calls=$calls sleeps=${sleeps[*]}"; exit 1; }
grep -q 'повторов больше нет' "$tmp/log" || { echo "FAIL: нет сообщения об исчерпании"; exit 1; }

# 5. код выхода сохраняется
fails7() { return 7; }
rc=0; run_retry 0 fails7 || rc=$?
[[ $rc -eq 7 ]] || { echo "FAIL: код выхода 7 потерян (rc=$rc)"; exit 1; }

# 6. секреты из аргументов в журнал не попадают
secret_cmd() { return 1; }
retry "метка" secret_cmd SUPER-SECRET-TOKEN >"$tmp/log" 2>&1 || true
! grep -q 'SUPER-SECRET-TOKEN' "$tmp/log" || { echo "FAIL: аргумент команды попал в журнал"; exit 1; }

# 7. настройка через RT_RETRY_MAX / RT_RETRY_DELAY
calls=0; sleeps=(); fail_times=99
RT_RETRY_MAX=3 RT_RETRY_DELAY=1 retry "тест" flaky >"$tmp/log" 2>&1 || true
[[ $calls -eq 3 && "${sleeps[*]}" == "1 2" ]] || { echo "FAIL: RT_RETRY_*: calls=$calls sleeps=${sleeps[*]}"; exit 1; }

echo "retry-test: ok"
