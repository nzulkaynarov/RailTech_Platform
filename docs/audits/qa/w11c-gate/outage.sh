#!/usr/bin/env bash
# Пункт 2 гейта 11c: простой подписчика-заглушки >= 10 мин, события до и во время, старт сразу после неудачной ранней пробы CRM
# (наихудший остаток паузы предохранителя), после старта нового трафика нет. Запуск: ./outage.sh > timeline.txt
D="$(cd "$(dirname "$0")" && pwd)"
now() { date -u +%H:%M:%S; }
pg() { docker exec -i rt-w11c-postgres-1 sh -c "psql -U \"\$POSTGRES_USER\" -d $1 -At -c \"$2\""; }
crm_events() { "$D/run.sh" crm_gen.py "$@" 2>&1 | tail -1; }
erp_events() { docker exec -i -e GEN_N="$1" -e GEN_SLEEP="${2:-0.2}" rt-w11c-erp-backend-1 python manage.py shell < "$D/erp_gen.py" 2>&1 | tail -1; }
pu() { pg "$1" "select coalesce(to_char(paused_until at time zone 'utc','HH24:MI:SS'),'-') from rt_bus_subscriber_state where subscriber='stub'"; }
waiting() { pg "$1" "select count(*) from rt_bus_delivery where subscriber='stub' and status<>'delivered'"; }
echo "$(now) до остановки: 2 лида CRM и 2 события ERP"; crm_events 2 1 0.1; erp_events 2 0.1; sleep 6
T0=$(date +%s); echo "$(now) T0: docker stop bus-stub"; docker stop rt-w11c-bus-stub-1 >/dev/null
sleep 3; echo "$(now) сразу после остановки: 3 лида CRM, 3 события ERP"; crm_events 3 1 0.1; erp_events 3 0.1
a=0; b=0
while [ $(( $(date +%s) - T0 )) -lt 600 ]; do
  sleep 20; el=$(( $(date +%s) - T0 ))
  [ $el -ge 180 ] && [ $a = 0 ] && a=1 && { echo "$(now) во время простоя (+${el} с)"; crm_events 2 1 0.1; erp_events 2 0.1; }
  [ $el -ge 420 ] && [ $b = 0 ] && b=1 && { echo "$(now) во время простоя (+${el} с)"; crm_events 2 1 0.1; erp_events 2 0.1; }
done
echo "$(now) простой >= 10 мин; жду неудачной пробы CRM"; prev=$(pu crm); while [ "$(pu crm)" = "$prev" ]; do sleep 1; done
T1=$(date +%s); echo "$(now) T1: docker start bus-stub (простой $((T1 - T0)) с); paused_until crm=$(pu crm) erp=$(pu erp); нового трафика нет"; docker start rt-w11c-bus-stub-1 >/dev/null
until [ "$(waiting crm)$(waiting erp)" = "00" ]; do sleep 2; done
echo "$(now) все ожидавшие доставлены через $(( $(date +%s) - T1 )) с после старта"
