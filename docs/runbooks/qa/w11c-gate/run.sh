#!/usr/bin/env bash
# run.sh <скрипт.py> [аргументы] — копирует скрипты гейта 11c и общие скрипты C1 (c1lib, s01…s11) в crm-api стенда rt-w11c и запускает там
# (EDS без внешнего маршрута; вызовы идут внутри сети compose). Состояние (пароли демо-сотрудников) — /tmp/w11c/state.json внутри контейнера.
D="$(cd "$(dirname "$0")" && pwd)"
C1="$D/../c1-eds"
ROOT="$(cd "$D/../../../.." && pwd)"
C=rt-w11c-crm-api-1
docker exec "$C" mkdir -p /tmp/w11c
docker cp "$C1/." "$C:/tmp/w11c/" >/dev/null
docker cp "$D/." "$C:/tmp/w11c/" >/dev/null
docker cp "$ROOT/packages/contracts/openapi/eds.yaml" "$C:/tmp/w11c/eds.yaml" >/dev/null
s="$1"; shift
docker exec -e PYTHONPATH=/tmp/w11c -e C1_STATE=/tmp/w11c/state.json "$C" python /tmp/w11c/"$s" "$@"
