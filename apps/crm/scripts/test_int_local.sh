#!/usr/bin/env bash
# Integration-тесты бэкенда на ОДНОРАЗОВЫХ контейнерах (Postgres+pgvector, RustFS) — как в CI.
# Никогда не направляйте их на БД dev-стенда: тесты делают TRUNCATE всех таблиц.
set -euo pipefail

# ITEST_NS — пространство имён прогона (как ERP_TEST_NS у ERP): контейнеры rt-itest-<ns>-pg/-s3, порты выдаёт
# Docker (свободные). Два прогона с разными ITEST_NS не мешают друг другу; без ITEST_NS всё как прежде.
NS="${ITEST_NS:+-$ITEST_NS}"
PG_NAME="rt-itest${NS}-pg"
S3_NAME="rt-itest${NS}-s3"
if [ -n "$NS" ]; then
  PG_PUBLISH="127.0.0.1::5432"
  S3_PUBLISH="127.0.0.1::9000"
else
  PG_PORT="${ITEST_PG_PORT:-55432}"
  S3_PORT="${ITEST_S3_PORT:-59000}"
  PG_PUBLISH="127.0.0.1:${PG_PORT}:5432"
  S3_PUBLISH="127.0.0.1:${S3_PORT}:9000"
fi
PG_IMAGE="${ITEST_PG_IMAGE:-pgvector/pgvector:0.8.7-pg17}"
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

Переменные: ITEST_NS (пространство имён: контейнеры rt-itest-<ns>-*, порты выдаёт Docker; для параллельных
прогонов), ITEST_PG_PORT (55432) и ITEST_S3_PORT (59000) — только без ITEST_NS, ITEST_PG_IMAGE, ITEST_S3_IMAGE.
Порты слушают только 127.0.0.1. После работы: [ITEST_NS=<ns>] scripts/test_int_local.sh --down
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
  docker run -d --name "$PG_NAME" -p "$PG_PUBLISH" \
    -e POSTGRES_DB=railtech_test -e POSTGRES_USER=railtech -e POSTGRES_PASSWORD="$PASS" "$PG_IMAGE" >/dev/null
fi
if ! docker inspect "$S3_NAME" >/dev/null 2>&1; then
  docker run -d --name "$S3_NAME" -p "$S3_PUBLISH" \
    -e RUSTFS_ACCESS_KEY=railtech -e RUSTFS_SECRET_KEY="$PASS" -e RUSTFS_ADDRESS=0.0.0.0:9000 "$S3_IMAGE" >/dev/null
fi
docker start "$PG_NAME" "$S3_NAME" >/dev/null
if [ -n "$NS" ]; then  # порт, выданный Docker (остаётся прежним, пока контейнер существует)
  PG_PORT="$(docker port "$PG_NAME" 5432/tcp | head -n1 | sed 's/.*://')"
  S3_PORT="$(docker port "$S3_NAME" 9000/tcp | head -n1 | sed 's/.*://')"
fi

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
