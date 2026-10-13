#!/usr/bin/env bash
# Integration-тесты бэкенда на ОДНОРАЗОВЫХ контейнерах (Postgres+pgvector, RustFS) — как в CI.
# Никогда не направляйте их на БД dev-стенда: тесты делают TRUNCATE всех таблиц.
set -euo pipefail

PG_NAME=rt-itest-pg
S3_NAME=rt-itest-s3
PG_PORT="${ITEST_PG_PORT:-55432}"
S3_PORT="${ITEST_S3_PORT:-59000}"
PG_IMAGE="${ITEST_PG_IMAGE:-pgvector/pgvector:0.8.7-pg16}"
S3_IMAGE="${ITEST_S3_IMAGE:-rustfs/rustfs:1.0.1}"
PASS=ci-only-password
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

usage() {
  cat <<EOF
Integration-тесты на одноразовых контейнерах (скилл stand-verify).

  scripts/test_int_local.sh [pytest-аргументы]     запустить (контейнеры поднимаются при необходимости)
  scripts/test_int_local.sh --down                 остановить и удалить контейнеры
  scripts/test_int_local.sh --help

Примеры:
  scripts/test_int_local.sh                        все integration-тесты
  scripts/test_int_local.sh -k crm_actions         только тесты по маске
  scripts/test_int_local.sh tests/integration/test_migrations.py

Переменные: ITEST_PG_PORT (55432), ITEST_S3_PORT (59000), ITEST_PG_IMAGE, ITEST_S3_IMAGE.
Порты слушают только 127.0.0.1. После работы: scripts/test_int_local.sh --down
EOF
}

case "${1:-}" in
  -h|--help) usage; exit 0 ;;
  --down)
    docker rm -f "$PG_NAME" "$S3_NAME" >/dev/null 2>&1 || true
    echo "Контейнеры $PG_NAME и $S3_NAME удалены."
    exit 0 ;;
esac

command -v docker >/dev/null || { echo "Нужен Docker (на этом компьютере — Docker Desktop)."; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker не запущен: open -a Docker, затем повторите."; exit 1; }

if ! docker inspect "$PG_NAME" >/dev/null 2>&1; then
  docker run -d --name "$PG_NAME" -p "127.0.0.1:${PG_PORT}:5432" \
    -e POSTGRES_DB=railtech_test -e POSTGRES_USER=railtech -e POSTGRES_PASSWORD="$PASS" "$PG_IMAGE" >/dev/null
fi
if ! docker inspect "$S3_NAME" >/dev/null 2>&1; then
  docker run -d --name "$S3_NAME" -p "127.0.0.1:${S3_PORT}:9000" \
    -e RUSTFS_ACCESS_KEY=railtech -e RUSTFS_SECRET_KEY="$PASS" -e RUSTFS_ADDRESS=0.0.0.0:9000 "$S3_IMAGE" >/dev/null
fi
docker start "$PG_NAME" "$S3_NAME" >/dev/null

for _ in $(seq 1 30); do
  if docker exec "$PG_NAME" pg_isready -U railtech -d railtech_test >/dev/null 2>&1 \
     && curl -fsS "http://127.0.0.1:${S3_PORT}/health" >/dev/null 2>&1; then
    ready=1; break
  fi
  sleep 1
done
[ "${ready:-}" = 1 ] || { echo "Контейнеры не поднялись за 30 с: docker logs $PG_NAME / $S3_NAME"; exit 1; }

cd "$ROOT/backend"
# env -i и явные значения: переменные .env стенда (ключи, токен бота, LiteLLM) не попадают в тесты —
# настройки читают ещё и ../.env, поэтому каждый секрет перекрыт пустым или одноразовым.
env -i PATH="$PATH" HOME="$HOME" APP_ENV=test \
  POSTGRES_HOST=127.0.0.1 POSTGRES_PORT="$PG_PORT" POSTGRES_DB=railtech_test \
  POSTGRES_USER=railtech POSTGRES_PASSWORD="$PASS" \
  S3_ENDPOINT="http://127.0.0.1:${S3_PORT}" S3_ACCESS_KEY=railtech S3_SECRET_KEY="$PASS" \
  TELEGRAM_BOT_TOKEN= TELEGRAM_WEBHOOK_SECRET= TELEGRAM_MODE=disabled TELEGRAM_DRY_RUN=true \
  LITELLM_BASE_URL=http://127.0.0.1:9 LITELLM_API_KEY= LITELLM_MASTER_KEY=sk-test \
  ANTHROPIC_API_KEY= GEMINI_API_KEY= DOCLING_API_KEY= SECRETS_KEY= \
  JWT_SECRET="$(openssl rand -hex 32)" AGENT_CONTEXT_KEY="$(openssl rand -hex 32)" \
  LANGFUSE_PUBLIC_KEY= LANGFUSE_SECRET_KEY= \
  uv run pytest -m integration -q -p no:cacheprovider "$@" || status=$?
status="${status:-0}"
echo "Готово. Остановить контейнеры: scripts/test_int_local.sh --down"
exit $status
