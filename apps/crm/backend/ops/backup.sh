#!/usr/bin/env bash
# Бэкап RailTech (ADR-0013, runbook docs/runbooks/backup-restore.md):
# pg_dump (custom format) + копия бакетов RustFS → $BACKUP_DIR/<UTC-штамп>/, ротация.
#
#   backup.sh --once     один бэкап (make backup)
#   backup.sh --daemon   ежедневно в $BACKUP_AT_UTC (по умолчанию 22:00 UTC = 03:00 Ташкент)
#                        и по запросу из CRM (файл $BACKUP_DIR/request_now, проверка раз в 30 с);
#                        каждые 30 с пишет $BACKUP_DIR/heartbeat (epoch) — CRM видит, что демон жив
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/backups}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
AT_UTC="${BACKUP_AT_UTC:-22:00}"
PG_BIN="${PG_BIN:-/usr/lib/postgresql/16/bin}"

log() { printf '{"event":"%s","ts":"%s"}\n' "$1" "$(date -u +%FT%TZ)"; }

backup_once() {
  local stamp dir
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  dir="$BACKUP_DIR/$stamp"
  mkdir -p "$dir.partial"
  log "backup_started"
  PGPASSWORD="$POSTGRES_PASSWORD" "$PG_BIN/pg_dump" -h "$POSTGRES_HOST" -p "${POSTGRES_PORT:-5432}" \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner --file "$dir.partial/db.dump"
  python -m app s3-mirror --dest "$dir.partial/s3"
  (cd "$dir.partial" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
  mv "$dir.partial" "$dir"
  date -u +%s > "$BACKUP_DIR/last_success"
  find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -name '20*' -mtime +"$KEEP_DAYS" -exec rm -rf {} +
  find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -name '*.partial' -mmin +360 -exec rm -rf {} +
  log "backup_done:$stamp"
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
    # Плановый бэкап по расписанию или раньше — по флагу request_now от CRM («Сделать сейчас»).
    while true; do
      due=$(( $(date -u +%s) + $(seconds_until) ))
      while (( $(date -u +%s) < due )); do
        date -u +%s > "$BACKUP_DIR/heartbeat"
        if [[ -f "$BACKUP_DIR/request_now" ]]; then
          rm -f "$BACKUP_DIR/request_now"
          log "backup_requested"
          break
        fi
        sleep 30
      done
      # Пока идёт бэкап (минуты), heartbeat пишет фоновый цикл — CRM не считает демон зависшим.
      ( while true; do date -u +%s > "$BACKUP_DIR/heartbeat"; sleep 30; done ) &
      beat_pid=$!
      backup_once || log "backup_failed"
      kill "$beat_pid" 2>/dev/null || true
    done
    ;;
  -h|--help) sed -n '2,8p' "$0" ;;
  *) echo "usage: backup.sh [--once|--daemon]" >&2; exit 2 ;;
esac
