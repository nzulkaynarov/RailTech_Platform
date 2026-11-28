#!/usr/bin/env bash
# Решение по ФАКТИЧЕСКИМ часам (ВЫКЛ-3, DECISIONS 2026-11-27): расписание GitHub на этом репозитории опаздывает на 6-9 часов,
# поэтому режим выкладки определяет текущее ташкентское время (Asia/Tashkent, UTC+5), а не то, какой крон сработал. Чистая функция, без сети.
#   clock-decision.sh phase  [epoch]   night | day
#       night - окно 00:45-05:30 по Ташкенту (00:45 включительно, 05:30 уже day): выкладывается новейший зелёный main без проверки активности;
#       day   - всё остальное время: дневные ворота (daytime-decision.sh: 30 минут тишины в Платформе, иначе баннер за 15 минут).
#   clock-decision.sh banner [epoch]   yes | no
#       yes - ночной баннер «обновление в 01:00» ещё имеет смысл: сейчас 23:30-00:44 (до 01:00 осталось от 16 до 90 минут).
#       no  - иначе. Баннер на уже прошедшее время не пишется никогда (maintenance-notice.sh перенёс бы его на завтра).
# epoch - секунды Unix, по умолчанию сейчас. Код 2 - ошибка вызова.
set -euo pipefail

usage() { echo "usage: clock-decision.sh phase|banner [epoch]" >&2; exit 2; }
[ "$#" -ge 1 ] && [ "$#" -le 2 ] || usage
cmd="$1"; now="${2:-$(date +%s)}"
[[ "$now" =~ ^[0-9]+$ ]] || usage

hm="$(TZ=Asia/Tashkent date -d "@$now" +%H:%M)"
mins=$((10#${hm%:*} * 60 + 10#${hm#*:}))

case "$cmd" in
  phase)
    if [ "$mins" -ge 45 ] && [ "$mins" -lt 330 ]; then echo night; else echo day; fi ;;
  banner)
    if [ "$mins" -ge 1410 ] || [ "$mins" -lt 45 ]; then echo yes; else echo no; fi ;;
  *) usage ;;
esac
