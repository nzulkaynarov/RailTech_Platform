#!/usr/bin/env bash
# Повтор замера шины W13-A0 (W11C-G-1) в гейте W13-A7 — КОРОТКИЙ прогон: WAVES волн (по умолчанию 3 вместо 8) и BURSTS всплесков CRM (1 вместо 3).
# Оригинал — docs/screens/w13-a0-bus/logs/measure.sh (на том же стенде rt-c2): быстрые подписчики (platform-bff, erp, eds, crm) при подписчике `slow`,
# отвечающем 200 через 2,5 с. Генераторы нагрузки — общие скрипты гейта 11c (docs/runbooks/qa/w11c-gate/, STAND=rt-c2).
# Предусловия: стенд поднят и подготовлен (setup, сопряжение ERP, сотрудники, клиент со сделкой ERP — см. отчёт PR), заглушка bus-slow
# (slow_stub.py) запущена, файл подписок стенда — bind-mount на /opt/rt/contracts/bus (правится НА МЕСТЕ).
#   SUBS_FILE=<копия subscriptions.yaml стенда> ./measure_short.sh <каталог вывода>
# Подписчики erp и eds получают события только от правок клиента и сотрудников CRM (crm.client.updated, identity.user.updated) —
# их даёт ident_gen.py (рядом с генераторами гейта 11c); platform-bff и crm — от остальных генераторов.
# Фазы: control (без slow) -> x1 (30 лидов CRM = 60 событий с паузами 0..6 с + ERP и EDS вразбивку) -> burst (волны по 50 публикаций).
set -u
D="$(cd "$(dirname "$0")" && pwd)"
GATE="$D/../w11c-gate"
SCREENS="$D/../../../screens"
WAVES="${WAVES:-3}"; BURSTS="${BURSTS:-1}"
OUT="${1:?каталог вывода}"; mkdir -p "$OUT"
export STAND="${STAND:-rt-c2}"
now() { date -u '+%Y-%m-%d %H:%M:%S'; }
phase_start() { echo "$(now) --- фаза $1"; PH="$1"; PH_START="$(now)"; }
phase_end() { echo "$PH|$PH_START|$(now)|$1" >> "$OUT/phases.txt"; }
: > "$OUT/phases.txt"
T_ALL="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

wave() {   # волна гейта 11c (25 лидов CRM + 25 публикаций ERP + 8 писем EDS) + 10 правок клиента/сотрудников CRM одновременно
  ( "$GATE/run.sh" ident_gen.py 1 10 0.0 2>&1 | tail -1 ) &
  "$GATE/wave.sh" 2>&1
  wait
}
phase_start control
wave; sleep 25; wave; sleep 25
phase_end 0

echo "$(now) + подписчик slow (строка дописана в файл подписок на месте)"
if [ "${SKIP_SLOW:-0}" = 1 ]; then echo "SKIP_SLOW=1: подписчик slow НЕ добавлен (контрольный прогон: та же нагрузка без медленного подписчика)"; else
cat >> "$SUBS_FILE" <<'YAML'

  - name: slow
    endpoint: http://bus-slow:9000/bus/v1/events
    types: [uz.railtech.erp.*.v1, uz.railtech.crm.*.v1, uz.railtech.eds.*.v1]
YAML
fi
sleep 12   # файл подписок перечитывается по mtime (<= 7..10 с)

phase_start x1
( docker exec -i -e GEN_N=20 -e GEN_SLEEP=3 "$STAND-erp-backend-1" python manage.py shell < "$GATE/erp_gen.py" 2>&1 | tail -1 ) &
( "$GATE/run.sh" eds_gen.py 10 3 2>&1 | tail -1 ) &
( "$GATE/run.sh" ident_gen.py 12 1 3.0 2>&1 | tail -1 ) &
"$GATE/run.sh" crm_gen.py 30 1 3.0 2>&1 | tail -1     # 30 лидов x 2 события, пауза 0..6 с
wait
sleep 8
phase_end 1

phase_start burst
for n in $(seq 1 "$WAVES"); do
  echo "--- волна $n  $(now)"
  wave
  sleep 20
done
for n in $(seq 1 "$BURSTS"); do   # 50 лидов CRM одновременно (по барьеру) = 100 событий
  echo "--- всплеск CRM $n  $(now)"
  ( "$GATE/run.sh" ident_gen.py 1 10 0.0 2>&1 | tail -1 ) &
  "$GATE/run.sh" crm_gen.py 1 50 0.0 2>&1 | tail -1
  wait
  sleep 20
done
phase_end 1

echo "$(now) жду, пока slow доберёт хвост (до 150 с)"
for _ in $(seq 1 30); do
  left=0
  for db in crm erp eds; do
    n=$(docker exec -i "$STAND-postgres-1" sh -c "psql -U \"\$POSTGRES_USER\" -d $db -At -c \"select count(*) from rt_bus_delivery where subscriber='slow' and status<>'delivered'\"")
    left=$((left + n))
  done
  [ "$left" -eq 0 ] && break
  sleep 5
done
echo "$(now) slow не доставлено: $left"
"$SCREENS/w11c-gate/logs/collect_latency.sh" "$T_ALL" > "$OUT/rows.csv"
python3 "$SCREENS/w13-a0-bus/logs/latency_table.py" "$OUT/rows.csv" "$OUT/phases.txt" | tee "$OUT/latency-table.txt"
