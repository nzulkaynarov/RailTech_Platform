#!/usr/bin/env bash
# Живой тест OPS-GDRIVE (Docker, без Google и без секретов, ≈ 3–5 минут): архив WAL-G → копия «на Drive» (offsite-sync.sh) →
# восстановление и учения из неё (infra/db/restore-from-offsite.sh --check и --latest). Drive подменён локальным каталогом
# (RESTORE_OFFSITE_REMOTE, OFFSITE_DST), RustFS — каталогом файлового хранилища WAL-G.
#  1. Одноразовый PostgreSQL из образа rt-db-postgres пишет архив WAL-G (WALG_FILE_PREFIX, шифрование libsodium) — базы crm, erp, eds,
#     базовая копия, запись A, переключение сегмента, запись B.
#  2. offsite-sync.sh --now копирует архив в «Drive»: итог ok.
#  3. restore-from-offsite.sh --check: скачивает, wal-g видит копию, разворачивает, базы на месте — учения пройдены, остатков нет.
#  4. restore-from-offsite.sh --latest: в восстановленной базе есть и A, и B (WAL после базовой копии проигран).
#  5. Неверный WAL_ENC_KEY — восстановление не проходит, и после провала не остаётся контейнера, тома и скачанной копии.
# Запуск: bash этот-файл [образ rt-db-postgres] (по умолчанию rt-db-postgres:local; нет — docker build -f infra/db/Dockerfile.postgres infra/db)
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
image="${1:-rt-db-postgres:local}"
rclone_image="$(sed -n 's|^[[:space:]]*image:[[:space:]]*\(rclone/rclone:[^[:space:]]*\)[[:space:]]*$|\1|p' "$root/infra/compose/prod.yml" | head -n 1)"
w="$(mktemp -d)"; pg=rt-offsite-live-pg
cleanup() {
  docker rm -f "$pg" >/dev/null 2>&1 || true
  "$root/infra/db/restore-pitr.sh" --drop --name rt-pitr-offsite-live >/dev/null 2>&1 || true
  "$root/infra/db/restore-pitr.sh" --drop --name rt-pitr-offsite-bad >/dev/null 2>&1 || true
  docker run --rm -v "$w:/w" --entrypoint sh "$rclone_image" -c 'rm -rf /w/*' >/dev/null 2>&1 || true
  rm -rf "$w"
}
trap cleanup EXIT
fail() { echo "FAIL: $*"; exit 1; }
docker image inspect "$image" >/dev/null 2>&1 || fail "нет образа $image: docker build -t $image -f infra/db/Dockerfile.postgres infra/db"
key="$(openssl rand -hex 32)"
printf 'WAL_ENC_KEY=%s\n' "$key" > "$w/env.db"; chmod 600 "$w/env.db"
mkdir -p "$w/archive/pg17" "$w/drive" "$w/state" "$w/status"; chmod -R 777 "$w/archive"

# 1. Архив WAL-G в файловом хранилище (как бакет wal, только на диске).
docker run -d --name "$pg" -e POSTGRES_PASSWORD=x -e WALG_FILE_PREFIX=/archive/pg17 -e WALG_LIBSODIUM_KEY="$key" \
  -e WALG_LIBSODIUM_KEY_TRANSFORM=hex -e WALG_COMPRESSION_METHOD=zstd -v "$w/archive:/archive" "$image" \
  -c archive_mode=on -c "archive_command=wal-g wal-push %p" -c archive_timeout=60 >/dev/null
for _ in $(seq 60); do docker exec -u postgres "$pg" pg_isready -q 2>/dev/null && break; sleep 1; done
sleep 3
q() { docker exec -u postgres "$pg" psql -X -v ON_ERROR_STOP=1 -At "$@"; }
for db in crm erp eds; do q -c "CREATE DATABASE $db" >/dev/null; done
q -d erp -c "CREATE TABLE t(v text); INSERT INTO t VALUES ('A')" >/dev/null
docker exec -u postgres -e WALG_FILE_PREFIX=/archive/pg17 -e WALG_LIBSODIUM_KEY="$key" -e WALG_LIBSODIUM_KEY_TRANSFORM=hex \
  -e WALG_COMPRESSION_METHOD=zstd "$pg" wal-g backup-push /var/lib/postgresql/data >/dev/null 2>&1 || fail "backup-push"
q -d erp -c "INSERT INTO t VALUES ('B')" >/dev/null
q -c "SELECT pg_switch_wal()" >/dev/null
for _ in $(seq 30); do [[ "$(q -c 'SELECT archived_count > 2 AND failed_count = 0 FROM pg_stat_archiver')" == t ]] && break; sleep 1; done
sleep 2
docker rm -f "$pg" >/dev/null
compgen -G "$w/archive/pg17/basebackups_005/*_backup_stop_sentinel.json" >/dev/null || fail "нет базовой копии в архиве"

# 2. Копия «на Drive».
printf '{"type": "service_account", "private_key": "fake"}' > "$w/sa.json"
docker run --rm -v "$w:/t" -v "$root/infra/offsite/offsite-sync.sh:/offsite/offsite-sync.sh:ro" -e TZ=UTC \
  -e OFFSITE_STATE_DIR=/t/state -e OFFSITE_SRC=/t/archive/pg17 -e OFFSITE_DST=/t/drive/pg17 -e OFFSITE_STATUS_DST=/t/status/status.json \
  -e OFFSITE_GDRIVE_SA_FILE=/t/sa.json -e OFFSITE_GDRIVE_FOLDER_ID=LIVETESTFOLDER123 \
  --entrypoint sh "$rclone_image" /offsite/offsite-sync.sh --now > "$w/sync.out" 2>&1 || { cat "$w/sync.out"; fail "offsite-sync.sh --now"; }
grep -q '"result":"ok"' "$w/status/status.json" || { cat "$w/status/status.json"; fail "итог копии не ok"; }

# 3. Учения.
export RESTORE_OFFSITE_REMOTE="$w/drive"
"$root/infra/db/restore-from-offsite.sh" --check --env-file "$w/env.db" --image "$image" --dir "$w/dl-check" --name rt-pitr-offsite-live \
  > "$w/check.out" 2>&1 || { cat "$w/check.out"; fail "restore-from-offsite --check"; }
grep -q 'учения пройдены' "$w/check.out" || { cat "$w/check.out"; fail "нет итога учений"; }
grep -q 'base_' "$w/check.out" || fail "backup-list не показал копии"
! docker inspect rt-pitr-offsite-live >/dev/null 2>&1 || fail "после учений остался контейнер"
! docker volume inspect rt-pitr-offsite-live-data >/dev/null 2>&1 || fail "после учений остался том"

# 4. Восстановление до конца архива: и A, и B.
"$root/infra/db/restore-from-offsite.sh" --latest --env-file "$w/env.db" --image "$image" --dir "$w/dl-latest" --name rt-pitr-offsite-live \
  > "$w/latest.out" 2>&1 || { cat "$w/latest.out"; fail "restore-from-offsite --latest"; }
[[ "$(docker exec -u postgres rt-pitr-offsite-live psql -X -At -U postgres -d erp -c "SELECT string_agg(v, ',' ORDER BY v) FROM t")" == A,B ]] \
  || fail "в восстановленной базе нет записей A и B"

# 5. Неверный ключ шифрования — восстановления нет.
printf 'WAL_ENC_KEY=%s\n' "$(openssl rand -hex 32)" > "$w/env.bad"
if WAL_FETCH_TIMEOUT_S=60 "$root/infra/db/restore-from-offsite.sh" --check --env-file "$w/env.bad" --image "$image" --dir "$w/dl-bad" \
  --name rt-pitr-offsite-bad > "$w/bad.out" 2>&1; then
  cat "$w/bad.out"; fail "с неверным WAL_ENC_KEY учения не должны проходить"
fi
# Провалившиеся учения после себя ничего не оставляют: ни контейнера и тома восстановления, ни скачанной копии.
! docker inspect rt-pitr-offsite-bad >/dev/null 2>&1 || fail "после провала учений остался контейнер"
! docker volume inspect rt-pitr-offsite-bad-data >/dev/null 2>&1 || fail "после провала учений остался том"
[[ -z "$(ls -A "$w/dl-bad" 2>/dev/null)" ]] || fail "после провала учений осталась скачанная копия"
echo "offsite-restore-live-test: ok"
