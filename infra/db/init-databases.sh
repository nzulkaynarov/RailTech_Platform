#!/usr/bin/env bash
# Создаёт отсутствующие базы на общей инстанции PostgreSQL (ADR-0002: базы `crm` и `erp` раздельны,
# общих таблиц нет) и расширение pgvector в `crm`. Идемпотентно; запускается сервисом db-init
# (infra/compose/base.yml) при каждом `make up`. Аргументы — имена баз.
set -euo pipefail

for db in "$@"; do
  if psql -tAc "SELECT 1 FROM pg_database WHERE datname = '${db}'" | grep -q 1; then
    echo "db ok: ${db}"
  else
    psql -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"${db}\""
    echo "db created: ${db}"
  fi
done

# pgvector нужен CRM (база знаний); миграции CRM тоже создают расширение, здесь — на случай пустой базы.
psql -v ON_ERROR_STOP=1 -d crm -c "CREATE EXTENSION IF NOT EXISTS vector" >/dev/null
echo "extension ok: vector (crm)"
