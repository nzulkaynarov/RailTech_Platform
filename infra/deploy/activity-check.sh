#!/usr/bin/env bash
# Активность в Платформе за последние 30 минут (ВЫКЛ-2, DECISIONS 2026-11-27): число успешных (2xx/3xx) запросов к BFF Платформы,
# кроме проверки здоровья (/api/v1/health: healthcheck контейнера и smoke выкладки) и приёмника шины (/bus/: сервер-сервер).
# Читает только журнал контейнера platform-bff (access-лог uvicorn), ничего не пишет. Печатает одно число.
#   ssh app 'bash -s' < infra/deploy/activity-check.sh        запуск с раннера (скрипт на сервер не кладётся)
#   ... | bash infra/deploy/activity-check.sh --stdin         разобрать журнал со стандартного входа (тест)
# Нет контейнера или docker не отвечает - код 1 без числа: «неизвестно» не должно превращаться в «никого нет».
set -euo pipefail

count() {
  # INFO:     172.18.0.5:41234 - "GET /api/v1/me HTTP/1.1" 200 OK
  { grep -E ' - "(GET|HEAD|POST|PUT|PATCH|DELETE|OPTIONS) [^ ]+ HTTP/[0-9.]+" [23][0-9][0-9]' || true; } \
    | { grep -Ev ' - "[A-Z]+ (/api/v1/health|/bus/)' || true; } \
    | wc -l | tr -d ' '
}

if [ "${1:-}" = "--stdin" ]; then
  count
  exit 0
fi

cid="$(docker ps -q --filter label=com.docker.compose.service=platform-bff | head -n1)"
[ -n "$cid" ] || { echo "activity-check: контейнер platform-bff не найден" >&2; exit 1; }
docker logs --since 30m "$cid" 2>&1 | count
