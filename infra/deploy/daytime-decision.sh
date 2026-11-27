#!/usr/bin/env bash
# Решение дневной выкладки (ВЫКЛ-2, DECISIONS 2026-11-27): один тик крона каждые 15 минут. Чистая функция входов, без сети.
#   daytime-decision.sh <should> <failed 0|1> <activity N> <banner_start_epoch|-> <now_epoch>
#     should        слово из should-deploy.sh (deploy | skip-same | skip-older | skip-diverged)
#     failed        1 - кандидат в state/failed_tags (откачен автооткатом)
#     activity      число запросов за 30 минут (activity-check.sh)
#     banner_start  starts_at предупреждения на VPS 1 в секундах Unix, «-» - предупреждения нет
#     banner_end    (необязательно, 6-й аргумент) конец окна предупреждения: starts_at + minutes; по умолчанию start + 20 минут
# Печатает одно слово (код 0):
#   skip          нечего или нельзя выкладывать (уже выложен, старше, расходится, откачен)
#   deploy-now    в Платформе никого нет - выкладываем сразу, без предупреждения
#   banner        кто-то работает - ставим предупреждение на now+15 минут; выкладка - на следующем тике
#   wait          предупреждение стоит, его время ещё не пришло
#   deploy-due    время предупреждения пришло (допуск 3 минуты на дрожание крона), окно ещё не закончилось - выкладываем независимо от активности
#   Окно предупреждения закончилось (now > banner_end): люди его уже не видят, предупреждения «нет» - активность проверяется заново
#   (deploy-now или новый banner).
# Код 2 - ошибка вызова.
set -euo pipefail

[ "$#" -eq 5 ] || [ "$#" -eq 6 ] || { echo "usage: daytime-decision.sh <should> <failed 0|1> <activity N> <banner_start|-> <now> [banner_end]" >&2; exit 2; }
should="$1"; failed="$2"; activity="$3"; banner="$4"; now="$5"; banner_end="${6:--}"
[[ "$failed" =~ ^[01]$ && "$activity" =~ ^[0-9]+$ && "$now" =~ ^[0-9]+$ && ( "$banner" = "-" || "$banner" =~ ^[0-9]+$ ) && ( "$banner_end" = "-" || "$banner_end" =~ ^[0-9]+$ ) ]] \
  || { echo "daytime-decision: неверные аргументы" >&2; exit 2; }

grace=180
if [ "$banner" != "-" ]; then
  [ "$banner_end" != "-" ] || banner_end=$((banner + 1200))
  # окно предупреждения прошло - баннера для людей уже нет
  if [ "$now" -gt "$banner_end" ]; then banner="-"; fi
fi
if [ "$should" != deploy ] || [ "$failed" = 1 ]; then echo skip
elif [ "$banner" != "-" ]; then
  if [ "$now" -ge $((banner - grace)) ]; then echo deploy-due; else echo wait; fi
elif [ "$activity" -eq 0 ]; then echo deploy-now
else echo banner
fi
