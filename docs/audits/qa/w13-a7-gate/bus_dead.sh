#!/usr/bin/env bash
# W13-A7, пункт 4: «сломать» доставку CRM -> EDS (и ERP -> EDS) на стенде rt-c2, чтобы в Журнале интеграций появились dead-доставки,
# а затем «починить» адрес и повторить их из Платформы. Адрес приёмника EDS у издателей подменяется переменной RT_BUS_ENDPOINT_EDS
# (rt-bus.md §5: «исправить адрес, затем повторить все dead») на заглушку bus-dead (dead_stub.py: на любой POST отвечает 400 ->
# доставка сразу уходит в DLQ). Файл окружения стенда и обёртка compose — вне репозитория:
#   QA_ENV=<.env стенда> QA_DCO=<обёртка docker compose -p rt-c2 с override, где есть сервис bus-dead> ./bus_dead.sh on|off
set -euo pipefail
: "${QA_ENV:?}" "${QA_DCO:?}"
case "${1:-}" in
  on)
    "$QA_DCO" up -d --no-deps bus-dead
    sed -i '' 's|^RT_BUS_ENDPOINT_EDS=.*|RT_BUS_ENDPOINT_EDS=http://bus-dead:9000/bus/v1/events|' "$QA_ENV"
    ;;
  off)
    sed -i '' 's|^RT_BUS_ENDPOINT_EDS=.*|RT_BUS_ENDPOINT_EDS=|' "$QA_ENV"
    ;;
  *) echo "on|off"; exit 2 ;;
esac
# издатели читают адрес из окружения при старте: пересоздаём только их
"$QA_DCO" up -d --no-deps --force-recreate crm-api crm-worker erp-backend erp-worker
