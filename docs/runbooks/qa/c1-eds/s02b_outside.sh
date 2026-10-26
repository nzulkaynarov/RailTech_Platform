#!/usr/bin/env bash
# Пункт 2/E2: через Caddy стенда (порт HTTP_PORT) EDS недоступен ни на одном домене и ни по одному пути.
P="${1:-8092}"
echo "## Снаружи (Caddy :$P) EDS недоступен"
for host in eds.localhost crm.localhost erp.localhost platform.localhost cabinet.localhost 127.0.0.1; do
  for p in /api/v1/letters /api/v1/auth/sso/exchange /bus/v1/events /api/v1/me /api/v1/registry; do
    code=$(curl -s -m 5 -o /tmp/c1body.txt -w "%{http_code}" -H "Host: $host:$P" -X POST "http://127.0.0.1:$P$p" -d '{}' -H 'content-type: application/json')
    echo "POST host=$host path=$p -> $code  body[0:60]=$(head -c 60 /tmp/c1body.txt | tr '\n' ' ')"
  done
done
echo "## порты хоста у контейнеров EDS (пусто = не публикуются)"
docker ps --filter name=rt-c1-eds --format '{{.Names}} ports=[{{.Ports}}]'
