#!/usr/bin/env bash
# Тест S0-3: расписание walg-daemon.sh — когда due базовая копия и проверка восстановления, healthcheck контейнера walg.
# Время и день месяца подменены (now / today_at / day_of_month), Docker не нужен. Запуск: bash этот-файл
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fail() { echo "FAIL: $*"; exit 1; }

export WALG_STATE_DIR="$tmp/state"; mkdir -p "$WALG_STATE_DIR"
# shellcheck source=/dev/null
source "$root/infra/db/walg-daemon.sh"   # охранник в конце файла: main не стартует

# «Сегодня» 2026-10-22 (четверг), расписание копии 21:00, проверки 02:00 UTC 1-го числа.
DAY=1000000
now() { echo "$NOW"; }
today_at() { case "$1" in 21:00) echo $((DAY + 21 * 3600)) ;; 02:00) echo $((DAY + 2 * 3600)) ;; *) echo "$DAY" ;; esac; }
day_of_month() { echo "$DOM"; }
set_marker() { echo "$2" > "$STATE_DIR/$1"; }
clear_markers() { rm -f "$STATE_DIR"/*; }
yes() { "$@" || fail "ожидалось due: $*  ($CASE)"; }
no() { if "$@"; then fail "ожидалось not due: $*  ($CASE)"; fi; }

# --- базовая копия
clear_markers; NOW=$((DAY + 3600)); CASE="копий ещё не было"; yes backup_due
set_marker backup_last_success $((DAY - 3600)); NOW=$((DAY + 20 * 3600)); CASE="до 21:00, копия вчера"; no backup_due
NOW=$((DAY + 21 * 3600 + 60)); CASE="после 21:00, копия вчера"; yes backup_due
set_marker backup_last_success $((DAY + 21 * 3600 + 30)); CASE="после 21:00, копия уже сделана"; no backup_due

# --- проверка восстановления
clear_markers; DOM=15; NOW=$((DAY + 3600)); CASE="копии нет"; no check_due
set_marker backup_last_success $((NOW - 1800)); CASE="копия 30 минут назад, проверки не было"; no check_due
set_marker backup_last_success $((NOW - 7200)); CASE="копия 2 часа назад, проверки не было"; yes check_due
clear_markers; set_marker check_last_success $((DAY - 10 * 86400)); set_marker backup_last_success $((DAY - 3600))
DOM=15; NOW=$((DAY + 3 * 3600)); CASE="15-е число"; no check_due
DOM=1; NOW=$((DAY + 3600)); CASE="1-е число, до 02:00"; no check_due
DOM=1; NOW=$((DAY + 3 * 3600)); CASE="1-е число, после 02:00, проверка в прошлом месяце"; yes check_due
set_marker check_last_success $((DAY + 2 * 3600 + 100)); CASE="1-е число, проверка уже прошла"; no check_due
clear_markers; set_marker check_last_failure $((DAY - 100)); set_marker backup_last_success $((DAY - 7200)); DOM=15; NOW=$DAY
CASE="провал минуту назад"; no check_due
NOW=$((DAY + 86400)); CASE="провал сутки назад — повтор"; yes check_due

# --- healthcheck (отметки и pg_stat_archiver; psql подменён)
mkdir -p "$tmp/bin"
printf '#!/usr/bin/env bash\necho "${PSQL_ANSWER:-ok}"\n' > "$tmp/bin/psql"; chmod +x "$tmp/bin/psql"
hc() { PATH="$tmp/bin:$PATH" bash "$root/infra/db/walg-healthcheck.sh"; }
real_now="$(date -u +%s)"
clear_markers
set_marker started "$real_now"; set_marker backup_last_success "$real_now"; set_marker check_last_success "$real_now"
hc >/dev/null || fail "healthcheck: ожидалось healthy при свежих отметках"
set_marker backup_last_success $((real_now - 100000)); if hc >"$tmp/o" 2>&1; then fail "healthcheck: копия старше 26 ч должна давать UNHEALTHY"; fi
grep -q 'базовая копия' "$tmp/o" || fail "healthcheck: причина не названа"
set_marker backup_last_success "$real_now"; set_marker backup_last_failure $((real_now + 1)); if hc >/dev/null 2>&1; then fail "healthcheck: провал копии новее успеха должен давать UNHEALTHY"; fi
rm "$STATE_DIR/backup_last_failure"
if PSQL_ANSWER=failing hc >"$tmp/o" 2>&1; then fail "healthcheck: сбой archive_command должен давать UNHEALTHY"; fi
grep -q 'archive_command' "$tmp/o" || fail "healthcheck: причина сбоя архива не названа"
set_marker verify_last_failure $((real_now + 1)); if hc >/dev/null 2>&1; then fail "healthcheck: провал wal-verify должен давать UNHEALTHY"; fi
rm "$STATE_DIR/verify_last_failure"
set_marker check_last_failure $((real_now + 1)); if hc >/dev/null 2>&1; then fail "healthcheck: провал проверки восстановления должен давать UNHEALTHY"; fi
rm "$STATE_DIR/check_last_failure"
# выключатель архива
touch "$tmp/off"; if RT_ARCHIVE_OFF_FILE="$tmp/off" hc >"$tmp/o" 2>&1; then fail "healthcheck: включённый выключатель архива должен давать UNHEALTHY"; fi
grep -q 'приостановлен' "$tmp/o" || fail "healthcheck: причина (выключатель) не названа"
rm "$tmp/off"
# внешняя копия: без ext_last_success после старта — healthy до часа; старая отметка — UNHEALTHY
extenv=(BACKUP_EXT_ENDPOINT=https://ext.test BACKUP_EXT_BUCKET=b)
env "${extenv[@]}" PATH="$tmp/bin:$PATH" bash "$root/infra/db/walg-healthcheck.sh" >/dev/null || fail "healthcheck: ext настроен, контейнер только стартовал — ожидалось healthy"
set_marker ext_last_success $((real_now - 7200))
if env "${extenv[@]}" PATH="$tmp/bin:$PATH" bash "$root/infra/db/walg-healthcheck.sh" >"$tmp/o" 2>&1; then fail "healthcheck: ext не обновлялся 2 ч — UNHEALTHY"; fi
grep -q 'внешн' "$tmp/o" || fail "healthcheck: причина (внешняя копия) не названа"
env PATH="$tmp/bin:$PATH" bash "$root/infra/db/walg-healthcheck.sh" >/dev/null || fail "healthcheck: ext не настроен — отметка ext не должна влиять"
rm "$STATE_DIR/ext_last_success"
# pg_wal и свободное место
mkdir -p "$tmp/pgdata/pg_wal"; head -c 3000000 /dev/zero > "$tmp/pgdata/pg_wal/seg"
if env PGDATA="$tmp/pgdata" WAL_MAX_PGWAL_MB=1 PATH="$tmp/bin:$PATH" bash "$root/infra/db/walg-healthcheck.sh" >"$tmp/o" 2>&1; then fail "healthcheck: pg_wal больше порога — UNHEALTHY"; fi
grep -q 'pg_wal' "$tmp/o" || fail "healthcheck: причина (pg_wal) не названа"
if env PGDATA="$tmp/pgdata" WAL_MIN_FREE_MB=999999999 PATH="$tmp/bin:$PATH" bash "$root/infra/db/walg-healthcheck.sh" >"$tmp/o" 2>&1; then fail "healthcheck: мало свободного места — UNHEALTHY"; fi
grep -q 'свободно' "$tmp/o" || fail "healthcheck: причина (диск) не названа"
env PGDATA="$tmp/pgdata" PATH="$tmp/bin:$PATH" bash "$root/infra/db/walg-healthcheck.sh" >/dev/null || fail "healthcheck: при пороге по умолчанию малый pg_wal должен быть healthy"
set_marker check_last_success $((real_now - 41 * 86400)); if hc >/dev/null 2>&1; then fail "healthcheck: проверка старше 40 дней должна давать UNHEALTHY"; fi
rm "$STATE_DIR/check_last_success"; set_marker started $((real_now - 4 * 86400)); set_marker backup_last_success "$real_now"
if hc >/dev/null 2>&1; then fail "healthcheck: первой проверки нет больше 3 суток — UNHEALTHY"; fi
echo "walg-schedule-test: ok"
