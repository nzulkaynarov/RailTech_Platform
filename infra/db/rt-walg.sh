#!/usr/bin/env bash
# Обёртка над wal-g (S0-3): собирает настройки WAL-G из переменных ансамбля и запускает wal-g. Лежит в образе как
# /usr/local/bin/rt-walg; её зовут archive_command / restore_command PostgreSQL, боковой сервис walg и контейнер восстановления.
#   rt-walg [--source primary|ext|file] <аргументы wal-g...>
# primary (по умолчанию) — бакет $WAL_S3_BUCKET RustFS на VPS 1: адрес $WAL_S3_ENDPOINT, ключи $WAL_S3_ACCESS_KEY/$WAL_S3_SECRET_KEY,
#   каталог в бакете $WAL_S3_PREFIX (по умолчанию pg17).
# ext — внешнее S3 (BACKUP_EXT_*): бакет $BACKUP_EXT_BUCKET, каталог wal/$WAL_S3_PREFIX/. Копия туда идёт из walg-daemon.sh.
# file — копия архива на диске, каталог $WAL_FILE_PREFIX (в нём basebackups_005/ и wal_005/): скачанная с Google Drive
#   (infra/db/restore-from-offsite.sh, OPS-GDRIVE). Только для восстановления и проверки.
# Шифрование — libsodium, ключ $WAL_ENC_KEY (64 hex-символа = 32 байта). Значения секретов никуда не печатаются.
set -euo pipefail

source=primary
if [[ "${1:-}" == --source ]]; then
  source="${2:?--source: primary|ext}"
  shift 2
fi

err() { echo "rt-walg: $*" >&2; exit 1; }

# Аварийный выключатель архива (runbook backup-pitr.md, «Крайняя мера»): пока существует файл, wal-push сообщает PostgreSQL об успехе,
# ничего не отправляя, — WAL перестаёт копиться на диске. Цепочка архива при этом рвётся; healthcheck walg краснеет, пока файл есть.
# Файл лежит в общем томе сокета (/var/run/postgresql), переживает перезапуск контейнера; ALTER SYSTEM тут не годится —
# archive_command задан флагом -c и сильнее postgresql.auto.conf.
if [[ "${1:-}" == wal-push && -e "${RT_ARCHIVE_OFF_FILE:-/var/run/postgresql/rt-archive-off}" ]]; then
  echo "rt-walg: архив приостановлен выключателем ${RT_ARCHIVE_OFF_FILE:-/var/run/postgresql/rt-archive-off}: сегмент ${2:-?} НЕ отправлен" >&2
  exit 0
fi

case "$source" in
  primary)
    export AWS_ENDPOINT="${WAL_S3_ENDPOINT:-}" AWS_ACCESS_KEY_ID="${WAL_S3_ACCESS_KEY:-}" AWS_SECRET_ACCESS_KEY="${WAL_S3_SECRET_KEY:-}"
    export AWS_REGION="${WAL_S3_REGION:-us-east-1}"
    export WALG_S3_PREFIX="s3://${WAL_S3_BUCKET:-wal}/${WAL_S3_PREFIX:-pg17}"
    [[ -n "$AWS_ENDPOINT" && -n "$AWS_ACCESS_KEY_ID" && -n "$AWS_SECRET_ACCESS_KEY" ]] \
      || err "не заданы WAL_S3_ENDPOINT / WAL_S3_ACCESS_KEY / WAL_S3_SECRET_KEY"
    ;;
  ext)
    export AWS_ENDPOINT="${BACKUP_EXT_ENDPOINT:-}" AWS_ACCESS_KEY_ID="${BACKUP_EXT_ACCESS_KEY:-}" AWS_SECRET_ACCESS_KEY="${BACKUP_EXT_SECRET_KEY:-}"
    export AWS_REGION="${BACKUP_EXT_REGION:-us-east-1}"
    export WALG_S3_PREFIX="s3://${BACKUP_EXT_BUCKET:-}/wal/${WAL_S3_PREFIX:-pg17}"
    [[ -n "$AWS_ENDPOINT" && -n "${BACKUP_EXT_BUCKET:-}" && -n "$AWS_ACCESS_KEY_ID" && -n "$AWS_SECRET_ACCESS_KEY" ]] \
      || err "внешнее хранилище не настроено (BACKUP_EXT_*)"
    ;;
  file)
    [[ -n "${WAL_FILE_PREFIX:-}" && -d "${WAL_FILE_PREFIX:-}" ]] || err "не задан или не найден каталог копии архива WAL_FILE_PREFIX"
    [[ "${1:-}" != wal-push && "${1:-}" != backup-push ]] || err "источник file — только для чтения (восстановление, проверка)"
    export WALG_FILE_PREFIX="$WAL_FILE_PREFIX"
    ;;
  *) err "--source: primary|ext|file" ;;
esac

[[ "${WAL_ENC_KEY:-}" =~ ^[0-9a-fA-F]{64}$ ]] || err "WAL_ENC_KEY должен быть 64 hex-символа (openssl rand -hex 32)"
export AWS_S3_FORCE_PATH_STYLE=true
export WALG_LIBSODIUM_KEY="$WAL_ENC_KEY" WALG_LIBSODIUM_KEY_TRANSFORM=hex
export WALG_COMPRESSION_METHOD="${WALG_COMPRESSION_METHOD:-zstd}"
# VPS 2 — 2 ГБ ОЗУ: параллелизм минимальный.
export WALG_UPLOAD_CONCURRENCY="${WALG_UPLOAD_CONCURRENCY:-2}" WALG_DOWNLOAD_CONCURRENCY="${WALG_DOWNLOAD_CONCURRENCY:-2}"
export WALG_UPLOAD_DISK_CONCURRENCY="${WALG_UPLOAD_DISK_CONCURRENCY:-1}"

# wal-push под timeout: зависание хранилища не должно быть тихим — PostgreSQL увидит сбой команды и повторит попытку.
if [[ "${1:-}" == wal-push ]]; then
  exec timeout -k 10 "${WAL_PUSH_TIMEOUT_S:-300}" wal-g "$@"
fi
exec wal-g "$@"
