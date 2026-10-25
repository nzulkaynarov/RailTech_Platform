#!/usr/bin/env bash
# Выполнить команду с PostgreSQL для тестов EDS.
# EDS_TEST_DATABASE_URL задан (CI: service-контейнер) — команда идёт как есть.
# Не задан — одноразовый postgres:17 в Docker (tmpfs, 512 МБ), удаляется после команды при любом исходе.
# Имя контейнера — EDS_PG_CONTAINER (по умолчанию rt-eds-test-pg-<pid>); стенд ансамбля не используется.
set -euo pipefail

if [ -n "${EDS_TEST_DATABASE_URL:-}" ]; then
  exec "$@"
fi

command -v docker >/dev/null && docker info >/dev/null 2>&1 \
  || { echo "Docker не запущен — нужен для тестов EDS против PostgreSQL (или задайте EDS_TEST_DATABASE_URL)"; exit 1; }

NAME="${EDS_PG_CONTAINER:-rt-eds-test-pg-$$}"
PASSWORD="eds-test-only"
docker run -d --rm --name "$NAME" \
  -e POSTGRES_USER=rt -e POSTGRES_PASSWORD="$PASSWORD" -e POSTGRES_DB=postgres \
  -p 127.0.0.1::5432 --tmpfs /var/lib/postgresql/data --memory 512m \
  postgres:17 >/dev/null
trap 'docker rm -f "$NAME" >/dev/null 2>&1 || true' EXIT

# Готовность по TCP: во время initdb временный сервер слушает только сокет.
for _ in $(seq 1 60); do
  docker exec "$NAME" pg_isready -h 127.0.0.1 -U rt -q 2>/dev/null && break
  sleep 1
done
docker exec "$NAME" pg_isready -h 127.0.0.1 -U rt -q || { docker logs "$NAME" | tail -20; exit 1; }
PORT=$(docker port "$NAME" 5432/tcp | head -1 | sed 's/.*://')

export EDS_TEST_DATABASE_URL="postgresql://rt:${PASSWORD}@127.0.0.1:${PORT}/postgres"
"$@"
