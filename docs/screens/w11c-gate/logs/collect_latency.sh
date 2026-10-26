#!/usr/bin/env bash
# collect_latency.sh <метка_времени_начала> — выгрузка пар outbox x delivery из баз crm, erp, eds стенда rt-w11c (psql в контейнере postgres).
# Пользователь БД берётся из окружения контейнера; вывод — CSV с «|» для latency_stats.py (времена UTC).
since="$1"
for db in crm erp eds; do
  docker exec -i rt-w11c-postgres-1 sh -c "psql -U \"\$POSTGRES_USER\" -d $db -At -F '|' -c \"
    select '$db', d.subscriber, o.type, to_char(o.created_at at time zone 'utc','YYYY-MM-DD HH24:MI:SS.US'), coalesce(to_char(d.delivered_at at time zone 'utc','YYYY-MM-DD HH24:MI:SS.US'),''), d.attempts
      from rt_bus_delivery d join rt_bus_outbox o on o.id = d.event_id
     where o.created_at > '$since'::timestamptz order by o.created_at\""
done
