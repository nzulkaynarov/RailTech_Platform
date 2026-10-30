#!/usr/bin/env bash
# psql.sh <база: crm|erp|eds> "<SQL>" — запрос в Postgres стенда rt-c1 (пользователь rt из .env стенда).
exec docker exec -i rt-c1-postgres-1 psql -U rt -d "$1" -P pager=off -c "$2"
