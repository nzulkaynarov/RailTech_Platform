#!/usr/bin/env bash
# Предупреждение о плановом обновлении (DECISIONS 2026-11-23). Пишет и снимает файл maintenance.json, который Caddy отдаёт на
# доменах Платформы и Cabinet (/maintenance.json) и который показывают баннеры обеих SPA за 30 минут до starts_at.
#   scripts/maintenance-notice.sh set <ЧЧ:ММ> [минут=3] [planned|urgent]   время - ташкентское (Asia/Tashkent, UTC+5);
#                                                                          прошло - значит завтра
#   scripts/maintenance-notice.sh clear                                    убрать предупреждение (выкладка делает это сама)
#   scripts/maintenance-notice.sh show                                     что сейчас лежит
# На сервере (под deploy) или с рабочей станции:  ssh deploy@<хост> 'bash -s set 19:15' < scripts/maintenance-notice.sh
# Каталог - MAINTENANCE_DIR (по умолчанию /opt/rt/maintenance, монтируется в Caddy на чтение). Запись атомарна: временный файл + mv.
set -euo pipefail

dir="${MAINTENANCE_DIR:-/opt/rt/maintenance}"
file="$dir/maintenance.json"
tz="Asia/Tashkent"

usage() { echo "usage: maintenance-notice.sh set <HH:MM> [minutes=3] [planned|urgent] | clear | show" >&2; exit 2; }

cmd="${1:-}"
case "$cmd" in
  set)
    at="${2:-}"; minutes="${3:-3}"; kind="${4:-planned}"
    [[ "$at" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]] || { echo "время - ЧЧ:ММ (00:00-23:59), получено: '$at'" >&2; usage; }
    [[ "$minutes" =~ ^[0-9]{1,3}$ ]] && ((minutes >= 1)) || { echo "минут - целое от 1, получено: '$minutes'" >&2; usage; }
    [[ "$kind" == planned || "$kind" == urgent ]] || { echo "kind - planned или urgent, получено: '$kind'" >&2; usage; }
    now="${MAINTENANCE_NOW:-now}"   # MAINTENANCE_NOW - только для тестов
    today="$(TZ=$tz date -d "$now" +%F)"
    target="$(TZ=$tz date -d "$today $at" +%s)"
    if ((target <= $(TZ=$tz date -d "$now" +%s))); then
      target="$(TZ=$tz date -d "$today $at + 1 day" +%s)"
    fi
    starts_at="$(TZ=$tz date -d "@$target" +%Y-%m-%dT%H:%M:%S%:z)"
    mkdir -p "$dir"
    tmp="$(mktemp "$dir/.maintenance.XXXXXX")"
    trap 'rm -f "$tmp"' EXIT
    printf '{"starts_at":"%s","minutes":%s,"kind":"%s"}\n' "$starts_at" "$minutes" "$kind" > "$tmp"
    chmod 644 "$tmp"   # Caddy в контейнере читает от другого пользователя
    mv -f "$tmp" "$file"
    trap - EXIT
    echo "предупреждение записано: $(cat "$file")"
    ;;
  clear)
    rm -f "$file"
    echo "предупреждение снято"
    ;;
  show)
    if [[ -f "$file" ]]; then cat "$file"; else echo "предупреждения нет"; fi
    ;;
  *) usage ;;
esac
