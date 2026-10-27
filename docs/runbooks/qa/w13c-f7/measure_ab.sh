#!/usr/bin/env bash
# W13C-F7: один прогон A/B-замера шины на свободной машине (стенд compose-проекта rt-w13c-f7 или любой другой с STAND=<проект>).
# Нагрузка — та же, что в W13-A7 (docs/runbooks/qa/w13-a7-gate/measure_short.sh) и общие генераторы гейта 11c (docs/runbooks/qa/w11c-gate/):
# фазы control (без slow) -> x1 (обычный поток) -> burst (3 волны + 50 лидов CRM разом).
#   СЦЕНАРИЙ=A (по умолчанию): в начале x1 в файл подписок дописывается подписчик `slow` (200 через 2,5 с, заглушка slow_stub.py);
#   СЦЕНАРИЙ=B (контроль):     та же нагрузка, `slow` НЕ добавляется.
# Предусловия: стенд готов (setup, сопряжение ERP, сотрудники, клиент со сделкой ERP, gen_state), заглушка bus-slow запущена
# (в B она запущена тоже — на нагрузку она не влияет: подписчика в файле нет), каталог подписок стенда смонтирован в /opt/rt/contracts/bus.
#   STAND=rt-w13c-f7 SCENARIO=A|B SUBS_FILE=<рабочий файл подписок> SUBS_ORIG=<исходная копия subscriptions.yaml> \
#     measure_ab.sh <каталог вывода>
# Побочные файлы каталога вывода: load.txt (uptime каждые 5 с), foreign.txt (чужие контейнеры/стенды, замеченные во время прогона:
# пусто = прогон чистый), phases.txt, rows.csv, latency-table.txt, extra.txt (повторы, дубли, недоставленные, журнал slow).
set -u
D="$(cd "$(dirname "$0")" && pwd)"
GATE="$D/../w11c-gate"
SCREENS="$D/../../../screens"
WAVES="${WAVES:-3}"; BURSTS="${BURSTS:-1}"
SCENARIO="${SCENARIO:-A}"
OUT="${1:?каталог вывода}"; mkdir -p "$OUT"
export STAND="${STAND:-rt-w13c-f7}"
: "${SUBS_FILE:?}" "${SUBS_ORIG:?}"
now() { date -u '+%Y-%m-%d %H:%M:%S'; }
phase_start() { echo "$(now) --- фаза $1"; PH="$1"; PH_START="$(now)"; }
phase_end() { echo "$PH|$PH_START|$(now)|$1" >> "$OUT/phases.txt"; }
# IGNORE_IDLE — регэксп имён чужих контейнеров, заведомо простаивающих (осиротевшие, CPU ~0, без процесса-владельца); по умолчанию — никаких
foreign() { { docker ps --format '{{.Names}}' | grep -v -E "^(rt-platform-|$STAND-)" | grep -v -E "${IGNORE_IDLE:-^$}"; docker compose ls --format json | python3 -c 'import json,sys; [print("compose:"+p["Name"]) for p in json.load(sys.stdin) if p["Name"] not in ("rt-platform","'"$STAND"'")]'; } 2>/dev/null; }
: > "$OUT/phases.txt"; : > "$OUT/load.txt"; : > "$OUT/foreign.txt"
if [ -n "$(foreign)" ]; then echo "машина не свободна:"; foreign; exit 3; fi

echo "сценарий $SCENARIO, стенд $STAND, старт $(now) UTC; load average до прогона: $(uptime | sed 's/.*load averages*: //')" | tee "$OUT/run-info.txt"
docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' > "$OUT/stats-before.txt" 2>/dev/null
( while :; do echo "$(now) $(uptime | sed 's/.*load averages*: //')" >> "$OUT/load.txt"; f="$(foreign | tr '\n' ' ')"; [ -n "$f" ] && echo "$(now) $f" >> "$OUT/foreign.txt"; sleep 5; done ) &
SAMPLER=$!
disown "$SAMPLER"   # иначе безаргументный `wait` в волнах ждёт и сэмплер
trap 'kill $SAMPLER 2>/dev/null' EXIT

cp "$SUBS_ORIG" "$SUBS_FILE"; sleep 12   # исходное состояние: подписчика slow в файле нет; mtime перечитывается за <= 7..10 с
T_ALL="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
docker logs "$STAND-bus-slow-1" 2>&1 | wc -l > "$OUT/slow-log-offset.txt"
echo "T_ALL=$T_ALL" >> "$OUT/run-info.txt"

wave() {   # волна гейта 11c (25 лидов CRM + 25 публикаций ERP + 8 писем EDS) + 10 правок клиента/сотрудников CRM одновременно
  ( "$GATE/run.sh" ident_gen.py 1 10 0.0 2>&1 | tail -1 ) &
  "$GATE/wave.sh" 2>&1
  wait
}
phase_start control
wave; sleep 25; wave; sleep 25
phase_end 0

if [ "$SCENARIO" = A ]; then
  echo "$(now) + подписчик slow (строка дописана в файл подписок на месте)"
  cat >> "$SUBS_FILE" <<'YAML'

  - name: slow
    endpoint: http://bus-slow:9000/bus/v1/events
    types: [uz.railtech.erp.*.v1, uz.railtech.crm.*.v1, uz.railtech.eds.*.v1]
YAML
else
  echo "$(now) сценарий B: подписчик slow НЕ добавлен (контроль: та же нагрузка без медленного подписчика)"
fi
sleep 12

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

if [ "$SCENARIO" = A ]; then
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
else
  sleep 15
fi
T_END="$(date -u '+%Y-%m-%d %H:%M:%S')"
"$SCREENS/w11c-gate/logs/collect_latency.sh" "$T_ALL" > "$OUT/rows.csv"
python3 "$SCREENS/w13-a0-bus/logs/latency_table.py" "$OUT/rows.csv" "$OUT/phases.txt" > "$OUT/latency-table.txt"
if [ "$SCENARIO" = B ]; then   # в B критерий считается как контроль: подписи «slow=да» в таблице A0 — это признак «считать критерий»
  sed -i '' 's/slow=да/slow=нет (контроль, критерий считается)/' "$OUT/latency-table.txt"
fi
cat "$OUT/latency-table.txt"

{
  echo "# Дополнительные счётчики прогона $SCENARIO ($T_ALL .. $T_END UTC)"
  echo 'БД|подписчик|доставок|delivered|не delivered|попыток>1|dead'
  for db in crm erp eds; do
    docker exec -i "$STAND-postgres-1" sh -c "psql -U \"\$POSTGRES_USER\" -d $db -At -F '|' -c \"
      select '$db', d.subscriber, count(*), count(*) filter (where d.status='delivered'), count(*) filter (where d.status<>'delivered'),
             count(*) filter (where d.attempts>1), count(*) filter (where d.status='dead')
        from rt_bus_delivery d join rt_bus_outbox o on o.id=d.event_id where o.created_at > '$T_ALL'::timestamptz group by 1,2 order by 2\""
  done
  echo "дублей строк доставки (одно событие x подписчик более одного раза):"
  for db in crm erp eds; do
    docker exec -i "$STAND-postgres-1" sh -c "psql -U \"\$POSTGRES_USER\" -d $db -At -c \"select '$db', count(*) from (select event_id, subscriber from rt_bus_delivery group by 1,2 having count(*)>1) x\""
  done
  if [ "$SCENARIO" = A ]; then
    docker logs "$STAND-bus-slow-1" 2>&1 | tail -n +"$(( $(cat "$OUT/slow-log-offset.txt") + 1 ))" > "$OUT/.slow.jsonl"
    python3 - "$OUT/.slow.jsonl" <<'PY'
import json, sys, collections
ids = []
for l in open(sys.argv[1]):
    try: ids.append(json.loads(l)["id"])
    except Exception: pass
c = collections.Counter(ids)
print(f"заглушка slow приняла запросов: {len(ids)}, уникальных событий: {len(c)}, повторно полученных событий (дубли у подписчика): {sum(1 for v in c.values() if v > 1)}")
PY
    rm -f "$OUT/.slow.jsonl"
  fi
  echo "чужие контейнеры/стенды во время прогона: $( [ -s "$OUT/foreign.txt" ] && echo ДА-ЗАГРЯЗНЁН || echo нет )"
} > "$OUT/extra.txt"
cat "$OUT/extra.txt"
docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' > "$OUT/stats-after.txt" 2>/dev/null
echo "load average после прогона: $(uptime | sed 's/.*load averages*: //')  ($(now) UTC)" | tee -a "$OUT/run-info.txt"
