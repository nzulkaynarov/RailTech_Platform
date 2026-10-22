#!/usr/bin/env bash
# Установка и обновление БД-сервера (VPS 2): сертификат TLS, pg_hba.conf с IP VPS 1, контейнеры rt-db,
# идемпотентный prod-init.sh (роли, базы, расширение; повторный запуск применяет смену паролей из .env.db).
# Образ postgres собирается со встроенным WAL-G (infra/db/Dockerfile.postgres), включается WAL-архив (docs/runbooks/backup-pitr.md).
# Запускать от root (у пользователя deploy sudo нет): chown сертификата на uid 999 — пользователь postgres в контейнере.
#   db-up.sh        Файлы: $RT_DB_DIR/.env.db (создаёт владелец, chmod 600), certs/, pg_hba.conf (создаются здесь)
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
infra="$(cd "$here/.." && pwd)"
RT_DB_DIR="${RT_DB_DIR:-/opt/rt-db}"
envf="$RT_DB_DIR/.env.db"
[[ $EUID -eq 0 ]] || { echo "db-up.sh запускается от root (sudo у deploy нет): ssh root@<VPS 2> $0" >&2; exit 1; }

[[ -f "$envf" ]] || { echo "нет $envf (VPS 1: infra/deploy/make-env-prod.sh extract-db)" >&2; exit 1; }
get() { grep -E "^$1=" "$envf" | tail -1 | cut -d= -f2-; }
if grep -qE '^[A-Z0-9_]+=.*(CHANGE_ME|192\.0\.2\.[0-9]+([:/].*)?$)' "$envf"; then
  echo "в $envf остались CHANGE_ME или адреса-заглушки 192.0.2.x" >&2; exit 1
fi
app_ip="$(get APP_INTERNAL_IP)"; db_ip="$(get DB_INTERNAL_IP)"
backup_dir="$(get RT_BACKUP_DIR || true)"
mkdir -p "$RT_DB_DIR/certs" "${backup_dir:-/var/backups/rt}"

if [[ ! -f "$RT_DB_DIR/certs/server.key" ]]; then
  echo "▸ самоподписанный сертификат сервера (10 лет, SAN: $db_ip)"
  openssl req -x509 -newkey rsa:4096 -nodes -days 3650 -subj "/CN=rt-db" \
    -addext "subjectAltName=IP:$db_ip" \
    -keyout "$RT_DB_DIR/certs/server.key" -out "$RT_DB_DIR/certs/server.crt" 2>/dev/null
fi
chown 999:999 "$RT_DB_DIR/certs/server.key" "$RT_DB_DIR/certs/server.crt"
chmod 600 "$RT_DB_DIR/certs/server.key"

echo "▸ pg_hba.conf: доступ только с $app_ip"
sed "s#@APP_INTERNAL_IP@#$app_ip#g" "$infra/db/pg_hba.conf.tpl" | tee "$RT_DB_DIR/pg_hba.conf" >/dev/null
chown 999:999 "$RT_DB_DIR/pg_hba.conf"

dc() { docker compose -f "$infra/compose/db.yml" --env-file "$envf" "$@"; }
# WAL-архив (S0-3): без этих переменных compose не соберёт db.yml — говорим понятно и заранее.
for v in WAL_S3_ENDPOINT WAL_S3_ACCESS_KEY WAL_S3_SECRET_KEY WAL_ENC_KEY; do
  [[ -n "$(get "$v")" ]] || { echo "в $envf нет $v: VPS 1 — infra/deploy/make-env-prod.sh init, затем extract-db (docs/runbooks/backup-pitr.md, «Включение на проде»)" >&2; exit 1; }
done
echo "▸ docker compose build (образ postgres со встроенным WAL-G)"
dc build postgres
# Гейт CPU: прод-VPS отдают «QEMU Virtual CPU 2.5+» без x86-64-v2 (servers.md). Бинарь wal-g должен стартовать на самом сервере —
# проверка здесь, до перезапуска боевой базы.
docker run --rm --network none --entrypoint wal-g rt-db-postgres:local --version \
  || { echo "wal-g не запускается на CPU этого сервера — PostgreSQL не перезапущен (docs/runbooks/servers.md, «CPU прод-VPS»)" >&2; exit 1; }
echo "▸ docker compose up (rt-db)"
dc up -d --build
echo "▸ ожидание готовности PostgreSQL"
for _ in $(seq 1 30); do
  [[ "$(dc ps --format '{{.Health}}' postgres)" == healthy ]] && break
  sleep 5
done
echo "▸ роли и базы (идемпотентно)"
dc exec -T -u postgres postgres bash /docker-entrypoint-initdb.d/10-prod-init.sh
# Конфигурация pg_hba читается при reload — на случай смены IP VPS 1.
dc exec -T -u postgres postgres psql -U postgres -d postgres -tAc "SELECT pg_reload_conf()" >/dev/null
dc ps
