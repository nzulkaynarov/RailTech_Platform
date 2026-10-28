#!/bin/sh
# Внешняя копия архива базы на корпоративном Google Drive (OPS-GDRIVE, решение владельца 2026-10-28; runbook
# docs/runbooks/offsite-gdrive.md). Сервис `offsite-backup` на VPS 1 рядом с RustFS (infra/compose/prod.yml), образ rclone/rclone
# (Alpine: busybox sh и awk, без bash и jq).
#   - Раз в сутки в $OFFSITE_AT_UTC (по умолчанию 23:00 UTC — через 2 ч после базовой копии WAL-G в 21:00) копирует из бакета `wal`
#     RustFS (каталог $OFFSITE_WAL_PREFIX) в папку общего диска Google Drive базовые копии WAL-G за $OFFSITE_KEEP_DAYS суток, копию,
#     покрывающую границу срока, и весь WAL начиная с неё: с такой папки восстанавливаются на любой момент окна
#     (infra/db/restore-from-gdrive.sh).
#   - Объекты уже зашифрованы WAL-G (libsodium; ключ WAL_ENC_KEY есть только на VPS 2 и офлайн), второго слоя шифрования нет.
#   - `rclone copy`, а не `sync`: пропажа объектов в RustFS не стирает копию. Срок хранения на Drive — свой, по базовым копиям самой
#     папки: всё старше копии, покрывающей границу срока, уходит в корзину общего диска (Google чистит её через 30 дней).
#   - Полоса ограничена ($OFFSITE_BWLIMIT), повторы и тайм-ауты rclone; выборка больше квоты $OFFSITE_MAX_GB не выгружается.
#   - Итог каждой попытки — status.json в бакете `offsite` RustFS (время, объём, итог, причина). Его читает CRM для строки
#     «Внешняя копия бэкапов» (ключ CRM — только чтение бакета `offsite`: ни архива, ни Drive CRM не видит).
#   - Ключ сервисного аккаунта и ID папки задаются в интерфейсе (OPS-GDRIVE-2: Admin → Подключения → «Хранилище» → «Внешняя копия
#     бэкапов»): CRM кладёт их в бакет `offsite-config` (у CRM там только запись, у offsite — только чтение), сервис забирает их раз
#     в минуту и после смены сразу копирует. Аварийный путь — файл /secrets/gdrive-sa.json и OFFSITE_GDRIVE_FOLDER_ID: если заданы,
#     они сильнее настройки из интерфейса. Нет ни того ни другого — не ошибка: итог not_configured, проверка раз в 10 минут.
# Запуск: gdrive-sync.sh [--daemon | --now | --probe | --health]. Журнал — JSON-строки в stdout; ключи, секреты и ID папки в журнал и в
# status.json не попадают.
set -eu
# Время в листингах rclone и отметках — UTC (сравнение строк «ГГГГ-ММ-ДД чч:мм:сс» с границей срока).
export TZ=UTC

STATE="${OFFSITE_STATE_DIR:-/state}"
PREFIX="${OFFSITE_WAL_PREFIX:-pg17}"
SRC="${OFFSITE_SRC:-rustfs:${OFFSITE_WAL_BUCKET:-wal}/$PREFIX}"
DST="${OFFSITE_DST:-gdrive:$PREFIX}"
STATUS_DST="${OFFSITE_STATUS_DST:-rustfs:${OFFSITE_STATUS_BUCKET:-offsite}/status.json}"
# Аварийный путь (файл на сервере и переменная .env.prod) и настройка из интерфейса (бакет offsite-config, OPS-GDRIVE-2).
SA_FILE="${OFFSITE_GDRIVE_SA_FILE:-/secrets/gdrive-sa.json}"
SA_HOST="${OFFSITE_SA_HOST_PATH:-$SA_FILE}"
ENV_FOLDER="${OFFSITE_GDRIVE_FOLDER_ID:-}"
CFG_SRC="${OFFSITE_CONFIG_SRC:-rustfs:${OFFSITE_CONFIG_BUCKET:-offsite-config}}"
CFG_DIR="$STATE/config"
SA="$SA_FILE"
FOLDER="$ENV_FOLDER"
KEEP_DAYS="${OFFSITE_KEEP_DAYS:-14}"
MAX_GB="${OFFSITE_MAX_GB:-100}"
BWLIMIT="${OFFSITE_BWLIMIT:-2M}"
AT_UTC="${OFFSITE_AT_UTC:-23:00}"
RETRY_MIN="${OFFSITE_RETRY_MIN:-30}"
RUN_TIMEOUT_S="${OFFSITE_RUN_TIMEOUT_S:-21600}"
NOT_CONFIGURED_EVERY_S=600

# rclone настраивается переменными окружения, файла конфигурации с секретами нет. RustFS — ключ сервиса `offsite` (S3_OFFSITE_*):
# чтение бакета wal и запись только в бакет offsite (infra/s3/init.sh). Drive — сервисный аккаунт, корень — папка общего диска.
export RCLONE_CONFIG_RUSTFS_TYPE=s3 RCLONE_CONFIG_RUSTFS_PROVIDER=Other \
  RCLONE_CONFIG_RUSTFS_ENDPOINT="${OFFSITE_S3_ENDPOINT:-http://rustfs:9000}" \
  RCLONE_CONFIG_RUSTFS_ACCESS_KEY_ID="${OFFSITE_S3_ACCESS_KEY:-}" \
  RCLONE_CONFIG_RUSTFS_SECRET_ACCESS_KEY="${OFFSITE_S3_SECRET_KEY:-}" \
  RCLONE_CONFIG_RUSTFS_NO_CHECK_BUCKET=true
export RCLONE_CONFIG_GDRIVE_TYPE=drive RCLONE_CONFIG_GDRIVE_SCOPE=drive \
  RCLONE_CONFIG_GDRIVE_SERVICE_ACCOUNT_FILE="$SA" RCLONE_CONFIG_GDRIVE_ROOT_FOLDER_ID="$FOLDER"
if [ -n "${OFFSITE_GDRIVE_SHARED_DRIVE_ID:-}" ]; then export RCLONE_CONFIG_GDRIVE_TEAM_DRIVE="$OFFSITE_GDRIVE_SHARED_DRIVE_ID"; fi

# rclone с сетевыми флагами. Сеть VPS 1 наружу нестабильна: повторы операции и запросов, тайм-ауты, не больше 5 запросов в секунду
# (лимиты Drive API). --use-server-modtime: время объекта S3 — из листинга (LastModified), без HEAD на каждый объект; оно же уходит на Drive.
RETRIES="${OFFSITE_RETRIES:-3}"
RETRIES_SLEEP="${OFFSITE_RETRIES_SLEEP:-30s}"
rcl() {
  rclone "$@" --retries "$RETRIES" --retries-sleep "$RETRIES_SLEEP" --low-level-retries 10 --timeout 5m --contimeout 30s --tpslimit 5 \
    --use-server-modtime
}

log() { printf '{"event":"%s","ts":"%s"%s}\n' "$1" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${2:-}"; }
now() { date -u +%s; }
iso() { date -u -d "@$1" +%Y-%m-%dT%H:%M:%SZ; }
marker() { cat "$STATE/$1" 2>/dev/null || echo 0; }
mark() { printf '%s\n' "$2" > "$STATE/$1"; }
# Строка для JSON: без кавычек, обратных косых и переводов строк, ID папки скрыт, не длиннее 300 символов.
clean() {
  if [ -n "$FOLDER" ]; then printf '%s' "$1" | sed "s#$FOLDER#<папка>#g"; else printf '%s' "$1"; fi \
    | tr -d '"' | tr -d '\134' | tr '\n\r\t' '   ' | cut -c1-300
}
qjson() { if [ -n "$1" ]; then printf '"%s"' "$1"; else printf 'null'; fi; }
njson() { if [ -n "$1" ]; then printf '%s' "$1"; else printf 'null'; fi; }

# --- выборка: что копировать и что удалять ------------------------------------------------------------------------------
# Список файлов: «ГГГГ-ММ-ДД чч:мм:сс;размер;путь» (время UTC — TZ=UTC в контейнере).
list_files() { rcl lsf -R --files-only --format tsp --separator ';' "$1"; }

# Копия, покрывающая границу срока: самая поздняя базовая копия, завершённая не позже cutoff (время её sentinel). Печатает 24 hex
# сегмента её начала или пусто (нет такой — граница не наступила, удалять нечего). Та же логика, что retain_from в walg-daemon.sh.
boundary() { # <список> <cutoff "ГГГГ-ММ-ДД чч:мм:сс">
  awk -F';' -v cut="$2" '
    $3 ~ /^basebackups_005\/base_[0-9A-F][0-9A-F]*_backup_stop_sentinel\.json$/ && ($1 "") <= cut {
      if (($1 "") > bt || (($1 "") == bt && $3 > bp)) { bt = $1 ""; bp = $3 }
    }
    END { if (bp != "") print substr(bp, 22, 24) }' "$1"
}

# Делит список на «оставить» (keep) и «старше границы» (drop). Сравнение — строками ("x" спереди): 24 hex из одних цифр awk иначе
# сравнил бы как числа с потерей точности. Файлы истории веток (00000002.history) и всё незнакомое остаются всегда.
split_by() { # <граница или пусто> <keep|drop> < список
  awk -F';' -v b="$1" -v mode="$2" '
    function keep(h) { return b == "" || ("x" h) >= ("x" b) }
    {
      p = $3; k = 1
      if (p ~ /^basebackups_005\/base_[0-9A-F]{24}/) k = keep(substr(p, 22, 24))
      else if (p ~ /^wal_005\/[0-9A-F]{24}/) k = keep(substr(p, 9, 24))
      if ((mode == "keep") == (k == 1)) print
    }'
}

# Объекты WAL-G не меняются (то же имя — то же содержимое): сравнение по размеру. Полоса — OFFSITE_BWLIMIT; дольше OFFSITE_RUN_TIMEOUT_S
# новые передачи не начинаются (остаток — следующей попыткой), timeout — страховка от зависания самого rclone.
copy_list() { # <файл путей> <журнал>
  [ -s "$1" ] || return 0
  timeout "$((RUN_TIMEOUT_S + 600))" rclone copy "$SRC" "$DST" --files-from-raw "$1" \
    --retries "$RETRIES" --retries-sleep "$RETRIES_SLEEP" --low-level-retries 10 --timeout 5m --contimeout 30s --tpslimit 5 \
    --use-server-modtime --size-only --bwlimit "$BWLIMIT" --transfers 2 --checkers 4 --drive-chunk-size 8M \
    --drive-stop-on-upload-limit --max-duration "${RUN_TIMEOUT_S}s" --log-level NOTICE --stats 30m --stats-one-line 2>> "$2"
}

sum_bytes() { awk -F';' '{ s += $2 } END { printf "%.0f\n", s + 0 }' "$1"; }

# Сводка по списку на Drive: «объектов;байт;базовых копий;самая ранняя копия;самая поздняя» (время копии — её sentinel).
summary() {
  awk -F';' '
    { n++; s += $2 }
    $3 ~ /^basebackups_005\/base_[0-9A-F]*_backup_stop_sentinel\.json$/ {
      c++; t = $1 ""
      if (lo == "" || t < lo) lo = t
      if (t > hi) hi = t
    }
    END { printf "%d;%.0f;%d;%s;%s\n", n, s + 0, c, lo, hi }' "$1"
}
to_iso() { if [ -n "$1" ]; then printf '%s' "$1" | sed 's/ /T/; s/$/Z/'; fi; }

# --- причина сбоя по журналу rclone -------------------------------------------------------------------------------------
classify() { # <журнал>
  if grep -qiE 'do not have storage quota' "$1"; then echo not_shared_drive
  elif grep -qiE 'storageQuotaExceeded|teamDriveFileLimitExceeded|numChildrenInNonRootLimitExceeded|storage quota|uploadLimitExceeded|upload limit' "$1"; then echo quota
  elif grep -qiE 'invalid_grant|unauthorized_client|invalid_client|Error 401|insufficientFilePermissions|insufficientPermissions|teamDriveMembershipRequired|File not found|notFound|credentials|couldn.t find root|Error 403' "$1" \
    && ! grep -qiE 'rateLimitExceeded' "$1"; then echo access
  elif grep -qiE 'max transfer duration|max-duration' "$1"; then echo timeout
  elif grep -qiE 'dial tcp|i/o timeout|connection reset|connection refused|no such host|TLS handshake|deadline exceeded|unexpected EOF|network is unreachable|rateLimitExceeded' "$1"; then echo network
  else echo error
  fi
}
last_error() { grep -E 'ERROR|CRITICAL|Failed' "$1" 2>/dev/null | tail -n 1 || true; }

message_of() { # <причина>
  case "$1" in
    no_key) echo "Нет ключа сервисного аккаунта Google: загрузите его в Платформе (Admin → Подключения → «Хранилище» → «Внешняя копия бэкапов»)" ;;
    bad_key) echo "Ключ сервисного аккаунта не принят (нужен JSON с type service_account): загрузите его заново в Платформе; аварийный файл — $SA_HOST" ;;
    no_folder) echo "Не задан ID папки общего диска: укажите его в Платформе (Admin → Подключения → «Хранилище» → «Внешняя копия бэкапов»)" ;;
    access) echo "Google Drive отказал в доступе: ключ отозван, папка не найдена или у сервисного аккаунта нет роли «Менеджер контента»" ;;
    not_shared_drive) echo "Папка не на общем диске: у сервисного аккаунта нет своего места, нужна папка общего диска (Shared Drive)" ;;
    quota) echo "Нет места: квота общего диска Google или предел $MAX_GB ГБ копии" ;;
    timeout) echo "Копирование не уложилось в $((RUN_TIMEOUT_S / 3600)) ч и продолжится следующей попыткой" ;;
    network) echo "Нет связи с Google Drive: сеть сервера или ограничение запросов" ;;
    source) echo "Не удалось прочитать архив WAL в хранилище RustFS (бакет wal)" ;;
    source_empty) echo "В архиве WAL нет ни одной базовой копии — копировать нечего, копия на Drive не тронута" ;;
    *) echo "Копирование на Google Drive завершилось ошибкой" ;;
  esac
}

# --- итог попытки -------------------------------------------------------------------------------------------------------
write_status() { # <итог ok|fail|not_configured> <причина> [техническая строка]
  result="$1" reason="$2" detail="$(clean "${3:-}")"
  attempt="$(now)"
  mark last_attempt "$attempt"; mark last_result "$result"
  last_ok="$(marker last_success)"
  [ "$last_ok" -gt 0 ] && last_iso="$(iso "$last_ok")" || last_iso=""
  stats="$(cat "$STATE/stats" 2>/dev/null || echo ';;;;')"
  objects="$(echo "$stats" | cut -d';' -f1)"; bytes="$(echo "$stats" | cut -d';' -f2)"; bases="$(echo "$stats" | cut -d';' -f3)"
  oldest="$(to_iso "$(echo "$stats" | cut -d';' -f4)")"; newest="$(to_iso "$(echo "$stats" | cut -d';' -f5)")"
  message=""
  [ "$result" = ok ] || message="$(message_of "$reason")"
  body="$(printf '{"schema":1,"result":"%s","reason":"%s","message":"%s","detail":"%s","attempt_at":"%s","last_success_at":%s,"duration_s":%s,"bytes":%s,"objects":%s,"base_backups":%s,"oldest_base_at":%s,"newest_base_at":%s,"quota_bytes":%s,"keep_days":%s,"prefix":"%s"}' \
    "$result" "$reason" "$(clean "$message")" "$detail" "$(iso "$attempt")" "$(qjson "$last_iso")" "$(njson "${DURATION:-}")" \
    "$(njson "$bytes")" "$(njson "$objects")" "$(njson "$bases")" "$(qjson "$oldest")" "$(qjson "$newest")" \
    "$((MAX_GB * 1073741824))" "$KEEP_DAYS" "$(clean "$PREFIX")")"
  printf '%s\n' "$body" > "$STATE/status.json"
  if printf '%s\n' "$body" | rcl rcat "$STATUS_DST" 2> "$STATE/status-write.log"; then
    log "offsite_status_written" ",\"result\":\"$result\",\"reason\":\"$reason\""
  else
    log "offsite_status_write_failed" ",\"result\":\"$result\""
    tail -n 3 "$STATE/status-write.log" >&2 || true
  fi
}

# Настройка из интерфейса: объекты бакета offsite-config (gdrive-sa.json, settings.json) копируются в том состояния, когда меняются
# (отметка — список объектов с размером и временем). Новая настройка — копирование сразу (файл force). Хранилище не ответило —
# остаётся прежняя копия настройки. Аварийный путь сильнее: файл ключа на сервере, ID папки в переменной окружения.
load_config() {
  stamp="$(rcl lsf --format tsp --separator ';' "$CFG_SRC" 2>/dev/null | grep -E ';(gdrive-sa|settings)\.json$' | sort | tr '\n' ' ' || true)"
  if [ -n "$stamp" ] && [ "$stamp" != "$(cat "$STATE/config_stamp" 2>/dev/null || true)" ]; then
    mkdir -p "$CFG_DIR"; chmod 700 "$CFG_DIR"
    if rcl copyto "$CFG_SRC/gdrive-sa.json" "$CFG_DIR/gdrive-sa.json.new" 2>/dev/null \
      && rcl copyto "$CFG_SRC/settings.json" "$CFG_DIR/settings.json" 2>/dev/null; then
      chmod 600 "$CFG_DIR/gdrive-sa.json.new"; mv "$CFG_DIR/gdrive-sa.json.new" "$CFG_DIR/gdrive-sa.json"
      sed -n 's/.*"folder_id"[[:space:]]*:[[:space:]]*"\([A-Za-z0-9_-]*\)".*/\1/p' "$CFG_DIR/settings.json" | head -n 1 > "$CFG_DIR/folder_id"
      printf '%s' "$stamp" > "$STATE/config_stamp"
      : > "$STATE/force"
      log "offsite_config_loaded"
    else
      rm -f "$CFG_DIR/gdrive-sa.json.new"
    fi
  fi
  if [ -s "$SA_FILE" ]; then SA="$SA_FILE"; else SA="$CFG_DIR/gdrive-sa.json"; fi
  if [ -n "$ENV_FOLDER" ]; then FOLDER="$ENV_FOLDER"; else FOLDER="$(cat "$CFG_DIR/folder_id" 2>/dev/null || true)"; fi
  export RCLONE_CONFIG_GDRIVE_SERVICE_ACCOUNT_FILE="$SA" RCLONE_CONFIG_GDRIVE_ROOT_FOLDER_ID="$FOLDER"
}

config_problem() { # пусто — настроено, иначе причина
  if [ ! -s "$SA" ] || [ ! -r "$SA" ]; then echo no_key; return; fi
  if ! grep -q '"type"[[:space:]]*:[[:space:]]*"service_account"' "$SA" || ! grep -q '"private_key"' "$SA"; then echo bad_key; return; fi
  if [ -z "$FOLDER" ]; then echo no_folder; return; fi
}

fail_run() { # <причина> [журнал]
  detail=""
  [ -z "${2:-}" ] || detail="$(last_error "$2")"
  log "offsite_sync_failed" ",\"reason\":\"$1\""
  [ -z "${2:-}" ] || tail -n 15 "$2" | sed "s#${FOLDER:-<нет>}#<папка>#g" >&2 || true
  write_status fail "$1" "$detail"
  return 1
}

run_once() {
  load_config
  rm -f "$STATE/force"
  problem="$(config_problem)"
  if [ -n "$problem" ]; then
    log "offsite_not_configured" ",\"reason\":\"$problem\""
    write_status not_configured "$problem"
    return 0
  fi
  started="$(now)"; DURATION=""
  work="$(mktemp -d)"
  log "offsite_sync_started"
  cutoff="$(date -u -d "@$((started - KEEP_DAYS * 86400))" '+%Y-%m-%d %H:%M:%S')"

  # 1. Что есть в архиве и что из этого входит в окно.
  if ! list_files "$SRC" > "$work/src.lst" 2> "$work/src.log"; then rc=0; fail_run source "$work/src.log" || rc=$?; rm -rf "$work"; return "$rc"; fi
  if ! grep -qE ';basebackups_005/base_[0-9A-F]*_backup_stop_sentinel\.json$' "$work/src.lst"; then
    rc=0; fail_run source_empty || rc=$?; rm -rf "$work"; return "$rc"
  fi
  if grep -qE ';basebackups_005/base_[0-9A-F]*_D_' "$work/src.lst"; then
    # Дельта-копии WAL-G не используются (WALG_DELTA_MAX_STEPS не задан). Появились — срок хранения по полным копиям не годится:
    # копируем всё, ничего не удаляем, пока правило не пересмотрят.
    keep_from=""; log "offsite_delta_backups_found_retention_off"
  else
    keep_from="$(boundary "$work/src.lst" "$cutoff")"
  fi
  split_by "$keep_from" keep < "$work/src.lst" > "$work/sel.lst"
  cut -d';' -f3- "$work/sel.lst" > "$work/sel.paths"
  need="$(sum_bytes "$work/sel.lst")"
  quota=$((MAX_GB * 1073741824))
  if [ "$need" -gt "$quota" ]; then
    printf 'ERROR: выборка %s байт больше квоты OFFSITE_MAX_GB=%s ГБ\n' "$need" "$MAX_GB" > "$work/quota.log"
    rc=0; fail_run quota "$work/quota.log" || rc=$?; rm -rf "$work"; return "$rc"
  fi

  # 2. Копия на Drive (только новое: объекты WAL-G не меняются). Сначала данные и WAL, отметки окончания копий (sentinel) — последними:
  # прерванная копия не оставит на Drive «готовую» базовую копию без её данных (restore-from-gdrive.sh берёт самую свежую отметку).
  grep -v '_backup_stop_sentinel\.json$' "$work/sel.paths" > "$work/data.paths" || true
  grep '_backup_stop_sentinel\.json$' "$work/sel.paths" > "$work/sentinel.paths" || true
  if ! rcl mkdir "$DST" 2> "$work/copy.log" || ! copy_list "$work/data.paths" "$work/copy.log" \
    || ! copy_list "$work/sentinel.paths" "$work/copy.log"; then
    rc=0; fail_run "$(classify "$work/copy.log")" "$work/copy.log" || rc=$?; rm -rf "$work"; return "$rc"
  fi

  # 3. Срок хранения на Drive — по базовым копиям самой папки: старше копии, покрывающей границу, — в корзину общего диска.
  if ! list_files "$DST" > "$work/dst.lst" 2> "$work/dst.log"; then
    rc=0; fail_run "$(classify "$work/dst.log")" "$work/dst.log" || rc=$?; rm -rf "$work"; return "$rc"
  fi
  if grep -qE ';basebackups_005/base_[0-9A-F]*_D_' "$work/dst.lst"; then dst_from=""; else dst_from="$(boundary "$work/dst.lst" "$cutoff")"; fi
  split_by "$dst_from" drop < "$work/dst.lst" | cut -d';' -f3- > "$work/drop.paths"
  if [ -s "$work/drop.paths" ]; then
    # Наоборот: сначала отметки старых копий (копия перестаёт считаться готовой), затем их данные и WAL.
    grep '_backup_stop_sentinel\.json$' "$work/drop.paths" > "$work/drop1.paths" || true
    grep -v '_backup_stop_sentinel\.json$' "$work/drop.paths" > "$work/drop2.paths" || true
    for list in "$work/drop1.paths" "$work/drop2.paths"; do
      [ -s "$list" ] || continue
      if ! rcl delete "$DST" --files-from-raw "$list" 2>> "$work/delete.log"; then
        rc=0; fail_run "$(classify "$work/delete.log")" "$work/delete.log" || rc=$?; rm -rf "$work"; return "$rc"
      fi
    done
    rcl rmdirs "$DST/basebackups_005" --leave-root 2>/dev/null || true
    log "offsite_retention_done" ",\"deleted\":$(wc -l < "$work/drop.paths" | tr -d ' ')"
  fi
  split_by "$dst_from" keep < "$work/dst.lst" > "$work/kept.lst"
  summary "$work/kept.lst" > "$STATE/stats"

  DURATION=$(( $(now) - started ))
  mark last_success "$(now)"
  log "offsite_sync_done" ",\"seconds\":$DURATION,\"objects\":$(cut -d';' -f1 "$STATE/stats"),\"bytes\":$(cut -d';' -f2 "$STATE/stats")"
  write_status ok ""
  rm -rf "$work"
}

# Одна попытка за раз: демон и ручной запуск (--now) не пересекаются.
locked_run() {
  if ! mkdir "$STATE/lock" 2>/dev/null; then
    if [ $(( $(now) - $(stat -c %Y "$STATE/lock" 2>/dev/null || echo 0) )) -gt $((RUN_TIMEOUT_S + 1200)) ]; then
      rmdir "$STATE/lock" 2>/dev/null || true; mkdir "$STATE/lock"
    else
      log "offsite_sync_busy"; return 75
    fi
  fi
  rc=0; run_once || rc=$?
  rmdir "$STATE/lock" 2>/dev/null || true
  return "$rc"
}

# Восстановить отметку последнего успеха из status.json, если том состояния пуст (новый сервер, пересоздан том).
recover_marker() {
  [ "$(marker last_success)" -eq 0 ] || return 0
  prev="$(rcl cat "$STATUS_DST" 2>/dev/null | sed -n 's/.*"last_success_at":"\([^"]*\)".*/\1/p' | head -n 1)"
  [ -n "$prev" ] || return 0
  epoch="$(date -u -d "$(printf '%s' "$prev" | sed 's/T/ /; s/Z$//')" +%s 2>/dev/null || true)"
  [ -z "$epoch" ] || mark last_success "$epoch"
}

due() {
  [ ! -e "$STATE/force" ] || return 0
  t="$(now)"; last_try="$(marker last_attempt)"; last_ok="$(marker last_success)"
  result="$(cat "$STATE/last_result" 2>/dev/null || echo none)"
  if [ "$result" = not_configured ]; then [ $((t - last_try)) -ge "$NOT_CONFIGURED_EVERY_S" ]; return; fi
  if [ "$result" != ok ]; then [ $((t - last_try)) -ge $((RETRY_MIN * 60)) ]; return; fi
  [ $((t - last_ok)) -lt 86400 ] || return 0
  sched="$(date -u -d "$(date -u +%Y-%m-%d) $AT_UTC" +%s)"
  [ "$t" -ge "$sched" ] && [ "$last_ok" -lt "$sched" ]
}

# Блокировка /state/lock лежит в томе и переживает контейнер: деплой пересоздаёт его, и копия, прерванная SIGKILL, оставила бы
# блокировку на 6 ч 20 мин (без копий, healthcheck при этом «healthy»). Демон — единственный, кто стартует вместе с контейнером:
# любая блокировка на этот момент — от прежнего контейнера, её снимаем.
clear_stale_lock() {
  if [ -d "$STATE/lock" ]; then
    rmdir "$STATE/lock" 2>/dev/null || rm -rf "$STATE/lock"
    log "offsite_stale_lock_removed"
  fi
}

daemon() {
  log "offsite_daemon_started" ",\"at_utc\":\"$AT_UTC\",\"keep_days\":$KEEP_DAYS,\"bwlimit\":\"$BWLIMIT\""
  clear_stale_lock
  # SIGTERM (docker stop): sh как PID 1 без обработчика его игнорирует и получает SIGKILL через 10 с. Обработчик снимает блокировку
  # и выходит; пауза — `sleep & wait`, чтобы сигнал обрабатывался сразу, а не после sleep. Во время самого копирования сигнал
  # дождётся rclone — этот случай закрывает clear_stale_lock при следующем старте.
  trap 'rmdir "$STATE/lock" 2>/dev/null || true; log offsite_daemon_stopped; exit 0' TERM INT
  recover_marker
  while true; do
    mark heartbeat "$(now)"
    load_config
    if due; then locked_run || true; fi
    sleep 60 &
    wait $! || true
  done
}

# Диагностика связи и доступа (runbook offsite-gdrive.md, раздел 3): список папки на Drive и бакета архива, без копирования.
probe() {
  load_config
  problem="$(config_problem)"
  if [ -n "$problem" ]; then echo "не настроено: $(message_of "$problem")"; return 3; fi
  work="$(mktemp -d)"; rc=0
  if rcl lsf --max-depth 1 "${DST%"$PREFIX"}" > /dev/null 2> "$work/drive.log"; then echo "Google Drive: папка доступна"
  else reason="$(classify "$work/drive.log")"; echo "Google Drive: $(message_of "$reason")"; last_error "$work/drive.log" | sed "s#$FOLDER#<папка>#g"; rc=1; fi
  if rcl lsf --max-depth 1 "$SRC" > /dev/null 2> "$work/src.log"; then echo "архив WAL в RustFS: читается"
  else echo "архив WAL в RustFS: $(message_of source)"; last_error "$work/src.log"; rc=1; fi
  rm -rf "$work"
  return "$rc"
}

# healthcheck контейнера: цикл жив (отметка свежее 10 минут) или идёт копирование. Итог копирования — строка CRM, не здоровье.
health() {
  if [ -d "$STATE/lock" ]; then exit 0; fi
  [ $(( $(now) - $(marker heartbeat) )) -lt 600 ] || { echo "offsite-backup: цикл не отмечался больше 10 минут"; exit 1; }
}

# OFFSITE_LIB=1 — только функции (тест infra/deploy/tests/offsite-gdrive-test.sh подключает файл через «.»).
[ "${OFFSITE_LIB:-}" != 1 ] || return 0
mkdir -p "$STATE"
case "${1:---daemon}" in
  --daemon) daemon ;;
  --now)
    # Код выхода: 0 — скопировано, 1 — сбой, 3 — не настроено, 75 — копирование уже идёт (демон), итог — в status.json.
    rc=0; locked_run || rc=$?
    [ "$rc" -eq 75 ] || cat "$STATE/status.json" 2>/dev/null || true
    if [ "$rc" -eq 0 ] && [ "$(cat "$STATE/last_result" 2>/dev/null)" = not_configured ]; then rc=3; fi
    exit "$rc" ;;
  --health) health ;;
  --probe) rc=0; probe || rc=$?; exit "$rc" ;;
  -h|--help) sed -n '2,20p' "$0" ;;
  *) echo "usage: gdrive-sync.sh [--daemon|--now|--probe|--health]" >&2; exit 2 ;;
esac
