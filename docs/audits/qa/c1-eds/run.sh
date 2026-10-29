#!/usr/bin/env bash
# run.sh <скрипт.py> [аргументы] — копирует скрипты гейта (и eds.yaml) в контейнер crm-api стенда rt-c1 и запускает там:
# EDS не имеет внешнего маршрута, поэтому его API вызывается изнутри сети compose. crm-api не останавливается в ходе гейта.
D="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$D/../../../.." && pwd)"
C=rt-c1-crm-api-1
docker exec "$C" mkdir -p /tmp/c1
docker cp "$D/." "$C:/tmp/c1/" >/dev/null
docker cp "$ROOT/packages/contracts/openapi/eds.yaml" "$C:/tmp/c1/eds.yaml" >/dev/null
s="$1"; shift
docker exec -e PYTHONPATH=/tmp/c1 "$C" python /tmp/c1/"$s" "$@"
