#!/usr/bin/env bash
# Состояние КП в ERP и маршрутов в EDS (для пункта 5).
P() { docker exec -i rt-c1-postgres-1 psql -U rt -d "$1" -P pager=off -c "$2"; }
echo "## ERP: КП"; P erp "select q.id, q.version, q.number as erp_number, s.code status, q.eds_revision, q.outgoing_number as isx, q.director_decision, q.director_comment from sales_quote q join sales_quotestatus s on s.id=q.status_id order by q.id"
echo "## ERP: сделки"; P erp "select d.id, c.code stage from sales_deal d join sales_dealstage c on c.id=d.stage_id order by d.id"
echo "## ERP -> EDS: quote.ready_for_approval (создано, доставлено, КП, редакция, виз)"
P erp "select to_char(o.created_at,'HH24:MI:SS.MS') created, to_char(d.delivered_at,'HH24:MI:SS.MS') delivered, d.attempts, o.envelope->'data'->'payload'->>'number' quote, o.envelope->'data'->'payload'->>'version' ver, jsonb_array_length(o.envelope->'data'->'payload'->'visas') visas, o.envelope->'data'->'payload'->>'margin_pct' margin, o.envelope->'data'->'payload'->>'min_margin_pct' min_margin, o.envelope->'data'->'payload'->>'due' due from rt_bus_outbox o join rt_bus_delivery d on d.event_id=o.id and d.subscriber='eds' where o.type like '%quote.ready_for_approval%' order by o.created_at"
echo "## EDS: маршруты КП"; P eds "select title, status, round, outgoing_number from approval_routes where template='quote' order by created_at"
