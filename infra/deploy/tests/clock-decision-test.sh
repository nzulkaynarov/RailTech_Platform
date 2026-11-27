#!/usr/bin/env bash
# Тест clock-decision.sh (ВЫКЛ-3): границы ночного окна и окна ночного баннера по ташкентскому времени. Запуск: bash этот-файл
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
clk="$here/../clock-decision.sh"
ep() { date -u -d "$1" +%s; }   # аргумент - UTC; ташкентское время = UTC+5

expect() { # <ожидание> <команда> <UTC-время> <описание>
  local got; got="$(bash "$clk" "$2" "$(ep "$3")")"
  [ "$got" = "$1" ] || { echo "FAIL: $4 ($2 при $3Z): ожидали $1, получили $got"; exit 1; }
}
# phase: 00:45 Ташкент = 19:45Z предыдущего дня; 05:30 = 00:30Z
expect day   phase "2026-11-27 19:44" "00:44 - ещё день"
expect night phase "2026-11-27 19:45" "00:45 - начало ночи"
expect night phase "2026-11-27 20:00" "01:00"
expect night phase "2026-11-28 00:29" "05:29"
expect day   phase "2026-11-28 00:30" "05:30 - уже день"
expect day   phase "2026-11-28 02:36" "07:36 - ночной крон опоздал на 6,5 часа: день"
expect day   phase "2026-11-28 05:55" "10:55 - опоздал на 9,5 часа: день"
expect day   phase "2026-11-27 18:00" "23:00"
expect day   phase "2026-11-27 12:00" "17:00"
# banner: окно 23:30-00:44 (до 01:00 от 16 до 90 минут)
expect no  banner "2026-11-27 18:29" "23:29"
expect yes banner "2026-11-27 18:30" "23:30"
expect yes banner "2026-11-27 19:30" "00:30 - штатный крон баннера"
expect yes banner "2026-11-27 19:44" "00:44"
expect no  banner "2026-11-27 19:45" "00:45 - до 01:00 меньше 16 минут"
expect no  banner "2026-11-27 20:30" "01:30 - время баннера прошло"
expect no  banner "2026-11-28 03:00" "08:00 - опоздавший крон баннера"
# переход через сутки: UTC-полночь = 05:00 Ташкента (день)
expect day phase "2026-11-28 00:30" "UTC-полночь не путает дни"
# ошибки вызова
rc=0; bash "$clk" nope >/dev/null 2>&1 || rc=$?; [ "$rc" -eq 2 ] || { echo "FAIL: неизвестная команда: код $rc"; exit 1; }
rc=0; bash "$clk" phase abc >/dev/null 2>&1 || rc=$?; [ "$rc" -eq 2 ] || { echo "FAIL: мусорное время: код $rc"; exit 1; }
# без epoch - текущее время, ответ из двух слов
case "$(bash "$clk" phase)" in night|day) ;; *) echo "FAIL: phase без epoch"; exit 1 ;; esac
echo "clock-decision-test: ok"
