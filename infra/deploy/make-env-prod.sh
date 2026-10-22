#!/usr/bin/env bash
# Файл переменных прода из шаблона infra/.env.prod.example (аналог make env для dev, но для двух серверов).
#   make-env-prod.sh init [файл]       создаёт файл (по умолчанию /opt/rt/.env.prod, chmod 600) со случайными секретами
#                                      вместо CHANGE_ME; существующий файл не перезаписывает — дописывает новые переменные
#   make-env-prod.sh extract-db [файл] печатает часть для VPS 2 (.env.db): адреса, пароли ролей, настройки бэкапа
#   make-env-prod.sh drop-db-only [файл] удаляет из файла VPS 1 переменные, нужные только VPS 2 (суперпользователь,
#                                      роль бэкапа, ключи внешнего хранилища, фраза шифрования, WAL_*) — после копирования на VPS 2
# Значения секретов скрипт на экран не печатает (extract-db печатает — перенаправляйте в файл).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
example="$here/../.env.prod.example"
cmd="${1:-}"
file="${2:-${RT_ENV_FILE:-/opt/rt/.env.prod}}"
db_regex='^(APP_INTERNAL_IP|DB_[A-Z_]+|RT_DB_DIR|RT_BACKUP_DIR|BACKUP_[A-Z_]+|WAL_[A-Z0-9_]+)='
vps2_only='^(DB_SUPERUSER_PASSWORD|DB_BACKUP_PASSWORD|BACKUP_(KEEP_DAYS|AT_UTC|EXT_[A-Z_]+|ENC_PASSPHRASE|RUSTFS_[A-Z_]+)|WAL_[A-Z0-9_]+)='

case "$cmd" in
  init)
    command -v openssl >/dev/null || { echo "openssl не найден" >&2; exit 1; }
    mkdir -p "$(dirname "$file")"
    if [[ -f "$file" ]]; then
      echo "▸ $file уже есть — добавляю только новые переменные"
      while IFS= read -r line || [[ -n "$line" ]]; do
        [[ "$line" =~ ^([A-Z][A-Z0-9_]*)= ]] || continue
        grep -q "^${BASH_REMATCH[1]}=" "$file" || { printf '%s\n' "$line" >>"$file"; echo "  + ${BASH_REMATCH[1]}"; }
      done <"$example"
    else
      ( umask 077; cp "$example" "$file" )
    fi
    tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT
    while IFS= read -r line || [[ -n "$line" ]]; do
      if [[ "$line" =~ ^([A-Z][A-Z0-9_]*)=(sk-)?CHANGE_ME$ ]]; then
        name="${BASH_REMATCH[1]}"; prefix="${BASH_REMATCH[2]:-}"
        case "$name" in
          LANGFUSE_ENCRYPTION_KEY|WAL_ENC_KEY) value="$(openssl rand -hex 32)" ;;
          *) value="${prefix}$(openssl rand -hex 24)" ;;
        esac
        printf '%s=%s\n' "$name" "$value" >>"$tmp"
        echo "  ✓ ${name} сгенерирован"
      else
        printf '%s\n' "$line" >>"$tmp"
      fi
    done <"$file"
    # Ключи S3 для выгрузки бэкапа и WAL-архива в RustFS — те же, что у самого RustFS.
    s3a="$(grep -E '^S3_ACCESS_KEY=' "$tmp" | cut -d= -f2-)"; s3s="$(grep -E '^S3_SECRET_KEY=' "$tmp" | cut -d= -f2-)"
    sed -e "s#^BACKUP_RUSTFS_ACCESS_KEY=\$#BACKUP_RUSTFS_ACCESS_KEY=$s3a#" -e "s#^BACKUP_RUSTFS_SECRET_KEY=\$#BACKUP_RUSTFS_SECRET_KEY=$s3s#" \
      -e "s#^WAL_S3_ACCESS_KEY=\$#WAL_S3_ACCESS_KEY=$s3a#" -e "s#^WAL_S3_SECRET_KEY=\$#WAL_S3_SECRET_KEY=$s3s#" "$tmp" >"$file"
    chmod 600 "$file"
    echo "▸ Готово: $file. Впишите вручную: адреса (APP_INTERNAL_IP, DB_INTERNAL_IP), домены, ACME_EMAIL, ключи моделей, токен бота, SMTP, внешнее хранилище бэкапов."
    echo "▸ BACKUP_ENC_PASSPHRASE, WAL_ENC_KEY и LITELLM_SALT_KEY сохраните офлайн: потеря = потеря внешних копий / WAL-архива / ключей провайдеров."
    ;;
  extract-db)
    grep -E "$db_regex" "$file"
    ;;
  drop-db-only)
    sed -i.bak -E "/$vps2_only/d" "$file" && rm -f "$file.bak"
    chmod 600 "$file"
    echo "▸ из $file удалены переменные, нужные только VPS 2"
    ;;
  *)
    sed -n '2,9p' "$0"; exit 2 ;;
esac
