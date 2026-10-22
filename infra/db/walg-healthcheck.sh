#!/usr/bin/env bash
# Healthcheck контейнера `walg` (S0-3): красный контейнер = сбой WAL-архива или бэкапа. Так же, как у контейнера `backup`
# (отметка last_success + healthcheck), только проверок несколько; причина — первой строкой вывода (docker inspect → Health).
#   1) базовая копия: последний успех не старше 26 ч (нет успеха — с запуска контейнера прошло не больше 26 ч) и нет
#      более свежего провала;
#   2) архиватор PostgreSQL: последний сбой archive_command не новее последнего успеха (pg_stat_archiver);
#   3) целостность цепочки WAL (wal-verify раз в 6 ч): нет более свежего провала;
#   4) проверка восстановления: нет более свежего провала, успех не старше 40 дней, первая прошла в течение 3 суток.
set -uo pipefail

STATE_DIR="${WALG_STATE_DIR:-/walg-state}"
now="$(date -u +%s)"
marker() { cat "$STATE_DIR/$1" 2>/dev/null || echo 0; }
bad() { echo "UNHEALTHY: $*"; exit 1; }

started="$(marker started)"
ok="$(marker backup_last_success)"
fail="$(marker backup_last_failure)"
ref="$ok"
[[ "$ref" -gt 0 ]] || ref="$started"
[[ "$ref" -gt 0 ]] || bad "walg-daemon ещё не стартовал"
(( now - ref < 93600 )) || bad "базовая копия не делалась больше 26 ч (backup_last_success=$ok)"
(( fail <= ok )) || bad "последняя базовая копия завершилась ошибкой (docker logs, rt-pitr status)"

arch="$(psql -X -At -F ' ' -d postgres -c "SELECT CASE WHEN last_failed_time IS NOT NULL AND (last_archived_time IS NULL OR last_failed_time > last_archived_time) THEN 'failing' ELSE 'ok' END FROM pg_stat_archiver" 2>/dev/null || echo unreachable)"
case "$arch" in
  ok) ;;
  failing) bad "archive_command не срабатывает (WAL копится на диске VPS 2): pg_stat_archiver.last_failed_time новее last_archived_time" ;;
  *) bad "PostgreSQL недоступен по сокету" ;;
esac

vok="$(marker verify_last_success)"
vfail="$(marker verify_last_failure)"
(( vfail <= vok )) || bad "в цепочке WAL-архива есть пропуск (wal-g wal-verify): точка во времени между копиями может не восстановиться — docker logs, rt-pitr status"

cok="$(marker check_last_success)"
cfail="$(marker check_last_failure)"
(( cfail <= cok )) || bad "проверка восстановления завершилась ошибкой (docker logs: pitr_check_failed)"
if (( cok > 0 )); then
  (( now - cok < 3456000 )) || bad "проверка восстановления не проходила больше 40 дней"
else
  (( now - started < 259200 )) || bad "первая проверка восстановления не проходила больше 3 суток"
fi
echo "healthy"
