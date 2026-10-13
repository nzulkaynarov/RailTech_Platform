#!/bin/bash
# Внешняя проверка бэкапов прод-базы: app-VPS спрашивает DB-VPS, был ли свежий УСПЕШНЫЙ бэкап.
#
# Зачем отдельная машина: скрипт бэкапа на DB-VPS не может пожаловаться на то, что его самого
# перестали запускать (упал cron, кончилось место, сервер не поднялся после ребута). Молчание
# для него неотличимо от успеха. Поэтому спрашивает СОСЕД и шумит в Sentry — туда, куда владелец
# и так смотрит. Порог 26 ч: бэкап идёт в 02:30, суточный ритм + запас на перезагрузку.
set -uo pipefail
DB_HOST=10.0.0.2
STATUS_PATH=/var/backups/railtech-db/LAST_BACKUP_STATUS
MAX_AGE_HOURS=26
STACK_DIR=/opt/railtech-b2b

alert() {
    echo "$(date -Is) ALERT $1"
    # Sentry-события шлём ИЗ backend-контейнера: там уже настроен DSN, окружение и релиз,
    # дублировать конфиг на хосте незачем. Именно `manage.py shell`, а НЕ `python -c`:
    # `sentry_sdk.init` живёт в настройках Django, и у голого интерпретатора клиента нет —
    # capture_message молча уходит в никуда, а скрипт рапортует успех (поймано 18-08).
    docker compose -f "$STACK_DIR/docker-compose.yml" -f "$STACK_DIR/docker-compose.prod.yml" \
        exec -T backend python manage.py shell -c "
import sentry_sdk
assert sentry_sdk.get_client().is_active(), 'Sentry не сконфигурирован'
sentry_sdk.capture_message('''DB backup check: $1''', level='error')
sentry_sdk.flush(5)
" >/dev/null 2>&1 || echo "$(date -Is) WARN не удалось отправить событие в Sentry"
    exit 1
}

STATUS_JSON=$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$DB_HOST" "cat $STATUS_PATH" 2>/dev/null) \
    || alert "не удалось получить статус бэкапа с DB-VPS (SSH или файла нет)"

STATUS=$(printf '%s' "$STATUS_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['status'])" 2>/dev/null) \
    || alert "статус бэкапа нечитаем: $STATUS_JSON"
TS=$(printf '%s' "$STATUS_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['ts'])")

[ "$STATUS" = "OK" ] || alert "последний бэкап завершился со статусом $STATUS ($STATUS_JSON)"

AGE_H=$(python3 -c "
from datetime import datetime, timezone
print(int((datetime.now(timezone.utc) - datetime.fromisoformat('$TS')).total_seconds() // 3600))
")
[ "$AGE_H" -le "$MAX_AGE_HOURS" ] || alert "бэкап устарел: последний успешный $AGE_H ч назад ($TS)"

echo "$(date -Is) OK бэкап свежий: $TS ($AGE_H ч назад)"
