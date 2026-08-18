#!/bin/bash
# Ежедневный бэкап прод-базы RailTech. Формат custom (восстанавливается pg_restore), хранение 14 дней.
# pg_dump работает от postgres (peer auth) и пишет в stdout; root перенаправляет в каталог,
# доступный только root, поэтому файл остаётся root:600.
#
# 18-08: добавлены ПРОВЕРКА и СТАТУС. Раньше скрипт писал «OK» по факту завершения pg_dump —
# битый или обрезанный дамп выглядел бы так же, а если бы cron перестал запускаться, об этом
# никто не узнал бы вовсе: лог видел только тот, кто зашёл на сервер. Бэкап, существование
# которого нельзя проверить снаружи, бэкапом не является.
set -euo pipefail
BACKUP_DIR=/var/backups/railtech-db
DB=railtech
RETENTION_DAYS=14
MIN_BYTES=100000          # заведомо меньше нормального дампа (~1.9 МБ), но больше «пустышки»
STATUS_FILE="$BACKUP_DIR/LAST_BACKUP_STATUS"
TS=$(date +%Y-%m-%d_%H%M%S)
OUT="$BACKUP_DIR/${DB}_${TS}.dump"
umask 077

write_status() {
    # Машиночитаемый статус для внешней проверки (app-VPS читает его по SSH).
    printf '{"ts":"%s","status":"%s","file":"%s","bytes":%s,"detail":"%s"}\n' \
        "$(date -Is)" "$1" "$OUT" "${2:-0}" "${3:-}" > "$STATUS_FILE"
}
fail() {
    write_status FAILED 0 "$1"
    echo "$(date -Is) FAILED $OUT — $1"
    exit 1
}
trap 'fail "неожиданная ошибка на строке $LINENO"' ERR

sudo -u postgres pg_dump -Fc --no-owner --no-privileges -d "$DB" > "$OUT" || fail "pg_dump завершился с ошибкой"

BYTES=$(stat -c %s "$OUT")
[ "$BYTES" -ge "$MIN_BYTES" ] || fail "дамп подозрительно мал: $BYTES байт"

# Дамп ЧИТАЕТСЯ pg_restore — единственная проверка, отличающая архив от набора байтов.
# Читаем от ROOT, а не от postgres: файл лежит с правами root:600, и запуск от postgres падал бы
# на «нет доступа», выдавая ложную тревогу (поймано при первом же прогоне 18-08). Соединение с
# БД тут не нужно — `--list` разбирает только сам файл.
pg_restore --list "$OUT" > /dev/null 2>&1 || fail "pg_restore не может прочитать дамп"

find "$BACKUP_DIR" -name "${DB}_*.dump" -type f -mtime +"$RETENTION_DAYS" -delete
trap - ERR
write_status OK "$BYTES"
echo "$(date -Is) OK $OUT ($(du -h "$OUT" | cut -f1), проверен pg_restore)"
