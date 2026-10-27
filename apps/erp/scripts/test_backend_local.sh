#!/usr/bin/env bash
# Бэкенд-тесты ERP на ОДНОРАЗОВЫХ контейнерах — как backend-test в CI B2B: Postgres 17 + Redis, схема строится миграциями
# (словари сеются ими, Rule 1). Образ — apps/erp/backend (тот же, что в стенде). Стенд ансамбля и его база не используются.
# Прогон параллельный (pytest-xdist, W14-S1): у каждого воркера своя база Postgres test_erp_gwN и свои базы Redis.
#
#   scripts/test_backend_local.sh [pytest-аргументы]   запустить (контейнеры поднимаются при необходимости)
#   scripts/test_backend_local.sh --openapi            экспорт backend/schema.json и среза /api/v1 для packages/contracts (FIX-40)
#   scripts/test_backend_local.sh --migration-check    makemigrations --check и migrate на чистой базе
#   scripts/test_backend_local.sh --manage <args>      произвольная manage.py-команда (например, makemigrations accounts)
#   scripts/test_backend_local.sh --down               удалить контейнеры и сеть
#   ERP_TEST_NS=<имя> scripts/test_backend_local.sh …  свой набор контейнеров (параллельные сессии/агенты)
#
# Параллельность. По умолчанию `-n auto --maxprocesses=$ERP_TEST_MAXPROCS` (6; замер на 10 vCPU: 4 воркера — 170 с, 6 — 141 с, 8 — 200 с). Последовательно (одна база test_erp, один
# процесс): args="-n0" или args="-p no:xdist"; сам скрипт идёт последовательно, если выбран один тест (`::`) или `-k`
# (запуск воркеров и клонирование баз дороже выбранных тестов). Свой `-n N` в args перебивает значение по умолчанию.
# База тестов. Миграции гоняются один раз на набор файлов */migrations/* (хеш — в имени шаблонной базы rt_tpl_<хеш>
# внутри контейнера Postgres этого ERP_TEST_NS): тестовые базы каждого прогона клонируются из шаблона за секунды. Новый
# контейнер Postgres или правка миграций (в том числе rt_bus) — шаблон строится заново сам; штампов на диске нет.
# Образ: `docker build` с кэшем слоёв укладывается в секунды, штамп не нужен; ERP_TEST_REBUILD=1 — пересобрать без кэша
# (после правки requirements, Dockerfile или packages/rt-bus/packages/contracts, если кэш по какой-то причине подвёл).
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
MAXPROCS="${ERP_TEST_MAXPROCS:-6}"
PASS=ci-only-password
# Параметры контейнеров: при смене подписи контейнер пересоздаётся (вместе с ним и шаблонная база — она живёт в Postgres).
# Postgres одноразовый: fsync и full_page_writes ни к чему, max_connections — под воркеры xdist (пул соединений на процесс).
PG_FLAGS=(-c fsync=off -c synchronous_commit=off -c full_page_writes=off -c max_connections=400 -c shared_buffers=256MB)
# 1024 базы Redis: воркер gwN берёт базы 3·N + 0..2 (core/settings_pytest.py), штатных 16 хватило бы на пять воркеров.
REDIS_FLAGS=(--databases 1024 --save "" --appendonly no)
PG_SIG="$PG_IMAGE ${PG_FLAGS[*]}"
RD_SIG="$REDIS_IMAGE ${REDIS_FLAGS[*]}"

down() {
  docker rm -f "$PG" "$RD" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  echo "Контейнеры $PG, $RD и сеть $NET удалены."
}
case "${1:-}" in
  -h | --help) sed -n '2,20p' "$0"; exit 0 ;;
  --down) down; exit 0 ;;
esac

command -v docker >/dev/null && docker info >/dev/null 2>&1 \
  || { echo "Docker не запущен: open -a Docker, затем повторите."; exit 1; }

# Контейнер жив и собран с этими параметрами? Иначе (нет, остановлен, подпись другая) — пересоздать.
container_ok() { # имя подпись
  docker ps --format '{{.Names}}' | grep -qx "$1" \
    && [ "$(docker inspect -f '{{index .Config.Labels "rt.erp.test.sig"}}' "$1" 2>/dev/null)" = "$2" ]
}

docker network inspect "$NET" >/dev/null 2>&1 || docker network create "$NET" >/dev/null
if ! container_ok "$PG" "$PG_SIG"; then
  docker rm -f "$PG" >/dev/null 2>&1 || true
  docker run -d --name "$PG" --network "$NET" --label "rt.erp.test.sig=$PG_SIG" -e POSTGRES_DB=erp -e POSTGRES_USER=rt \
    -e POSTGRES_PASSWORD="$PASS" "$PG_IMAGE" "${PG_FLAGS[@]}" >/dev/null
fi
if ! container_ok "$RD" "$RD_SIG"; then
  docker rm -f "$RD" >/dev/null 2>&1 || true
  docker run -d --name "$RD" --network "$NET" --label "rt.erp.test.sig=$RD_SIG" "$REDIS_IMAGE" redis-server "${REDIS_FLAGS[@]}" >/dev/null
fi
for _ in $(seq 1 60); do
  docker exec "$PG" pg_isready -U rt -d erp >/dev/null 2>&1 && break
  sleep 1
done

# Образ runtime (prod) + код смонтирован: pytest и xdist есть в образе (requirements.in, «Testing»).
# packages/contracts смонтирован только на чтение (/packages/contracts): сторож контракта портала
# (portal/tests/test_contract_guard.py) читает erp-portal.yaml и без него падает, а не пропускается (FIX-21).
# rt_bus и контракты шины (B3, L14) приходят в образ именованными контекстами сборки — как в compose (additional_contexts).
# Сборка идёт каждый раз: слои из кэша docker — доли секунды (замер: ≤ 2 с), а вход образа не ограничен requirements*
# (rtbus, contracts, Dockerfile) — штамп по ним дал бы шанс забыть пересборку и получить устаревшую шину в образе.
echo "▸ сборка образа $IMAGE"
docker build -q ${ERP_TEST_REBUILD:+--no-cache} -t "$IMAGE" \
  --build-context "rtbus=$ROOT/../../packages/rt-bus" \
  --build-context "contracts=$ROOT/../../packages/contracts" \
  "$ROOT/backend" >/dev/null

DB_URL="postgresql://rt:${PASS}@${PG}:5432"
run_in() {
  # Без entrypoint (он мигрирует и делает collectstatic только для daphne/gunicorn — здесь не нужен).
  # Переменные окружения тестов — через массив RUN_ENV (подготовлен ниже); для --migration-check/--manage он пуст.
  docker run --rm --network "$NET" --entrypoint "" \
    -e DATABASE_URL="${DB_URL}/erp?sslmode=disable" \
    -e DB_SSLMODE=disable \
    -e DJANGO_SECRET_KEY=ci-test-secret-key-not-for-production \
    -e DJANGO_DEBUG="${DJANGO_DEBUG:-True}" \
    -e REDIS_CACHE_URL="redis://${RD}:6379/0" \
    -e REDIS_CHANNELS_URL="redis://${RD}:6379/2" \
    -e CELERY_BROKER_URL="redis://${RD}:6379/1" \
    -e CELERY_RESULT_BACKEND="redis://${RD}:6379/1" \
    -e EMAIL_BACKEND=django.core.mail.backends.locmem.EmailBackend \
    -e LITELLM_API_KEY= \
    ${RUN_ENV[@]+"${RUN_ENV[@]}"} \
    -v "$ROOT/backend:/app" \
    -v "$ROOT/../../packages/contracts:/packages/contracts:ro" \
    -w /app "$IMAGE" "$@"
}
RUN_ENV=()

# Хеш входов схемы и словарей: файлы миграций приложений ERP и библиотеки шины (rt_bus едет в образ из packages/rt-bus), код
# посева, который миграции вызывают (core/seeds, core/data), и образ Postgres. Пути относительные — хеш не зависит от worktree.
migrations_hash() {
  (
    cd "$ROOT/../.."
    echo "$PG_IMAGE"
    find apps/erp/backend packages/rt-bus/rt_bus \( -path '*/migrations/*.py' -o -path 'apps/erp/backend/core/seeds/*.py' \
      -o -path 'apps/erp/backend/core/data/*' \) -not -path '*/node_modules/*' -not -path '*/__pycache__/*' \
      | LC_ALL=C sort | xargs shasum -a 256
  ) | shasum -a 256 | cut -c1-12
}

# Шаблонная база: мигрированная схема со словарями, из неё клонируются тестовые базы воркеров. Строится под именем *_build и
# переименовывается по успеху, поэтому оборванная сборка шаблоном не становится.
ensure_template() {
  local tpl="rt_tpl_$(migrations_hash)" psql=(docker exec "$PG" psql -U rt -d postgres -v ON_ERROR_STOP=1 -tAq)
  if [ -n "${ERP_TEST_REBUILD:-}" ] || [ "$("${psql[@]}" -c "SELECT 1 FROM pg_database WHERE datname='$tpl'")" != 1 ]; then
    echo "▸ шаблонная база $tpl: миграции с нуля (один раз на набор миграций)" >&2
    for old in $("${psql[@]}" -c "SELECT datname FROM pg_database WHERE datname LIKE 'rt\_tpl\_%'"); do
      "${psql[@]}" -c "DROP DATABASE \"$old\" WITH (FORCE)" >/dev/null
    done
    "${psql[@]}" -c "CREATE DATABASE \"${tpl}_build\"" >/dev/null
    # Те же расширения и функция-заглушка, что ставит django_db_setup (conftest.py); миграции остальное.
    DATABASE_URL_OVERRIDE="${DB_URL}/${tpl}_build?sslmode=disable"
    docker exec "$PG" psql -U rt -d "${tpl}_build" -v ON_ERROR_STOP=1 -qc "CREATE EXTENSION IF NOT EXISTS pg_trgm" >/dev/null
    RUN_ENV=(-e "DATABASE_URL=$DATABASE_URL_OVERRIDE")
    if ! run_in python manage.py migrate --noinput -v 0 >&2; then
      "${psql[@]}" -c "DROP DATABASE \"${tpl}_build\" WITH (FORCE)" >/dev/null
      return 1
    fi
    RUN_ENV=()
    "${psql[@]}" -c "ALTER DATABASE \"${tpl}_build\" RENAME TO \"$tpl\"" >/dev/null
  fi
  echo "$tpl"
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
    TEMPLATE="$(ensure_template)"
    RUN_ENV=(-e "ERP_TEST_DB_TEMPLATE=$TEMPLATE")
    # Параллельность по умолчанию, если в args нет своего выбора (-n, --numprocesses, --dist, -p no:xdist) и выбран не один тест.
    PAR=()
    case " $* " in
      *" -n"* | *" --numprocesses"* | *" --dist"* | *" no:xdist"* | *" --maxprocesses"* | *"::"* | *" -k"* ) ;;
      *) PAR=(-n auto --maxprocesses="$MAXPROCS") ;;
    esac
    # .mo не в git — компилируем, как в CI (тест каталога проверяет реальный перевод). База каждого прогона создаётся заново
    # (--create-db, клон шаблона): транзакционные тесты (`django_db(transaction=True)`) сбрасывают таблицы, и переиспользованная
    # база теряла бы словари, посеянные миграциями.
    run_in sh -c 'find locale -name "*.po" -exec sh -c "msgfmt -o \"\${1%.po}.mo\" \"\$1\"" _ {} \; ; exec "$@"' sh \
      pytest --create-db -p no:cacheprovider ${PAR[@]+"${PAR[@]}"} "$@" ;;
esac
