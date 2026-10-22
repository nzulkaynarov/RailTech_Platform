#!/usr/bin/env bash
# Восстановление PostgreSQL из WAL-архива (S0-3). Лежит в образе как /usr/local/bin/rt-pitr, запускается от пользователя
# postgres. Боевую базу не трогает никогда: работает только в указанном каталоге данных.
#   rt-pitr prepare <каталог> [--target-time "YYYY-MM-DD HH:MM:SS+00"] [--backup ИМЯ|LATEST] [--source primary|ext]
#       скачивает базовую копию (по умолчанию — последнюю, завершённую не позже момента --target-time) и пишет настройки
#       восстановления: restore_command, recovery_target_time, recovery_target_action=promote, recovery.signal
#   rt-pitr serve <каталог>
#       запускает PostgreSQL на подготовленном каталоге в переднем плане с выключенным архивом (в боевой архив писать нельзя)
#   rt-pitr check [--source primary|ext]
#       проверка восстановления (ежемесячная, из walg-daemon.sh): последняя копия + весь архив во временный каталог, запуск,
#       сверка баз и отставания по LSN с боевой базой, удаление. Код выхода 0 — всё хорошо
#   rt-pitr status
#       копии в хранилище, состояние архиватора, отметки walg-daemon
set -euo pipefail

STATE_DIR="${WALG_STATE_DIR:-/walg-state}"
RESTORE_BASE="${WALG_RESTORE_DIR:-/var/lib/walg-restore}"

log() { # событие [ключ=значение ...] — одна JSON-строка в журнал контейнера
  local ev="$1" kv val out
  shift
  out="$(printf '{"event":"%s","ts":"%s"' "$ev" "$(date -u +%FT%TZ)")"
  for kv in "$@"; do
    val="${kv#*=}"; val="${val//\"/}"; val="${val//\\/}"; val="${val//$'\n'/ }"
    out+="$(printf ',"%s":"%s"' "${kv%%=*}" "$val")"
  done
  printf '%s}\n' "$out"
}
die() { echo "rt-pitr: $*" >&2; exit 1; }

prepare() {
  local dir="${1:?rt-pitr prepare <каталог>}" target="" backup="" source=primary
  shift
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --target-time) target="${2:?}"; shift 2 ;;
      --backup) backup="${2:?}"; shift 2 ;;
      --source) source="${2:?}"; shift 2 ;;
      *) die "неизвестный аргумент: $1" ;;
    esac
  done
  if [[ -e "$dir" && -n "$(ls -A "$dir" 2>/dev/null)" ]]; then die "$dir не пуст — восстановление только в пустой каталог"; fi

  local list epoch
  list="$(rt-walg --source "$source" backup-list --detail --json)" || die "не удалось получить список копий из хранилища ($source)"
  [[ "$(jq 'length' <<<"$list")" -gt 0 ]] || die "в хранилище ($source) нет ни одной базовой копии"
  if [[ -z "$backup" ]]; then
    # Копию выбираем сами по времени окончания из метаданных (finish_time), а не по времени изменения объекта: во внешнем
    # хранилище, куда архив скопирован rclone, оно отражает момент копирования, и LATEST wal-g выбрал бы не ту копию.
    if [[ -n "$target" ]]; then
      epoch="$(date -u -d "$target" +%s)" || die "не разобрал момент времени: $target"
    else
      epoch=$(( $(date -u +%s) + 86400 ))
    fi
    backup="$(jq -r --argjson t "$epoch" '[.[] | select((.finish_time | sub("\\.[0-9]+"; "") | fromdateiso8601) <= $t)] | sort_by(.finish_time) | last | .backup_name // empty' <<<"$list")"
    [[ -n "$backup" ]] || die "нет базовой копии, завершённой до ${target:-сейчас}; самая ранняя закончилась $(jq -r 'sort_by(.finish_time) | first | .finish_time' <<<"$list")"
  fi
  echo "rt-pitr: базовая копия: $backup (источник $source)" >&2

  mkdir -p "$dir"
  chmod 0700 "$dir"
  # timeout: с неверным ключом шифрования wal-g backup-fetch не падает, а зависает.
  timeout -k 10 "${WAL_FETCH_TIMEOUT_S:-7200}" rt-walg --source "$source" backup-fetch "$dir" "$backup" \
    || die "backup-fetch не завершился успешно за ${WAL_FETCH_TIMEOUT_S:-7200} с (неверный WAL_ENC_KEY? недоступно хранилище?)"
  chmod 0700 "$dir"
  {
    echo "# --- rt-pitr: восстановление, настройки добавлены скриптом ---"
    echo "restore_command = 'rt-walg --source $source wal-fetch %f %p'"
    [[ -z "$target" ]] || echo "recovery_target_time = '$target'"
    echo "recovery_target_action = 'promote'"
  } >> "$dir/postgresql.auto.conf"
  : > "$dir/recovery.signal"
  log pitr_prepared "backup=$backup" "source=$source" "target=${target:-end-of-archive}"
}

serve() {
  local dir="${1:?rt-pitr serve <каталог>}"
  [[ -f "$dir/recovery.signal" ]] || die "$dir не подготовлен (rt-pitr prepare)"
  # archive_mode=off: восстановленный экземпляр не должен писать в боевой архив (другая ветка времени, те же имена сегментов).
  exec postgres -D "$dir" -c archive_mode=off -c listen_addresses='*' -c ssl=off -c max_connections=100 -c log_connections=off
}

psql_q() { psql -v ON_ERROR_STOP=1 -X -At "$@"; }

check() {
  local source=primary
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --source) source="${2:?}"; shift 2 ;;
      *) die "неизвестный аргумент: $1" ;;
    esac
  done
  # dir и sock — глобальные: обработчик EXIT срабатывает уже после выхода из функции.
  dir="$RESTORE_BASE/pgdata"; sock="$RESTORE_BASE/sock"
  local port=55432 started deadline
  local timeout="${WAL_CHECK_TIMEOUT_S:-3600}" max_lag="${WAL_CHECK_MAX_LAG_BYTES:-67108864}"
  local db_names="${DB_NAMES:-crm erp litellm langfuse}"
  local reason="" primary_lsn restored_lsn lag="" report=""
  started="$(date +%s)"

  cleanup() {
    pg_ctl -D "$dir" -m immediate -w stop >/dev/null 2>&1 || true
    rm -rf "$dir" "$sock"
  }
  trap cleanup EXIT
  rm -rf "$dir" "$sock" "$RESTORE_BASE/pg.log"
  mkdir -p "$sock"
  primary_lsn="$(psql_q -d postgres -c 'SELECT pg_current_wal_lsn()')" || die "боевая база недоступна по сокету"

  # Подоболочка: die внутри prepare завершает только её, и ошибка попадает в журнал событием pitr_check_failed.
  ( prepare "$dir" --source "$source" >&2 ) || { log pitr_check_failed "source=$source" "reason=не удалось скачать копию из хранилища (см. строки выше)"; return 1; }
  # Временный экземпляр: без архива, без сетевых сокетов, минимум памяти, без hot_standby — подключение появится после конца восстановления.
  pg_ctl -D "$dir" -W -l "$RESTORE_BASE/pg.log" \
    -o "-c archive_mode=off -c listen_addresses='' -c unix_socket_directories=$sock -c port=$port -c hot_standby=off -c shared_buffers=32MB -c max_connections=100 -c fsync=off -c ssl=off" start >/dev/null
  local seen_pid=0 pg_started
  pg_started="$(date +%s)"
  deadline=$(( pg_started + timeout ))
  while :; do
    if [[ "$(psql_q -h "$sock" -p "$port" -d postgres -c 'SELECT pg_is_in_recovery()' 2>/dev/null || true)" == f ]]; then break; fi
    # pg_ctl start -W возвращается раньше, чем появится postmaster.pid: «не работает» считаем, только увидев его хоть раз.
    [[ -f "$dir/postmaster.pid" ]] && seen_pid=1
    if [[ $seen_pid -eq 1 ]] && ! pg_ctl -D "$dir" status >/dev/null 2>&1; then
      reason="PostgreSQL остановился во время восстановления: $(tail -n 5 "$RESTORE_BASE/pg.log" | tr '\n' ' ')"; break
    fi
    if [[ $seen_pid -eq 0 && $(( $(date +%s) - pg_started )) -gt 120 ]]; then
      reason="PostgreSQL не запустился: $(tail -n 5 "$RESTORE_BASE/pg.log" | tr '\n' ' ')"; break
    fi
    if [[ "$(date +%s)" -gt "$deadline" ]]; then reason="восстановление не закончилось за ${timeout} с"; break; fi
    sleep 5
  done

  if [[ -z "$reason" ]]; then
    local db rt pt rv pv
    for db in $db_names; do
      if [[ "$(psql_q -h "$sock" -p "$port" -d postgres -c "SELECT count(*) FROM pg_database WHERE datname = '$db'")" != 1 ]]; then
        reason="базы $db нет в восстановленном кластере"; break
      fi
      rt="$(psql_q -h "$sock" -p "$port" -d "$db" -c "SELECT count(*) FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog','information_schema')")"
      pt="$(psql_q -d "$db" -c "SELECT count(*) FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog','information_schema')")"
      if [[ "$rt" -eq 0 && "$pt" -gt 0 ]]; then reason="$db: в восстановленной базе нет таблиц (в боевой — $pt)"; break; fi
      rv="$(psql_q -h "$sock" -p "$port" -d "$db" -c "SELECT count(*) FROM pg_extension WHERE extname = 'vector'")"
      pv="$(psql_q -d "$db" -c "SELECT count(*) FROM pg_extension WHERE extname = 'vector'")"
      if [[ "$rv" -lt "$pv" ]]; then reason="$db: нет расширения vector"; break; fi
      report+="${db}=${rt}tables "
    done
  fi
  if [[ -z "$reason" ]]; then
    restored_lsn="$(psql_q -h "$sock" -p "$port" -d postgres -c 'SELECT pg_current_wal_lsn()')"
    lag="$(psql_q -h "$sock" -p "$port" -d postgres -c "SELECT pg_wal_lsn_diff('$primary_lsn', '$restored_lsn')::bigint")"
    # Боевой LSN снят до начала проверки: восстановленный должен быть не дальше max_lag позади (архив успевает за базой).
    if [[ "$lag" -gt "$max_lag" ]]; then reason="архив отстаёт от боевой базы на $lag байт (предел $max_lag)"; fi
  fi

  if [[ -n "$reason" ]]; then
    log pitr_check_failed "source=$source" "reason=$reason"
    return 1
  fi
  log pitr_check_ok "source=$source" "seconds=$(( $(date +%s) - started ))" "lag_bytes=$lag" "databases=${report% }"
}

status() {
  local f
  echo "== базовые копии (primary)"
  rt-walg backup-list --detail 2>&1 || true
  echo "== архиватор PostgreSQL"
  psql_q -d postgres -F ' | ' -c "SELECT 'archived='||archived_count, 'failed='||failed_count, 'last_archived='||coalesce(last_archived_wal,'-')||' @ '||coalesce(last_archived_time::text,'-'), 'last_failed='||coalesce(last_failed_wal,'-')||' @ '||coalesce(last_failed_time::text,'-') FROM pg_stat_archiver" || true
  echo "== отметки walg-daemon ($STATE_DIR)"
  for f in started backup_last_success backup_last_failure verify_last_success verify_last_failure check_last_success check_last_failure ext_last_success; do
    [[ -f "$STATE_DIR/$f" ]] && printf '%s: %s (%s)\n' "$f" "$(cat "$STATE_DIR/$f")" "$(date -u -d "@$(cat "$STATE_DIR/$f")" +%FT%TZ)"
  done
  return 0
}

cmd="${1:-}"
[[ $# -eq 0 ]] || shift
case "$cmd" in
  prepare) prepare "$@" ;;
  serve) serve "$@" ;;
  check) check "$@" ;;
  status) status ;;
  *) sed -n "2,13p" "$0"; exit 2 ;;
esac
