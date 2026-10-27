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
  scripts/test_int_local.sh                        все integration-тесты (параллельно: до 4 воркеров xdist, у каждого своя база)
  ITEST_WORKERS=1 scripts/test_int_local.sh        то же одним процессом (отладка; ITEST_WORKERS=<N> — своё число воркеров)
  scripts/test_int_local.sh -k crm_actions         только тесты по маске
  scripts/test_int_local.sh tests/integration/test_migrations.py

Параллельность включает tests/conftest.py сама (как и в CI) — только для целого прогона: отдельный файл, тест
или -k идут одним процессом, пока не задан ITEST_WORKERS.

Переменные: ITEST_NS (пространство имён: контейнеры rt-itest-<ns>-*, порты выдаёт Docker; для параллельных
прогонов), ITEST_WORKERS (число воркеров xdist; 0 или 1 — один процесс), ITEST_PG_PORT (55432) и ITEST_S3_PORT (59000) — только без ITEST_NS, ITEST_PG_IMAGE, ITEST_S3_IMAGE.
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
# Окружение pytest — ровно то, что задаёт задание «CRM · integration» в .github/workflows/ci.yml (Q-W6-1):
# APP_ENV, POSTGRES_*, S3_*. Больше ничего: ни TELEGRAM_*, ни ключей, ни JWT_SECRET — как у раннера CI, иначе
# тест зелёный локально и красный в CI (так было в #129). Менять набор переменных — только вместе с ci.yml.
# `env -i` отсекает остальное окружение оболочки (токены, ключи разработчика); от машины зависят и потому
# остаются отличиями от CI: PATH и HOME (uv, кэш uv), адреса и порты одноразовых контейнеров
# (127.0.0.1 вместо localhost — Docker публикует порт только на IPv4), имя БД/пользователя контейнера.
# Настройки читают ещё и .env из backend/ и apps/crm/ — в CI этих файлов нет, поэтому наличие их здесь — ошибка.
for f in "$ROOT/backend/.env" "$ROOT/.env"; do
  [ ! -e "$f" ] || { echo "Найден $f: настройки CRM прочитают его, а в CI такого файла нет. Уберите файл и повторите."; exit 1; }
done
# ITEST_WORKERS (если задан) пробрасывается: на результат не влияет, только на число процессов pytest.
env -i PATH="$PATH" HOME="$HOME" ${ITEST_WORKERS:+ITEST_WORKERS="$ITEST_WORKERS"} \
  APP_ENV=test \
  POSTGRES_HOST=127.0.0.1 POSTGRES_PORT="$PG_PORT" POSTGRES_DB=railtech_test \
  POSTGRES_USER=railtech POSTGRES_PASSWORD="$PASS" \
  S3_ENDPOINT="http://127.0.0.1:${S3_PORT}" S3_ACCESS_KEY=railtech S3_SECRET_KEY="$PASS" \
  uv run pytest -m integration -q -p no:cacheprovider "$@" || status=$?
status="${status:-0}"
echo "Готово. Остановить контейнеры: scripts/test_int_local.sh --down"
exit $status
