#!/usr/bin/env bash
# Тест S0-3 (WAL-архив PostgreSQL): конфигурация db.yml, бакет `wal`, закреплённый бинарь WAL-G, переменные make-env-prod.sh,
# настройки rt-walg и проверка аргументов restore-pitr.sh. Docker подменён заглушками там, где нужен только разбор аргументов;
# compose config — настоящий. Секретов не требует. Запуск: bash этот-файл
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fail() { echo "FAIL: $*"; exit 1; }

# 1. db.yml: архив включён, интервал 60 с, команда через rt-walg, боковой сервис walg, общий сокет и только чтение каталога данных.
sed 's/CHANGE_ME/ci-only-value/' "$root/infra/.env.prod.example" > "$tmp/env"
docker compose -f "$root/infra/compose/db.yml" --env-file "$tmp/env" config --format json > "$tmp/db.json"
cmd="$(jq -r '.services.postgres.command | join(" ")' "$tmp/db.json")"
for want in "archive_mode=on" "archive_timeout=60s" "archive_command=rt-walg wal-push %p"; do
  [[ "$cmd" == *"$want"* ]] || fail "postgres: в command нет «$want»"
done
[[ "$(jq -r '.services.postgres.image' "$tmp/db.json")" == "$(jq -r '.services.walg.image' "$tmp/db.json")" ]] \
  || fail "postgres и walg должны использовать один образ (с wal-g)"
jq -e '.services.postgres.build.dockerfile == "Dockerfile.postgres"' "$tmp/db.json" >/dev/null || fail "postgres не собирается из Dockerfile.postgres"
jq -e '.services.walg.healthcheck.test | join(" ") | contains("walg-healthcheck")' "$tmp/db.json" >/dev/null || fail "у walg нет healthcheck walg-healthcheck"
jq -e '.services.walg.volumes | map(select(.target == "/var/lib/postgresql/data" and .read_only == true)) | length == 1' "$tmp/db.json" >/dev/null \
  || fail "walg: каталог данных PostgreSQL должен быть смонтирован только на чтение"
for svc in postgres walg; do
  jq -e --arg s "$svc" '.services[$s].volumes | map(select(.target == "/var/run/postgresql")) | length == 1' "$tmp/db.json" >/dev/null \
    || fail "$svc: нет общего тома с сокетом /var/run/postgresql"
  for v in WAL_S3_ENDPOINT WAL_S3_ACCESS_KEY WAL_S3_SECRET_KEY WAL_ENC_KEY WAL_S3_BUCKET; do
    jq -e --arg s "$svc" --arg v "$v" '.services[$s].environment | has($v)' "$tmp/db.json" >/dev/null || fail "$svc: нет переменной $v"
  done
done
# Ежедневный pg_dump — второй рубеж — остаётся на месте.
jq -e '.services.backup.environment | has("BACKUP_KEEP_DAYS") and has("BACKUP_EXT_ENDPOINT")' "$tmp/db.json" >/dev/null || fail "сервис backup (pg_dump) пропал или потерял настройки"
# Без WAL_ENC_KEY compose отказывается собираться: WAL-архив не должен включиться молча без шифрования.
grep -v '^WAL_ENC_KEY=' "$tmp/env" > "$tmp/env.nokey"
if docker compose -f "$root/infra/compose/db.yml" --env-file "$tmp/env.nokey" config -q 2>/dev/null; then fail "compose собрался без WAL_ENC_KEY"; fi

# 2. prod.yml: s3-init создаёт бакет wal.
RT_IMAGE_TAG=wal-test docker compose -f "$root/infra/compose/base.yml" -f "$root/infra/compose/prod.yml" --env-file "$tmp/env" config --format json > "$tmp/prod.json"
jq -e '.services["s3-init"].environment.S3_BUCKETS | split(" ") | index("wal") != null' "$tmp/prod.json" >/dev/null || fail "prod.yml: s3-init не создаёт бакет wal"

# 3. Dockerfile.postgres: версия WAL-G и обе контрольные суммы закреплены; база образа — pgvector pg17.
df="$root/infra/db/Dockerfile.postgres"
grep -qE '^FROM pgvector/pgvector:0\.8\.7-pg17$' "$df" || fail "Dockerfile.postgres: база не pgvector/pgvector:0.8.7-pg17"
grep -qE '^ARG WALG_VERSION=v[0-9]+\.[0-9]+\.[0-9]+$' "$df" || fail "Dockerfile.postgres: версия WAL-G не закреплена"
for a in AMD64 ARM64; do
  grep -qE "^ARG WALG_SHA256_${a}=[0-9a-f]{64}\$" "$df" || fail "Dockerfile.postgres: нет SHA-256 для $a"
done
grep -q 'sha256sum -c' "$df" || fail "Dockerfile.postgres: сумма бинаря не проверяется"

# 4. make-env-prod.sh: ключ шифрования генерируется, ключи S3 подставляются, extract-db отдаёт WAL_*, drop-db-only их убирает.
envf="$tmp/.env.prod"
RT_ENV_FILE="$envf" bash "$root/infra/deploy/make-env-prod.sh" init "$envf" >/dev/null
key="$(grep '^WAL_ENC_KEY=' "$envf" | cut -d= -f2-)"
[[ "$key" =~ ^[0-9a-f]{64}$ ]] || fail "WAL_ENC_KEY не 64 hex-символа"
[[ "$key" != "$(grep '^LANGFUSE_ENCRYPTION_KEY=' "$envf" | cut -d= -f2-)" ]] || fail "WAL_ENC_KEY совпал с другим ключом"
[[ "$(grep '^WAL_S3_ACCESS_KEY=' "$envf" | cut -d= -f2-)" == "$(grep '^S3_ACCESS_KEY=' "$envf" | cut -d= -f2-)" ]] || fail "WAL_S3_ACCESS_KEY не подставлен из S3_ACCESS_KEY"
[[ "$(grep '^WAL_S3_SECRET_KEY=' "$envf" | cut -d= -f2-)" == "$(grep '^S3_SECRET_KEY=' "$envf" | cut -d= -f2-)" ]] || fail "WAL_S3_SECRET_KEY не подставлен из S3_SECRET_KEY"
grep -qE '^[A-Z0-9_]+=.*CHANGE_ME' "$envf" && fail "в сгенерированном файле остался CHANGE_ME"
bash "$root/infra/deploy/make-env-prod.sh" extract-db "$envf" > "$tmp/env.db"
for v in WAL_ENC_KEY WAL_S3_ENDPOINT WAL_S3_ACCESS_KEY WAL_S3_PREFIX WAL_KEEP_DAYS; do grep -q "^$v=" "$tmp/env.db" || fail "extract-db не отдаёт $v"; done
# Повторный init не меняет уже созданный ключ.
RT_ENV_FILE="$envf" bash "$root/infra/deploy/make-env-prod.sh" init "$envf" >/dev/null
[[ "$(grep '^WAL_ENC_KEY=' "$envf" | cut -d= -f2-)" == "$key" ]] || fail "повторный init сменил WAL_ENC_KEY"
bash "$root/infra/deploy/make-env-prod.sh" drop-db-only "$envf" >/dev/null
grep -q '^WAL_' "$envf" && fail "drop-db-only оставил WAL_* на VPS 1"
# Файл, прошедший db-up (extract-db), собирается как db.yml целиком.
sed 's/^APP_INTERNAL_IP=.*/APP_INTERNAL_IP=10.0.0.1/;s/^DB_INTERNAL_IP=.*/DB_INTERNAL_IP=10.0.0.2/' "$tmp/env.db" > "$tmp/env.db.ok"
docker compose -f "$root/infra/compose/db.yml" --env-file "$tmp/env.db.ok" config -q || fail "db.yml не собирается с .env.db из extract-db"

# 5. rt-walg: настройки WAL-G из переменных ансамбля (wal-g подменён заглушкой, печатающей окружение).
mkdir -p "$tmp/bin"
cat > "$tmp/bin/wal-g" <<'STUB'
#!/usr/bin/env bash
echo "ARGS=$*"; echo "PREFIX=$WALG_S3_PREFIX"; echo "ENDPOINT=$AWS_ENDPOINT"; echo "PATHSTYLE=$AWS_S3_FORCE_PATH_STYLE"
echo "KEYTRANSFORM=$WALG_LIBSODIUM_KEY_TRANSFORM"; echo "KEYLEN=${#WALG_LIBSODIUM_KEY}"; echo "ACCESS=$AWS_ACCESS_KEY_ID"
STUB
chmod +x "$tmp/bin/wal-g"
# walg <ПЕРЕМЕННАЯ=значение...> -- <аргументы rt-walg...>: чистое окружение, только перечисленные переменные.
walg() {
  local envs=()
  while [[ "$1" != -- ]]; do envs+=("$1"); shift; done
  shift
  env -i "PATH=$tmp/bin:$PATH" "${envs[@]}" bash "$root/infra/db/rt-walg.sh" "$@"
}
good=(WAL_S3_ENDPOINT=http://s3.test:9000 WAL_S3_ACCESS_KEY=ak WAL_S3_SECRET_KEY=sk WAL_ENC_KEY="$(printf 'a%.0s' $(seq 64))")
out="$(walg "${good[@]}" -- wal-push pg_wal/X)" || fail "rt-walg: не запустился с полным набором переменных"
grep -q '^PREFIX=s3://wal/pg17$' <<<"$out" || fail "rt-walg: префикс по умолчанию должен быть s3://wal/pg17 ($out)"
grep -q '^ARGS=wal-push pg_wal/X$' <<<"$out" || fail "rt-walg: аргументы wal-g не переданы"
grep -q '^PATHSTYLE=true$' <<<"$out" && grep -q '^KEYTRANSFORM=hex$' <<<"$out" && grep -q '^KEYLEN=64$' <<<"$out" || fail "rt-walg: path-style/ключ libsodium не настроены"
out="$(walg "${good[@]}" BACKUP_EXT_ENDPOINT=https://ext.test BACKUP_EXT_BUCKET=extb BACKUP_EXT_ACCESS_KEY=ea BACKUP_EXT_SECRET_KEY=es -- --source ext backup-list)" || fail "rt-walg --source ext не запустился"
grep -q '^PREFIX=s3://extb/wal/pg17$' <<<"$out" && grep -q '^ACCESS=ea$' <<<"$out" || fail "rt-walg --source ext: бакет/ключи внешнего хранилища не применены ($out)"
if walg "${good[@]}" -- --source ext backup-list >/dev/null 2>&1; then fail "rt-walg --source ext без BACKUP_EXT_* должен отказывать"; fi
if walg WAL_S3_ENDPOINT=http://s3.test:9000 WAL_S3_ACCESS_KEY=ak WAL_S3_SECRET_KEY=sk WAL_ENC_KEY=short -- wal-push x >/dev/null 2>&1; then fail "rt-walg принял короткий ключ шифрования"; fi
if walg WAL_ENC_KEY="$(printf 'a%.0s' $(seq 64))" -- wal-push x >/dev/null 2>&1; then fail "rt-walg запустился без адреса и ключей S3"; fi

# 6. restore-pitr.sh: разбор аргументов до обращения к Docker; боевые контейнеры (rt-db-*) тронуть нельзя.
cat > "$tmp/bin/docker" <<'STUB'
#!/usr/bin/env bash
# image inspect «успешен», остальное — как будто образа/контейнера нет; запуск контейнеров не допускается.
case "$1 $2" in
  "image inspect") exit 0 ;;
  "inspect rt-pitr"*|"volume inspect") exit 1 ;;
esac
echo "docker $*" >> "$RT_TEST_LOG"; exit 1
STUB
chmod +x "$tmp/bin/docker"
: > "$tmp/envdb"
rp() { RT_TEST_LOG="$tmp/docker.log" PATH="$tmp/bin:$PATH" bash "$root/infra/db/restore-pitr.sh" --env-file "$tmp/envdb" "$@"; }
if rp >/dev/null 2>&1; then fail "restore-pitr без --target-time/--latest должен отказывать"; fi
if rp --target-time "2026-10-22 12:00:00+00" --latest >/dev/null 2>&1; then fail "restore-pitr принял --target-time вместе с --latest"; fi
if rp --target-time "2026-10-22 12:00:00" >/dev/null 2>&1; then fail "restore-pitr принял момент без часового пояса"; fi
if rp --target-time "вчера" >/dev/null 2>&1; then fail "restore-pitr принял нечисловой момент"; fi
if rp --latest --name rt-db-postgres-1 >/dev/null 2>&1; then fail "restore-pitr принял имя боевого контейнера"; fi
# Ни одна проверка аргументов не доходит до запуска контейнеров.
[[ ! -s "$tmp/docker.log" ]] || fail "restore-pitr запускал docker при некорректных аргументах: $(cat "$tmp/docker.log")"
rp --help >/dev/null || fail "restore-pitr --help"
# Корректный момент проходит разбор (дальше упирается в заглушку Docker, это ожидаемо) и не называет формат причиной отказа.
if rp --target-time "2026-10-22 12:00:00+00" 2>&1 | grep -q 'формат момента'; then fail "restore-pitr отверг корректный момент"; fi
if rp --target-time "2026-10-22T12:00:00Z" 2>&1 | grep -q 'формат момента'; then fail "restore-pitr отверг момент с Z"; fi
echo "wal-archive-test: ok"
