#!/usr/bin/env bash
# Первичный запуск dev-стенда RailTech CRM на локальном компьютере.
# Идемпотентен: повторный запуск не перезаписывает .env и не теряет данные.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/.env"
WITH_OBS=0
TIMEOUT_S=300

usage() {
  cat <<USAGE
Использование: scripts/bootstrap_dev.sh [--observability] [--timeout SEC]

Что делает:
  1. Проверяет docker, docker compose, openssl, curl.
  2. Создаёт .env из .env.example (если .env ещё нет) и заменяет CHANGE_ME
     случайными значениями.
  3. Собирает образы и поднимает dev-стенд (make up). Миграции Alembic
     применяются сервисом migrate автоматически.
  4. Ждёт, пока GET /ready вернёт 200, и печатает следующие шаги.

Опции:
  --observability  дополнительно поднять Langfuse (профиль observability)
  --timeout SEC    сколько ждать /ready (по умолчанию ${TIMEOUT_S})
  -h, --help       эта справка
USAGE
}

die() { echo "✖ $*" >&2; exit 1; }
# Значение переменной из .env без исполнения файла: env_get KEY DEFAULT.
env_get() {
  local v
  v="$(grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- || true)"
  echo "${v:-$2}"
}
info() { echo "▸ $*"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --observability) WITH_OBS=1 ;;
    --timeout) shift; TIMEOUT_S="${1:?--timeout требует число}" ;;
    -h|--help) usage; exit 0 ;;
    *) usage; die "Неизвестный аргумент: $1" ;;
  esac
  shift
done

check_tools() {
  command -v docker >/dev/null || die "Docker не найден. Установите Docker Desktop / Docker Engine: https://docs.docker.com/get-docker/"
  docker info >/dev/null 2>&1 || die "Docker установлен, но демон не запущен. Запустите Docker и повторите."
  docker compose version >/dev/null 2>&1 || die "Нет плагина docker compose v2. Обновите Docker."
  command -v openssl >/dev/null || die "openssl не найден (нужен для генерации секретов)."
  command -v curl >/dev/null || die "curl не найден."
}

# Переменные, появившиеся в .env.example позже (например, LITELLM_SALT_KEY, ADR-0020), дописываются
# в существующий .env; CHANGE_ME в них заменяется ниже. Существующие значения не трогаются.
add_missing_vars() {
  local line name
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^([A-Z][A-Z0-9_]*)= ]] || continue
    name="${BASH_REMATCH[1]}"
    if ! grep -q "^${name}=" "$ENV_FILE"; then
      printf '%s\n' "$line" >>"$ENV_FILE"
      info "В .env добавлена новая переменная ${name}."
    fi
  done <"$ROOT/.env.example"
}

create_env() {
  if [[ -f "$ENV_FILE" ]]; then
    info ".env уже существует — оставляю как есть, добавляю только новые переменные."
    add_missing_vars
  else
    cp "$ROOT/.env.example" "$ENV_FILE"
    info "Создан .env из .env.example."
  fi
  local tmp
  tmp="$(mktemp)"
  while IFS= read -r line || [[ -n "$line" ]]; do
    while [[ "$line" != \#* && "$line" == *CHANGE_ME* ]]; do
      line="${line/CHANGE_ME/$(openssl rand -hex 32)}"
    done
    printf '%s\n' "$line"
  done <"$ENV_FILE" >"$tmp"
  if ! cmp -s "$tmp" "$ENV_FILE"; then
    mv "$tmp" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    info "Секреты CHANGE_ME в .env заменены случайными значениями."
  else
    rm -f "$tmp"
  fi
}

start_stack() {
  cd "$ROOT"
  if [[ "$WITH_OBS" == 1 ]]; then
    info "Поднимаю dev-стенд с Langfuse (make up-obs)…"
    make up-obs
  else
    info "Поднимаю dev-стенд (make up)…"
    make up
  fi
}

wait_ready() {
  local url="${READY_URL:-http://localhost:$(env_get DEV_API_PORT 8000)/ready}"
  local deadline=$((SECONDS + TIMEOUT_S))
  info "Жду ${url} (до ${TIMEOUT_S} с)…"
  until curl -fsS "$url" >/dev/null 2>&1; do
    if (( SECONDS >= deadline )); then
      curl -sS "$url" || true
      echo
      die "/ready не вернул 200 за ${TIMEOUT_S} с. Диагностика: make ps; make logs s=api; docs/runbooks/dev-stand.md"
    fi
    sleep 3
  done
  info "/ready → 200: $(curl -fsS "$url")"
}

next_steps() {
  local http_port api_port
  http_port="$(env_get HTTP_PORT 80)"
  api_port="$(env_get DEV_API_PORT 8000)"
  cat <<NEXT

✔ dev-стенд работает.

Дальше:
  • CRM:                    http://localhost:${http_port}/
  • API:                    http://localhost:${api_port}/docs
  • RustFS console (S3):    http://localhost:$(env_get DEV_S3_CONSOLE_PORT 9001)  (S3_ACCESS_KEY / S3_SECRET_KEY из .env)
  • Langfuse (если --observability): http://localhost:$(env_get DEV_LANGFUSE_PORT 3000)
  • Проверка:               make smoke-dev
  • Логи / статус:          make logs s=api   |   make ps
  • Остановить:             make down
NEXT
}

check_tools
create_env
start_stack
wait_ready
next_steps
