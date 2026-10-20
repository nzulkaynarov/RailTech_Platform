#!/usr/bin/env bash
# Роли и базы прода (VPS 2): по роли на базу, расширение pgvector в crm, роль rt_backup (только чтение).
# Идемпотентно: выполняется при создании пустого тома (/docker-entrypoint-initdb.d) и повторно командой
#   docker exec -u postgres rt-db-postgres-1 bash /docker-entrypoint-initdb.d/10-prod-init.sh
# (db-up.sh) — так же меняются пароли ролей при ротации. Пароли берутся из окружения контейнера.
set -euo pipefail

psql_su() { psql -v ON_ERROR_STOP=1 -U postgres -d postgres "$@"; }

ensure_role() { # имя, переменная с паролем, доп. атрибуты
  local role="$1" pass="${!2:?$2 не задан}" attrs="${3:-}"
  psql_su -v role="$role" -v pass="$pass" <<'SQL' >/dev/null
SELECT format('CREATE ROLE %I LOGIN', :'role')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'role') \gexec
SELECT format('ALTER ROLE %I PASSWORD %L', :'role', :'pass') \gexec
SQL
  [[ -n "$attrs" ]] && psql_su -c "GRANT ${attrs} TO \"${role}\"" >/dev/null
  echo "role ok: ${role}"
}

ensure_db() { # база, владелец
  if ! psql_su -tAc "SELECT 1 FROM pg_database WHERE datname = '$1'" | grep -q 1; then
    psql_su -c "CREATE DATABASE \"$1\" OWNER \"$2\""
    echo "db created: $1"
  else
    echo "db ok: $1"
  fi
}

ensure_role crm_app DB_CRM_PASSWORD
ensure_role erp_app DB_ERP_PASSWORD
ensure_role litellm_app DB_LITELLM_PASSWORD
ensure_role langfuse_app DB_LANGFUSE_PASSWORD
ensure_role rt_backup DB_BACKUP_PASSWORD pg_read_all_data

ensure_db crm crm_app
ensure_db erp erp_app
ensure_db litellm litellm_app
ensure_db langfuse langfuse_app

# Базы не доступны чужим ролям: CONNECT только владельцу и rt_backup.
for db in crm erp litellm langfuse; do
  psql_su -c "REVOKE CONNECT ON DATABASE \"${db}\" FROM PUBLIC" >/dev/null
  psql_su -c "GRANT CONNECT ON DATABASE \"${db}\" TO rt_backup" >/dev/null
done

# pgvector нужен CRM (база знаний); создаёт суперпользователь — роли приложения расширений не создают.
psql -v ON_ERROR_STOP=1 -U postgres -d crm -c "CREATE EXTENSION IF NOT EXISTS vector" >/dev/null
echo "extension ok: vector (crm)"
