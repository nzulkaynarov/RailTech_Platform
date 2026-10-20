#!/usr/bin/env bash
# pg_dump-гейт перед миграциями (VPS 1): дамп баз crm и erp с VPS 2 (одноразовый контейнер с pg_dump 17) в
# $RT_STATE/predeploy/<тег>-<время>/. Нет читаемого дампа — код выхода ≠ 0, и deploy.sh миграции не запускает.
#   predeploy-dump.sh <тег>
set -euo pipefail
# shellcheck source=infra/deploy/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

tag="${1:?usage: predeploy-dump.sh <тег>}"
PG_IMAGE="${PG_IMAGE:-pgvector/pgvector:0.8.7-pg17}"
host="$(env_get DB_INTERNAL_IP)"
out="$RT_STATE/predeploy/${tag}-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$out"

dump_db() { # база, роль, имя переменной с паролем
  local db="$1" role="$2" pass
  pass="$(env_get "$3")"
  # Пароль — только через окружение процесса (-e без значения), не в командной строке.
  PGPASSWORD="$pass" docker run --rm --user "$(id -u):$(id -g)" -e PGPASSWORD -e PGSSLMODE=require \
    -v "$out:/out" "$PG_IMAGE" \
    pg_dump -h "$host" -p 5432 -U "$role" -d "$db" --format=custom --no-owner --file "/out/$db.dump"
  [[ -s "$out/$db.dump" ]] || die "дамп $db пуст"
  docker run --rm -v "$out:/out:ro" "$PG_IMAGE" pg_restore -l "/out/$db.dump" >/dev/null \
    || die "дамп $db не читается"
  log "дамп $db: $(du -h "$out/$db.dump" | cut -f1)"
}

dump_db crm crm_app DB_CRM_PASSWORD || { rm -rf "$out"; die "pg_dump crm не удался — миграции не запускаются"; }
dump_db erp erp_app DB_ERP_PASSWORD || { rm -rf "$out"; die "pg_dump erp не удался — миграции не запускаются"; }
(cd "$out" && sha256sum -- *.dump > SHA256SUMS)
log "pg_dump-гейт пройден: $out"
# Храним пять последних предмиграционных дампов.
# shellcheck disable=SC2012
ls -1dt "$RT_STATE"/predeploy/*/ | tail -n +6 | xargs -r rm -rf
