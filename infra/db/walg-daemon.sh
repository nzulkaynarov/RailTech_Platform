#!/usr/bin/env bash
# Боковой сервис `walg` (VPS 2, S0-3): рядом с PostgreSQL, пользователь postgres, сокет БД и каталог данных общие с `postgres`.
# Непрерывный архив WAL делает сам PostgreSQL (archive_command = rt-walg wal-push %p); здесь — всё остальное:
#   - ежедневная базовая копия в $WAL_BASEBACKUP_AT_UTC (по умолчанию 21:00 UTC; первая — сразу при первом запуске),
#     затем удаление копий и WAL старше $WAL_KEEP_DAYS (14) дней, кроме копии, покрывающей границу срока
#     (wal-g delete before FIND_FULL <эта копия>) — восстановление на любой момент внутри срока остаётся возможным;
#   - если задано внешнее S3 (BACKUP_EXT_*): каждые 5 минут rclone copy бакета WAL в него (копия уже зашифрована WAL-G,
#     повторно не шифруется; удаления из основного хранилища не переносятся — срок хранения во внешнем применяется отдельно);
#   - проверка восстановления: раз в месяц ($WAL_CHECK_DAY, по умолчанию 1-го числа, в 02:00 UTC) и один раз вскоре после
#     первой копии — rt-pitr check;
#   - раз в 6 часов wal-g wal-verify: нет ли дыр в цепочке сегментов WAL;
#   - отметки в $WALG_STATE_DIR (/walg-state): started, backup_last_success, backup_last_failure, check_last_success,
#     check_last_failure, verify_last_success, verify_last_failure, ext_last_success (секунды Unix) — их читает
#     walg-healthcheck.sh (healthcheck контейнера).
# Журнал — JSON-строки в stdout контейнера. Значения секретов в журнал не попадают.
set -euo pipefail

STATE_DIR="${WALG_STATE_DIR:-/walg-state}"
KEEP_DAYS="${WAL_KEEP_DAYS:-14}"
AT_UTC="${WAL_BASEBACKUP_AT_UTC:-21:00}"
CHECK_DAY="${WAL_CHECK_DAY:-1}"
CHECK_AT_UTC="${WAL_CHECK_AT_UTC:-02:00}"
PGDATA="${PGDATA:-/var/lib/postgresql/data}"
EXT_SYNC_EVERY=300

log() { printf '{"event":"%s","ts":"%s"}\n' "$1" "$(date -u +%FT%TZ)"; }
now() { date -u +%s; }
today_at() { date -u -d "today $1" +%s; }   # секунды Unix сегодняшнего времени HH:MM UTC
day_of_month() { date -u +%-d; }
mark() { now > "$STATE_DIR/$1"; }
marker() { cat "$STATE_DIR/$1" 2>/dev/null || echo 0; }
ext_enabled() { [[ -n "${BACKUP_EXT_ENDPOINT:-}" && -n "${BACKUP_EXT_BUCKET:-}" ]]; }

rclone_remote() { # имя, endpoint, access, secret, region
  local up="${1^^}"
  export "RCLONE_CONFIG_${up}_TYPE=s3" "RCLONE_CONFIG_${up}_PROVIDER=Other" \
    "RCLONE_CONFIG_${up}_ENDPOINT=$2" "RCLONE_CONFIG_${up}_ACCESS_KEY_ID=$3" \
    "RCLONE_CONFIG_${up}_SECRET_ACCESS_KEY=$4" "RCLONE_CONFIG_${up}_REGION=${5:-}"
}

# Копия, с которой можно восстановиться на момент cutoff: последняя из завершённых не позже него. Её и всё новее — оставляем:
# `delete before <момент>` без этого удалил бы и её, и окно восстановления сузилось бы до первой копии после cutoff.
retain_from() { # источник, cutoff (секунды Unix)
  rt-walg --source "$1" backup-list --detail --json 2>/dev/null \
    | jq -r --argjson t "$2" '[.[] | select((.finish_time | sub("\\.[0-9]+"; "") | fromdateiso8601) <= $t)] | sort_by(.finish_time) | last | .backup_name // empty'
}

retention_one() { # источник
  local cutoff keep
  cutoff="$(date -u -d "$KEEP_DAYS days ago" +%s)"
  keep="$(retain_from "$1" "$cutoff")"
  if [[ -z "$keep" ]]; then log "walg_retention_nothing_to_delete:$1"; return 0; fi
  # FIND_FULL: если keep — не полная копия, остаётся и полная, на которую она опирается.
  rt-walg --source "$1" delete before FIND_FULL "$keep" --use-sentinel-time --confirm || { log "walg_retention_failed:$1"; return 1; }
  log "walg_retention_done:$1"
}

retention() { # применяется к основному хранилищу и, если оно есть, ко внешнему
  local rc=0
  retention_one primary || rc=1
  if ext_enabled; then retention_one ext || rc=1; fi
  return "$rc"
}

run_backup() {
  log "walg_backup_started"
  if timeout -k 30 4h rt-walg backup-push "$PGDATA"; then
    mark backup_last_success
    log "walg_backup_done"
    retention || true
    return 0
  fi
  mark backup_last_failure
  log "walg_backup_failed"
  return 1
}

ext_sync() {
  rclone_remote src "$WAL_S3_ENDPOINT" "$WAL_S3_ACCESS_KEY" "$WAL_S3_SECRET_KEY"
  rclone_remote ext "$BACKUP_EXT_ENDPOINT" "$BACKUP_EXT_ACCESS_KEY" "$BACKUP_EXT_SECRET_KEY" "${BACKUP_EXT_REGION:-}"
  if rclone copy "src:${WAL_S3_BUCKET:-wal}/${WAL_S3_PREFIX:-pg17}" "ext:${BACKUP_EXT_BUCKET}/wal/${WAL_S3_PREFIX:-pg17}" --s3-no-check-bucket --transfers 2 --checkers 4; then
    mark ext_last_success
  else
    log "walg_ext_sync_failed"
  fi
}

run_check() {
  local rc=0
  rt-pitr check --source primary || rc=1
  if ext_enabled; then rt-pitr check --source ext || rc=1; fi
  if [[ $rc -eq 0 ]]; then mark check_last_success; else mark check_last_failure; fi
  return 0
}

# Известная особенность PostgreSQL: checkpointer стартует ещё в режиме восстановления и засыпает на checkpoint_timeout (5 мин),
# поэтому после каждого запуска сервера archive_timeout не действует до первой контрольной точки. Сигнал SIGHUP (reload)
# будит checkpointer — после этого сегменты закрываются раз в archive_timeout (60 с). Делаем reload при каждом новом запуске сервера.
nudge_checkpointer() {
  local started
  started="$(psql -X -At -d postgres -c 'SELECT pg_postmaster_start_time()' 2>/dev/null || true)"
  [[ -n "$started" && "$started" != "${PG_STARTED_SEEN:-}" ]] || return 0
  if psql -X -At -d postgres -c 'SELECT pg_reload_conf()' >/dev/null 2>&1; then
    PG_STARTED_SEEN="$started"
    log "walg_archive_timeout_armed"
  fi
}

# Целостность архива: непрерывная ли цепочка сегментов WAL от самой старой копии до текущего, нет ли «дыр» (wal-g wal-verify).
run_verify() {
  local out
  out="$(rt-walg wal-verify integrity timeline 2>&1 || true)"
  if grep -q 'integrity check status: OK' <<<"$out" && grep -q 'timeline check status: OK' <<<"$out"; then
    mark verify_last_success
    log "walg_wal_verify_ok"
  else
    mark verify_last_failure
    log "walg_wal_verify_failed"
    printf '%s\n' "$out" | tail -n 15 >&2
  fi
}

backup_due() {
  local last sched
  last="$(marker backup_last_success)"
  [[ "$last" -gt 0 ]] || return 0   # копий ещё не было — сразу
  sched="$(today_at "$AT_UTC")"
  [[ "$(now)" -ge "$sched" && "$last" -lt "$sched" ]]
}

check_due() {
  local last fail first sched
  last="$(marker check_last_success)"
  fail="$(marker check_last_failure)"
  first="$(marker backup_last_success)"
  # Первая проверка — через час после первой успешной копии (когда в архиве уже есть сегменты после неё).
  if [[ "$last" -eq 0 && "$fail" -eq 0 ]]; then [[ "$first" -gt 0 && $(( $(now) - first )) -ge 3600 ]]; return; fi
  # После провала — повтор раз в сутки, пока проверка не пройдёт (healthcheck остаётся красным).
  if [[ "$fail" -gt "$last" ]]; then [[ $(( $(now) - fail )) -ge 86400 ]]; return; fi
  [[ "$(day_of_month)" == "$CHECK_DAY" ]] || return 1
  sched="$(today_at "$CHECK_AT_UTC")"
  [[ "$(now)" -ge "$sched" && "$last" -lt "$sched" ]]
}

main() {
  mkdir -p "$STATE_DIR"
  mark started
  log "walg_daemon_started"
  until pg_isready -q; do sleep 5; done

  local next_backup_try=0 last_ext=0 last_verify=0
  while true; do
    nudge_checkpointer
    if [[ "$(now)" -ge "$next_backup_try" ]] && backup_due; then
      run_backup || next_backup_try=$(( $(now) + 1800 ))
    fi
    if check_due; then run_check; fi
    # Раз в 6 часов, когда уже есть первая копия.
    if [[ "$(marker backup_last_success)" -gt 0 && $(( $(now) - last_verify )) -ge 21600 ]]; then
      run_verify
      last_verify="$(now)"
    fi
    if ext_enabled && [[ $(( $(now) - last_ext )) -ge $EXT_SYNC_EVERY ]]; then
      ext_sync
      last_ext="$(now)"
    fi
    sleep 30
  done
}

# Не запускать, если файл подключён через source (тест infra/deploy/tests/walg-schedule-test.sh).
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  case "${1:---daemon}" in
    --daemon) main ;;
    --backup-now) run_backup ;;
    --check-now) run_check ;;
    --verify-now) run_verify ;;
    -h|--help) sed -n '2,15p' "$0" ;;
    *) echo "usage: walg-daemon [--daemon|--backup-now|--check-now|--verify-now]" >&2; exit 2 ;;
  esac
fi
