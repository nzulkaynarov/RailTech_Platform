#!/usr/bin/env bash
# Бэкап PostgreSQL ансамбля (VPS 2, контейнер `backup`): pg_dump (custom) каждой базы → $BACKUP_DIR/<UTC-штамп>/,
# SHA256SUMS, проверка читаемости (pg_restore -l), ротация $BACKUP_KEEP_DAYS дней, выгрузка:
#   - ежедневно в бакет RustFS на VPS 1 (BACKUP_RUSTFS_*), открытым дампом внутри внутренней сети;
#   - раз в неделю (BACKUP_EXT_DAY, 0 = воскресенье) во внешнее S3-хранилище (BACKUP_EXT_*), зашифрованно
#     (openssl AES-256, BACKUP_ENC_PASSPHRASE) — дампы содержат данные клиентов.
# Подключение — переменные libpq (PGHOST, PGUSER, PGPASSWORD). Значения секретов в лог не попадают.
#
#   backup.sh --once     один бэкап (infra/deploy/backup-now.sh)
#   backup.sh --daemon   каждый день в $BACKUP_AT_UTC (по умолчанию 22:00 UTC = 03:00 Ташкент)
#   Расшифровка внешней копии: openssl enc -d -aes-256-cbc -pbkdf2 -in crm.dump.enc -out crm.dump -pass env:BACKUP_ENC_PASSPHRASE
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/backups}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
AT_UTC="${BACKUP_AT_UTC:-22:00}"
DB_NAMES="${DB_NAMES:-crm erp eds litellm langfuse}"
EXT_DAY="${BACKUP_EXT_DAY:-0}"
EXT_KEEP_DAYS="${BACKUP_EXT_KEEP_DAYS:-60}"

log() { printf '{"event":"%s","ts":"%s"}\n' "$1" "$(date -u +%FT%TZ)"; }

# rclone настраивается переменными окружения, файла конфигурации (с секретами) нет.
rclone_remote() { # имя, endpoint, access, secret, region
  local up="${1^^}"
  export "RCLONE_CONFIG_${up}_TYPE=s3" "RCLONE_CONFIG_${up}_PROVIDER=Other" \
    "RCLONE_CONFIG_${up}_ENDPOINT=$2" "RCLONE_CONFIG_${up}_ACCESS_KEY_ID=$3" \
    "RCLONE_CONFIG_${up}_SECRET_ACCESS_KEY=$4" "RCLONE_CONFIG_${up}_REGION=${5:-}"
}

dump_all() { # каталог назначения
  local dir="$1" db
  for db in $DB_NAMES; do
    pg_dump -d "$db" --format=custom --no-owner --file "$dir/$db.dump"
    # Дамп должен читаться и содержать объекты — иначе бэкап считается неудачным.
    if ! { [[ -s "$dir/$db.dump" ]] && pg_restore -l "$dir/$db.dump" >/dev/null; }; then
      log "backup_invalid_dump:$db"
      return 1
    fi
  done
  (cd "$dir" && sha256sum -- *.dump > SHA256SUMS)
}

upload_rustfs() { # штамп, каталог
  [[ -n "${BACKUP_RUSTFS_ENDPOINT:-}" ]] || { log "upload_rustfs_skipped"; return 0; }
  rclone_remote rustfs "$BACKUP_RUSTFS_ENDPOINT" "$BACKUP_RUSTFS_ACCESS_KEY" "$BACKUP_RUSTFS_SECRET_KEY"
  rclone copy "$2" "rustfs:${BACKUP_RUSTFS_BUCKET:-backups}/$1" --s3-no-check-bucket
  rclone delete "rustfs:${BACKUP_RUSTFS_BUCKET:-backups}" --min-age "${KEEP_DAYS}d" --s3-no-check-bucket || true
  log "upload_rustfs_done:$1"
}

upload_external() { # штамп, каталог
  [[ -n "${BACKUP_EXT_ENDPOINT:-}" && -n "${BACKUP_EXT_BUCKET:-}" ]] || { log "upload_external_skipped"; return 0; }
  [[ -n "${BACKUP_ENC_PASSPHRASE:-}" ]] || { log "upload_external_refused_no_passphrase"; return 1; }
  [[ "$(date -u +%w)" == "$EXT_DAY" || "${FORCE_EXT:-0}" == 1 ]] || return 0
  local enc f
  enc="$(mktemp -d)"
  for f in "$2"/*.dump; do
    openssl enc -aes-256-cbc -pbkdf2 -salt -in "$f" -out "$enc/$(basename "$f").enc" -pass env:BACKUP_ENC_PASSPHRASE
  done
  (cd "$enc" && sha256sum -- *.enc > SHA256SUMS)
  rclone_remote ext "$BACKUP_EXT_ENDPOINT" "$BACKUP_EXT_ACCESS_KEY" "$BACKUP_EXT_SECRET_KEY" "${BACKUP_EXT_REGION:-}"
  rclone copy "$enc" "ext:${BACKUP_EXT_BUCKET}/$1" --s3-no-check-bucket
  rclone delete "ext:${BACKUP_EXT_BUCKET}" --min-age "${EXT_KEEP_DAYS}d" --s3-no-check-bucket || true
  rm -rf "$enc"
  log "upload_external_done:$1"
}

backup_once() {
  local stamp dir rc=0
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  dir="$BACKUP_DIR/$stamp"
  mkdir -p "$dir.partial"
  log "backup_started"
  if ! dump_all "$dir.partial"; then
    rm -rf "$dir.partial"
    log "backup_failed"
    return 1
  fi
  mv "$dir.partial" "$dir"
  date -u +%s > "$BACKUP_DIR/last_success"
  find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -name '20*' -mtime +"$KEEP_DAYS" -exec rm -rf {} +
  find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -name '*.partial' -mmin +360 -exec rm -rf {} +
  log "backup_done:$stamp"
  # Сбой выгрузки не отменяет локальную копию, но делает прогон неуспешным (виден в логах и коде выхода).
  upload_rustfs "$stamp" "$dir" || { log "upload_rustfs_failed"; rc=1; }
  upload_external "$stamp" "$dir" || { log "upload_external_failed"; rc=1; }
  return "$rc"
}

seconds_until() {
  local now next
  now="$(date -u +%s)"
  next="$(date -u -d "today $AT_UTC" +%s)"
  if (( next <= now )); then next="$(date -u -d "tomorrow $AT_UTC" +%s)"; fi
  echo $(( next - now ))
}

case "${1:---once}" in
  --once) backup_once ;;
  --daemon)
    while true; do
      sleep "$(seconds_until)"
      backup_once || log "backup_run_failed"
    done
    ;;
  -h|--help) sed -n '2,13p' "$0" ;;
  *) echo "usage: backup.sh [--once|--daemon]" >&2; exit 2 ;;
esac
