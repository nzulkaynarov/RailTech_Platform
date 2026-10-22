#!/usr/bin/env bash
# Бэкенд-тесты ERP на ОДНОРАЗОВЫХ контейнерах — как backend-test в CI B2B: Postgres 17 + Redis,
# pytest --create-db (схема строится миграциями: словари сеются ими, Rule 1). Образ — apps/erp/backend
# (тот же, что в стенде). Стенд ансамбля и его база не используются.
#
#   scripts/test_backend_local.sh [pytest-аргументы]   запустить (контейнеры поднимаются при необходимости)
#   scripts/test_backend_local.sh --openapi            экспорт backend/schema.json и среза /api/v1 для packages/contracts (FIX-40)
#   scripts/test_backend_local.sh --migration-check    makemigrations --check и migrate на чистой базе
#   scripts/test_backend_local.sh --manage <args>      произвольная manage.py-команда (например, makemigrations accounts)
#   scripts/test_backend_local.sh --down               удалить контейнеры и сеть
#   ERP_TEST_NS=<имя> scripts/test_backend_local.sh …  свой набор контейнеров (параллельные сессии/агенты)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# ERP_TEST_NS — суффикс имён: две сессии на одной машине не делят базу тестов.
NS="${ERP_TEST_NS:+-${ERP_TEST_NS}}"
NET="rt-erp-test${NS}"
PG="rt-erp-test${NS}-pg"
RD="rt-erp-test${NS}-redis"
IMAGE="${ERP_TEST_IMAGE:-rt-platform-erp-backend:test${NS}}"
PG_IMAGE="${ERP_TEST_PG_IMAGE:-pgvector/pgvector:0.8.7-pg17}"
REDIS_IMAGE="${ERP_TEST_REDIS_IMAGE:-redis:7.4.11}"
PASS=ci-only-password

down() {
  docker rm -f "$PG" "$RD" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  echo "Контейнеры $PG, $RD и сеть $NET удалены."
}
case "${1:-}" in
  -h | --help) sed -n '2,11p' "$0"; exit 0 ;;
  --down) down; exit 0 ;;
esac

command -v docker >/dev/null && docker info >/dev/null 2>&1 \
  || { echo "Docker не запущен: open -a Docker, затем повторите."; exit 1; }

docker network inspect "$NET" >/dev/null 2>&1 || docker network create "$NET" >/dev/null
if ! docker ps --format '{{.Names}}' | grep -qx "$PG"; then
  docker rm -f "$PG" >/dev/null 2>&1 || true
  docker run -d --name "$PG" --network "$NET" -e POSTGRES_DB=erp -e POSTGRES_USER=rt \
    -e POSTGRES_PASSWORD="$PASS" "$PG_IMAGE" >/dev/null
fi
if ! docker ps --format '{{.Names}}' | grep -qx "$RD"; then
  docker rm -f "$RD" >/dev/null 2>&1 || true
  docker run -d --name "$RD" --network "$NET" "$REDIS_IMAGE" >/dev/null
fi
for _ in $(seq 1 40); do
  docker exec "$PG" pg_isready -U rt -d erp >/dev/null 2>&1 && break
  sleep 1
done

# Образ runtime (prod) + код смонтирован: pytest есть в образе (requirements.in, «Testing»).
# packages/contracts смонтирован только на чтение (/packages/contracts): сторож контракта портала
# (portal/tests/test_contract_guard.py) читает erp-portal.yaml и без него падает, а не пропускается (FIX-21).
# rt_bus и контракты шины (B3, L14) приходят в образ именованными контекстами сборки — как в compose (additional_contexts).
echo "▸ сборка образа $IMAGE"
docker build -q -t "$IMAGE" \
  --build-context "rtbus=$ROOT/../../packages/rt-bus" \
  --build-context "contracts=$ROOT/../../packages/contracts" \
  "$ROOT/backend" >/dev/null

run_in() {
  # Без entrypoint (он мигрирует и делает collectstatic только для daphne/gunicorn — здесь не нужен).
  docker run --rm --network "$NET" --entrypoint "" \
    -e DATABASE_URL="postgresql://rt:${PASS}@${PG}:5432/erp?sslmode=disable" \
    -e DB_SSLMODE=disable \
    -e DJANGO_SECRET_KEY=ci-test-secret-key-not-for-production \
    -e DJANGO_DEBUG="${DJANGO_DEBUG:-True}" \
    -e REDIS_URL="redis://${RD}:6379/0" \
    -e CELERY_BROKER_URL="redis://${RD}:6379/1" \
    -e CELERY_RESULT_BACKEND="redis://${RD}:6379/1" \
    -e EMAIL_BACKEND=django.core.mail.backends.locmem.EmailBackend \
    -e LITELLM_API_KEY= \
    -v "$ROOT/backend:/app" \
    -v "$ROOT/../../packages/contracts:/packages/contracts:ro" \
    -w /app "$IMAGE" "$@"
}

case "${1:-}" in
  --openapi)
    # Файл заканчивается переводом строки (end-of-file-fixer в pre-commit), иначе выгрузка и коммит расходятся.
    run_in sh -c 'python manage.py spectacular --format openapi-json --file schema.json && echo >> schema.json'
    echo "▸ backend/schema.json обновлён"
    # erp-internal.yaml — срез /api/v1 из той же выгрузки (FIX-40); stdout → временный файл → на место.
    CONTRACT="$ROOT/../../packages/contracts/openapi/erp-internal.yaml"
    run_in python scripts/export_internal_contract.py schema.json >"$CONTRACT.tmp"
    mv "$CONTRACT.tmp" "$CONTRACT"
    echo "▸ packages/contracts/openapi/erp-internal.yaml обновлён" ;;
  --migration-check)
    run_in python manage.py makemigrations --check --dry-run
    run_in python manage.py migrate --noinput ;;
  --manage)
    shift
    run_in python manage.py "$@" ;;
  *)
    # .mo не в git — компилируем, как в CI (тест каталога проверяет реальный перевод).
    run_in sh -c 'find locale -name "*.po" -exec sh -c "msgfmt -o \"\${1%.po}.mo\" \"\$1\"" _ {} \;'
    run_in pytest --create-db -p no:cacheprovider "$@" ;;
esac
