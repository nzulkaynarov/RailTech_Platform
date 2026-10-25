#!/usr/bin/env bash
# pg_dump-гейт перед миграциями (VPS 1): дамп баз crm, erp и eds с VPS 2 (одноразовый контейнер с pg_dump 17) в
# $RT_STATE/predeploy/<тег>-<время>/. Нет читаемого дампа или pg_dump вернул не 0 — код выхода ≠ 0, и deploy.sh
# миграции не запускает. Код возврата pg_dump проверяется явно; частично записанный каталог удаляется по trap.
#   predeploy-dump.sh <тег>
# PG_IMAGE можно подменить (тест: infra/deploy/tests/predeploy-dump-test.sh подставляет фейковый pg_dump).
set -euo pipefail
# shellcheck source=infra/deploy/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

tag="${1:?usage: predeploy-dump.sh <тег>}"
PG_IMAGE="${PG_IMAGE:-pgvector/pgvector:0.8.7-pg17}"
# PG_DOCKER — команда docker (в тесте подменяется).
PG_DOCKER="${PG_DOCKER:-docker}"
host="$(env_get DB_INTERNAL_IP)"
out="$RT_STATE/predeploy/${tag}-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$out"
ok=0
trap '[[ $ok -eq 1 ]] || { rm -rf "$out"; echo "✘ pg_dump-гейт не пройден — миграции не запускаются" >&2; }' EXIT

dump_db() { # база, роль, имя переменной с паролем
  local db="$1" role="$2" pass
  pass="$(env_get "$3")"
  # Пароль — только через окружение процесса (-e без значения), не в командной строке.
  PGPASSWORD="$pass" "$PG_DOCKER" run --rm --user "$(id -u):$(id -g)" -e PGPASSWORD -e PGSSLMODE=require \
    -v "$out:/out" "$PG_IMAGE" \
    pg_dump -h "$host" -p 5432 -U "$role" -d "$db" --format=custom --no-owner --file "/out/$db.dump" \
    || die "pg_dump $db завершился с ошибкой"
  [[ -s "$out/$db.dump" ]] || die "дамп $db пуст"
  "$PG_DOCKER" run --rm -v "$out:/out:ro" "$PG_IMAGE" pg_restore -l "/out/$db.dump" >/dev/null \
    || die "дамп $db не читается"
  log "дамп $db: $(du -h "$out/$db.dump" | cut -f1)"
}

dump_db crm crm_app DB_CRM_PASSWORD
dump_db erp erp_app DB_ERP_PASSWORD
dump_db eds eds_app DB_EDS_PASSWORD
(cd "$out" && sha256sum -- *.dump > SHA256SUMS)
ok=1
log "pg_dump-гейт пройден: $out"
# Храним пять последних предмиграционных дампов.
# shellcheck disable=SC2012
ls -1dt "$RT_STATE"/predeploy/*/ | tail -n +6 | xargs -r rm -rf
