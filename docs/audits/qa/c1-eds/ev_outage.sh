#!/usr/bin/env bash
# Состояние доставок подписчику eds у издателей CRM и ERP (и общее по подписчикам) — снимок для пункта 7.
P() { docker exec -i rt-c1-postgres-1 psql -U rt -d "$1" -P pager=off -c "$2"; }
echo "### $(date -u +%H:%M:%S) UTC"
for db in crm erp; do
  echo "-- $db: доставки по подписчикам"
  P $db "select subscriber, status, count(*), max(attempts) max_attempts from rt_bus_delivery group by 1,2 order by 1,2"
  echo "-- $db: ожидающие доставки eds (тип, попыток, следующая попытка, последняя ошибка)"
  P $db "select event_type, status, attempts, to_char(next_attempt_at,'HH24:MI:SS') next_try, left(last_error,60) err from rt_bus_delivery where subscriber='eds' and status<>'delivered' order by id"
done
