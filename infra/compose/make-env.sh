#!/usr/bin/env bash
# Создаёт .env в корне из .env.example и заменяет CHANGE_ME случайными значениями (make env).
# Идемпотентен: существующий .env не перезаписывается, в него только дописываются новые переменные.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EXAMPLE="$ROOT/.env.example"
ENV_FILE="$ROOT/.env"

command -v openssl >/dev/null || { echo "openssl не найден" >&2; exit 1; }

if [[ -f "$ENV_FILE" ]]; then
  echo "▸ .env уже существует — оставляю, добавляю только новые переменные."
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^([A-Z][A-Z0-9_]*)= ]] || continue
    name="${BASH_REMATCH[1]}"
    grep -q "^${name}=" "$ENV_FILE" || { printf '%s\n' "$line" >>"$ENV_FILE"; echo "  + ${name}"; }
  done <"$EXAMPLE"
else
  cp "$EXAMPLE" "$ENV_FILE"
  echo "▸ Создан .env из .env.example."
fi

# Каждому CHANGE_ME — своё значение. LITELLM_* должны начинаться с sk-; LANGFUSE_ENCRYPTION_KEY — 64 hex.
tmp="$(mktemp)"
while IFS= read -r line || [[ -n "$line" ]]; do
  if [[ "$line" =~ ^([A-Z][A-Z0-9_]*)=(sk-)?CHANGE_ME$ ]]; then
    name="${BASH_REMATCH[1]}"; prefix="${BASH_REMATCH[2]:-}"
    case "$name" in
      LANGFUSE_ENCRYPTION_KEY) value="$(openssl rand -hex 32)" ;;
      *) value="${prefix}$(openssl rand -hex 24)" ;;
    esac
    printf '%s=%s\n' "$name" "$value" >>"$tmp"
    echo "  ✓ ${name} сгенерирован"
  else
    printf '%s\n' "$line" >>"$tmp"
  fi
done <"$ENV_FILE"
mv "$tmp" "$ENV_FILE"
chmod 600 "$ENV_FILE"
echo "▸ Готово: $ENV_FILE. Ключи моделей (ANTHROPIC_API_KEY, GEMINI_API_KEY) и TELEGRAM_BOT_TOKEN впишите сами."
