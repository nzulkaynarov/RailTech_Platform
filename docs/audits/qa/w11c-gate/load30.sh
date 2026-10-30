#!/usr/bin/env bash
# Пункт 4: новый подписчик stub3 (строка дописывается в файл подписок на месте) и сразу первая волна; затем волна каждые 90 с, 30 минут.
# SUBS_FILE=<копия subscriptions.yaml вне репозитория> ./load30.sh
D="$(cd "$(dirname "$0")" && pwd)"
now() { date -u +%H:%M:%S; }
echo "$(now) T4=$(date -u +%Y-%m-%dT%H:%M:%SZ): +stub3 и волна 1"
cat >> "$SUBS_FILE" <<'YAML'
  - name: stub3
    endpoint: http://bus-stub3:9000/bus/v1/events
    types: [uz.railtech.erp.*.v1, uz.railtech.crm.*.v1]
YAML
START=$(date +%s); n=1
while [ $(( $(date +%s) - START )) -lt 1800 ]; do
  W0=$(date +%s); echo "--- волна $n  $(now)"
  "$D/wave.sh" 2>&1
  n=$((n+1)); rest=$(( 90 - ( $(date +%s) - W0 ) )); [ $rest -gt 0 ] && sleep $rest
done
echo "КОНЕЦ серии $(now), волн: $((n-1))"
