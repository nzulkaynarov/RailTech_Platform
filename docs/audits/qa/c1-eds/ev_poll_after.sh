#!/usr/bin/env bash
# Опрос раз в 3 с после включения EDS: число недоставленных доставок eds у CRM и ERP и состояние в базе EDS. Выход — когда все доставлены.
P() { docker exec -i rt-c1-postgres-1 psql -U rt -d "$1" -At -c "$2"; }
while true; do
  c=$(P crm "select count(*) from rt_bus_delivery where subscriber='eds' and status<>'delivered'")
  e=$(P erp "select count(*) from rt_bus_delivery where subscriber='eds' and status<>'delivered'")
  i=$(P eds "select count(*) from rt_bus_inbox")
  echo "$(date -u +%H:%M:%S) недоставлено: crm=$c erp=$e | inbox EDS=$i | писем=$(P eds 'select count(*) from letters') маршрутов=$(P eds 'select count(*) from approval_routes')"
  [ "$c" = 0 ] && [ "$e" = 0 ] && break
  sleep 3
done
