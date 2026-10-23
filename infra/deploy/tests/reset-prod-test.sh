#!/usr/bin/env bash
# Тест S0-8: infra/deploy/reset-prod.sh с подменёнными docker, ssh и id (ничего не запускается и не удаляется).
# Проверяет: отказ при неверном подтверждении (до любого действия), порядок шагов, что litellm, backups, wal, langfuse,
# тома s3_data/caddy_* и сервисы rustfs/caddy/litellm не трогаются, обязательный дамп, продолжение после сбоя деплоя,
# режим VPS 2 (только crm и erp, litellm цела).  Запуск: bash этот-файл
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
script="$here/../reset-prod.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fail() { echo "FAIL: $*"; [[ -f "${LOG:-}" ]] && { echo "--- журнал вызовов:"; cat "$LOG"; }; [[ -f "$tmp/out" ]] && { echo "--- вывод:"; cat "$tmp/out"; }; exit 1; }

domain=crm.example.org
tag=t1
mkdir -p "$tmp/bin" "$tmp/state"
rel="$tmp/releases/$tag"
mkdir -p "$rel/infra/deploy"
printf 'CRM_DOMAIN=%s\nERP_DOMAIN=erp.example.org\nCABINET_DOMAIN=cabinet.example.org\nPLATFORM_DOMAIN=platform.example.org\nDB_INTERNAL_IP=198.51.100.2\nDB_CRM_PASSWORD=x\nDB_ERP_PASSWORD=x\nRT_PROFILES=\n' "$domain" > "$tmp/env"
chmod 600 "$tmp/env"
printf 'DB_SUPERUSER_PASSWORD=x\n' > "$tmp/db.env"   # режим VPS 2 только проверяет наличие файла
mkdir -p "$tmp/rtdb"; cp "$tmp/db.env" "$tmp/rtdb/.env.db"

# --- заглушки скриптов релиза: пишут в журнал, deploy.sh может «упасть»
LOG="$tmp/log"
for s in deploy cpu-baseline-check smoke; do
  cat > "$rel/infra/deploy/$s.sh" <<EOF
#!/usr/bin/env bash
echo "$s.sh \$*" >> "$LOG"
[[ "$s" == deploy && -f "$tmp/deploy-fails" ]] && exit 1
exit 0
EOF
done
cat > "$rel/infra/deploy/make-env-prod.sh" <<EOF
#!/usr/bin/env bash
echo "make-env-prod.sh \$*" >> "$LOG"
# «генерация»: ключи сервисов wal и backup появляются, если их ещё нет (как у настоящего s3-keys)
if ! grep -q '^S3_WAL_SECRET_KEY=' "\$2"; then printf 'S3_WAL_SECRET_KEY=w1\nS3_BACKUP_SECRET_KEY=b1\n' >> "\$2"; fi
EOF
cat > "$rel/infra/deploy/predeploy-dump.sh" <<EOF
#!/usr/bin/env bash
echo "predeploy-dump.sh \$*" >> "$LOG"
[[ -f "$tmp/dump-fails" ]] && exit 1
d="$tmp/state/predeploy/\$1-\$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "\$d"; echo crm > "\$d/crm.dump"; echo erp > "\$d/erp.dump"
EOF
chmod +x "$rel"/infra/deploy/*.sh

# --- заглушка id: обычный пользователь на VPS 1, root на VPS 2
cat > "$tmp/bin/id" <<EOF
#!/usr/bin/env bash
if [[ -f "$tmp/as-root" ]]; then echo 0; else echo 1000; fi
EOF
# --- заглушка ssh: «заходит на VPS 2» — запускает режим db того же скрипта с теми же заглушками
cat > "$tmp/bin/ssh" <<EOF
#!/usr/bin/env bash
echo "ssh \$*" >> "$LOG"
[[ -f "$tmp/ssh-fails" ]] && exit 255
touch "$tmp/as-root"
# последний аргумент — команда на VPS 2; путь заменяем на проверяемый скрипт
cmd="\${*: -1}"; cmd="\${cmd#*reset-prod.sh }"
RT_DB_DIR="$tmp/rtdb" bash "$script" \$cmd
rc=\$?
rm -f "$tmp/as-root"
exit \$rc
EOF
# --- заглушка docker
cat > "$tmp/bin/docker" <<'EOF'
#!/usr/bin/env bash
args="$*"
echo "docker $args" >> "$LOG"
state() { cat "$FAKE/dbstate" 2>/dev/null || echo dirty; }
case "$1" in
  ps)
    if [[ "$args" == *"--filter volume="* ]]; then
      v="${args#*--filter volume=}"; v="${v%% *}"
      cat "$FAKE/holders-$v" 2>/dev/null || true
    elif [[ "$args" == *"service=crm-api"* ]]; then
      echo rt-test-crm-api-1
    elif [[ "$args" == *" -a "* || "$2" == -a ]]; then
      cat "$FAKE/ps_all"
    elif [[ -f "$FAKE/stopped" ]]; then
      :
    else
      cat "$FAKE/ps"
    fi ;;
  stop) touch "$FAKE/stopped" ;;
  volume)
    if [[ "$2" == ls ]]; then
      key="${args##*com.docker.compose.volume=}"; key="${key%% *}"
      grep -qx "$key" "$FAKE/volumes" && echo "rt-test_$key" || true
    fi ;;
  run)   # psql в одноразовом контейнере (проверка баз с VPS 1)
    if [[ "$args" == *pg_extension* ]]; then echo 1
    elif [[ "$args" == *pg_class* ]]; then
      case "$(state)" in
        empty) echo 0 ;;
        missing) echo 'psql: error: connection to server failed: FATAL:  database "crm" does not exist'; exit 2 ;;
        *) echo 57 ;;
      esac
    fi ;;
  logs) echo "ts setup_code_issued code=SECRET-CODE-1234" ;;
  compose)
    if [[ "$args" == *" run "* ]]; then cat >/dev/null; fi   # одноразовый контейнер (stdin не используется)
    if [[ "$args" == *" ps --format"* ]]; then echo healthy; fi
    if [[ "$args" == *" exec "* ]]; then
      if [[ "$args" == *pg_class* ]]; then echo 42; fi                                  # таблицы litellm
      if [[ "$args" == *"DROP DATABASE"* ]]; then echo empty > "$FAKE/dbstate"; fi        # «база пересоздана»
      if [[ "$args" == *"count(*) FROM pg_database"* || "$args" == *"FROM pg_extension"* ]]; then echo 1; fi
    fi ;;
esac
exit 0
EOF
chmod +x "$tmp"/bin/*
export PATH="$tmp/bin:$PATH" LOG FAKE="$tmp/fake"
export RT_ENV_FILE="$tmp/env" RT_RELEASES="$tmp/releases" RT_STATE="$tmp/state" RT_DB_DIR="$tmp/rtdb" PG_IMAGE=pg:test
export COMPOSE_PROJECT_NAME=rt-test RT_RESET_TEST_STDIN=1

reset_fake() { # состав проекта на «VPS 1» и состояние баз
  rm -rf "$FAKE" "$tmp/state" "$tmp/deploy-fails" "$tmp/dump-fails" "$tmp/ssh-fails" "$tmp/as-root"; mkdir -p "$FAKE" "$tmp/state"
  echo "$tag" > "$tmp/state/current_tag"
  : > "$LOG"
  cat > "$FAKE/ps" <<'P'
id-rustfs rustfs
id-caddy caddy
id-litellm litellm
id-crmapi crm-api
id-crmbot crm-bot
id-worker crm-worker
id-erp erp-backend
id-brk redis-broker
id-cache redis-cache
id-bff platform-bff
P
  cp "$FAKE/ps" "$FAKE/ps_all"
  printf 'redis_broker_data\nredis_cache_data\nredis_data\ns3_data\ncaddy_data\ncaddy_config\ncrm_backups\n' > "$FAKE/volumes"
  echo "id-brk redis-broker" > "$FAKE/holders-rt-test_redis_broker_data"
  echo "id-cache redis-cache" > "$FAKE/holders-rt-test_redis_cache_data"
  echo "id-oldredis redis" > "$FAKE/holders-rt-test_redis_data"
  echo dirty > "$FAKE/dbstate"
}
run_reset() { # вход: строки stdin; вывод в $tmp/out; код возврата
  RT_RESET_DB_SSH="${SSH_TARGET-}" bash "$script" ${TAG_ARG-$tag} "$@" > "$tmp/out" 2>&1
}
line_of() { grep -n -m1 -- "$1" "$LOG" | cut -d: -f1 || true; }
assert_before() { # a b: первое вхождение a раньше первого вхождения b
  local la lb; la="$(line_of "$1")"; lb="$(line_of "$2")"
  [[ -n "$la" ]] || fail "в журнале нет шага: $1"
  [[ -n "$lb" ]] || fail "в журнале нет шага: $2"
  (( la < lb )) || fail "порядок нарушен: '$1' (строка $la) должен идти раньше '$2' (строка $lb)"
}
assert_absent() { if grep -q -- "$1" "$LOG"; then fail "в журнале не должно быть: $1"; fi; }
assert_present() { grep -q -- "$1" "$LOG" || fail "в журнале должно быть: $1"; }

# ── 1. неверное подтверждение: отказ до любого действия ──────────────────────────────────────────────────────────────────
reset_fake
if echo "wrong.example.org" | run_reset; then fail "сброс прошёл при неверном подтверждении"; fi
[[ ! -s "$LOG" ]] || fail "при неверном подтверждении выполнены действия (docker/скрипты)"
grep -q 'сброс отменён' "$tmp/out" || fail "нет сообщения об отмене"
if : | run_reset; then fail "сброс прошёл при пустом вводе"; fi
[[ ! -s "$LOG" ]] || fail "при пустом вводе выполнены действия"
[[ ! -d "$tmp/state/reset.lock" ]] || fail "блокировка не снята после отказа"

# ── 2. полный сценарий через ssh: порядок и неприкосновенное ──────────────────────────────────────────────────────────
reset_fake
SSH_TARGET=root@vps2.example.org run_reset <<<"$domain" || fail "сценарий с ssh упал"
assert_before "make-env-prod.sh s3-keys" "docker compose .* pull"      # ключи S3 на сервис (S0-9) готовы до pull/config и до разрушения
assert_before "docker compose .* pull" "docker stop"
assert_before "cpu-baseline-check.sh" "docker stop"
assert_before "docker stop" "predeploy-dump.sh pre-reset-$tag"
assert_before "predeploy-dump.sh" "ssh -o BatchMode=yes root@vps2.example.org"
assert_before "ssh -o BatchMode=yes root@vps2.example.org" "DROP DATABASE"
assert_before "DROP DATABASE" "run --rm -T --no-deps --entrypoint sh s3-init -c"
assert_before "run --rm -T --no-deps --entrypoint sh s3-init -c" "docker volume rm"
assert_before "docker volume rm" "deploy.sh $tag"
# останавливаются только приложения; rustfs, caddy, litellm — нет
stop_line="$(grep -m1 '^docker stop' "$LOG")"
for id in id-crmapi id-crmbot id-worker id-erp id-brk id-cache id-bff; do [[ "$stop_line" == *"$id"* ]] || fail "не остановлен $id: $stop_line"; done
for id in id-rustfs id-caddy id-litellm; do [[ "$stop_line" != *"$id"* ]] || fail "остановлен $id, которому положено работать: $stop_line"; done
# базы: только crm и erp
grep 'DROP DATABASE' "$LOG" | grep -q '"crm"' || fail "crm не удалена"
grep 'DROP DATABASE' "$LOG" | grep -q '"erp"' || fail "erp не удалена"
if grep 'DROP DATABASE' "$LOG" | grep -Eq 'litellm|langfuse'; then fail "DROP затронул litellm или langfuse"; fi
assert_present "10-prod-init.sh"
assert_before "DROP DATABASE" "10-prod-init.sh"
# бакеты: ровно шесть приложений
purge_line="$(awk '/entrypoint sh s3-init -c/ {on=1} on {print} on && /^. sh / {exit}' "$LOG" | tr '\n' ' ')"   # вызов многострочный: до строки с аргументами бакетов
[[ "$purge_line" == *"S3_ROOT"* || "$purge_line" == *"rc alias set root"* ]] || fail "очистка бакетов не идёт корневым ключом через rc: $purge_line"
[[ "$purge_line" == *"object remove --recursive --force"* ]] || fail "очистка бакетов не удаляет объекты рекурсивно: $purge_line"
for b in erp-private erp-public erp-temp client-documents tg-attachments kb-sources; do [[ "$purge_line" == *" $b"* ]] || fail "бакет $b не очищается: $purge_line"; done
for b in backups wal langfuse; do [[ "$purge_line" != *" $b"* ]] || fail "очищается бакет $b, который трогать нельзя: $purge_line"; done
# тома: Redis снят, RustFS/Caddy/CRM-бэкапы целы
for v in redis_broker_data redis_cache_data redis_data; do assert_present "volume rm rt-test_$v"; done
for v in s3_data caddy_data caddy_config crm_backups postgres_data; do assert_absent "volume rm rt-test_$v"; done
assert_absent "docker rm -f id-rustfs"; assert_absent "docker rm -f id-caddy"; assert_absent "docker rm -f id-litellm"
assert_present "docker rm -f id-oldredis"
assert_absent "compose.* down"                       # down снял бы сети и тома проекта
assert_absent "volume prune"; assert_absent "system prune"
# ключи S3 созданы заново — напоминание про VPS 2 есть, значений ключей в выводе нет
grep -q 'extract-s3' "$tmp/out" || fail "нет напоминания перенести ключи S3 на VPS 2"
if grep -qE 'S3_(WAL|BACKUP)_SECRET_KEY=' "$tmp/out"; then fail "ключ S3 напечатан в вывод"; fi
# код первого запуска: путь указан, значение не печатается
grep -q 'grep setup_code_issued' "$tmp/out" || fail "не напечатано, где взять код первого запуска"
if grep -q 'SECRET-CODE-1234' "$tmp/out"; then fail "код первого запуска напечатан в вывод скрипта"; fi
[[ ! -f "$tmp/state/reset/run" ]] || fail "состояние сброса не закрыто после успеха"
ls "$tmp/state/reset/dumps"/*/crm.dump >/dev/null 2>&1 || fail "копия дампа до сброса не сохранена"

# ── 3. ручной режим: команда для VPS 2 печатается, скрипт ждёт Enter и проверяет базы ─────────────────────────────────
reset_fake
(
  echo "$domain"
  for _ in $(seq 1 100); do grep -q 'нажмите Enter' "$tmp/out" 2>/dev/null && break; sleep 0.1; done
  echo empty > "$FAKE/dbstate"   # оператор выполнил команду на VPS 2
  echo
) | run_reset || fail "ручной режим упал"
grep -q 'reset-prod.sh db --drop crm,erp' "$tmp/out" || fail "не напечатана команда для VPS 2"
assert_absent "^ssh "

# ── 4. оператор не выполнил шаг на VPS 2: базы не пусты — деплоя нет ─────────────────────────────────────────────────────
reset_fake
if printf '%s\n\n' "$domain" | run_reset; then fail "сценарий прошёл при непересозданных базах"; fi
assert_absent "deploy.sh $tag"
assert_absent "volume rm"; assert_absent "entrypoint sh s3-init -c"
grep -q 'не пусты' "$tmp/out" || fail "нет сообщения о непустых базах"

# ── 5. нет дампа — нет разрушения ──────────────────────────────────────────────────────────────────────────────────────
reset_fake; touch "$tmp/dump-fails"
if SSH_TARGET=root@vps2.example.org run_reset <<<"$domain"; then fail "сценарий прошёл без дампа"; fi
assert_absent "ssh "; assert_absent "DROP DATABASE"; assert_absent "volume rm"; assert_absent "entrypoint sh s3-init -c"; assert_absent "deploy.sh"

# ── 6. сбой деплоя после сброса; повтор не снимает дамп и не сбрасывает данные заново ─────────────────────────────────
reset_fake; touch "$tmp/deploy-fails"
sed -i.bak "/^S3_/d" "$tmp/env" && rm -f "$tmp/env.bak"   # ключей S3 ещё нет: s3-keys создаст их в первом запуске
if SSH_TARGET=root@vps2.example.org run_reset <<<"$domain"; then fail "сценарий прошёл при упавшем deploy.sh"; fi
[[ -f "$tmp/state/reset/run" ]] || fail "состояние сброса не сохранено после сбоя"
rm "$tmp/deploy-fails"; : > "$LOG"
SSH_TARGET=root@vps2.example.org run_reset <<<"$domain" || fail "повторный запуск после сбоя деплоя упал"
assert_absent "predeploy-dump.sh"; assert_absent "ssh "; assert_absent "DROP DATABASE"; assert_absent "volume rm"; assert_absent "docker stop"
assert_present "deploy.sh $tag"
grep -q 'extract-s3' "$tmp/out" || fail "напоминание про ключи S3 VPS 2 потерялось при повторном запуске"
[[ ! -f "$tmp/state/reset/run" ]] || fail "состояние не закрыто после успешного повтора"

# ── 7. сбой ssh на VPS 2: ничего дальше не выполняется ────────────────────────────────────────────────────────────────
reset_fake; touch "$tmp/ssh-fails"
if SSH_TARGET=root@vps2.example.org run_reset <<<"$domain"; then fail "сценарий прошёл при сбое ssh"; fi
assert_absent "entrypoint sh s3-init -c"; assert_absent "volume rm"; assert_absent "deploy.sh"
# повтор после сбоя на середине (дамп уже есть) не снимает дамп второй раз и доходит до конца
rm "$tmp/ssh-fails"; : > "$LOG"
SSH_TARGET=root@vps2.example.org run_reset <<<"$domain" || fail "повтор после сбоя ssh упал"
assert_absent "predeploy-dump.sh"; assert_present "deploy.sh $tag"

# ── 8. базы уже пусты (повтор после сброса баз): шаг 3 пропускается без ssh и без Enter ──────────────────────────────────
reset_fake; echo empty > "$FAKE/dbstate"
run_reset <<<"$domain" || fail "при пустых базах сценарий упал"
assert_absent "ssh "; assert_absent "DROP DATABASE"; assert_present "volume rm"; assert_present "deploy.sh $tag"

# ── 9. режим VPS 2: только crm и erp, litellm и langfuse отклоняются, нужен root ───────────────────────────────────────
reset_fake; touch "$tmp/as-root"
for bad in "crm,litellm" "litellm" "langfuse" "crm,erp,langfuse" "postgres"; do
  : > "$LOG"
  if bash "$script" db --drop "$bad" >"$tmp/out" 2>&1; then fail "режим db принял --drop $bad"; fi
  assert_absent "DROP DATABASE"
done
: > "$LOG"; if bash "$script" db >"$tmp/out" 2>&1; then fail "режим db без --drop выполнился"; fi; assert_absent "DROP DATABASE"
rm "$tmp/as-root"; : > "$LOG"
if bash "$script" db --drop crm,erp --dump-taken /var/state/dump-1 >"$tmp/out" 2>&1; then fail "режим db выполнился не от root"; fi
assert_absent "DROP DATABASE"
touch "$tmp/as-root"; : > "$LOG"
bash "$script" db --drop crm,erp --dump-taken /var/state/dump-1 >"$tmp/out" 2>&1 || fail "режим db упал на допустимом списке"
assert_present 'DROP DATABASE IF EXISTS "crm"'; assert_present 'DROP DATABASE IF EXISTS "erp"'
assert_before 'DROP DATABASE IF EXISTS "erp"' "10-prod-init.sh"
grep -q 'litellm цела' "$tmp/out" || fail "режим db не подтвердил сохранность litellm"

# ── 9b. барьер режима db: без дампа от VPS 1 и без подтверждения человека — отказ ─────────────────────────────────────────
reset_fake; touch "$tmp/as-root"
check_refused() { # описание, команда...: режим db обязан отказать и не выполнить DROP
  local what="$1"; shift
  : > "$LOG"
  if "$@" >"$tmp/out" 2>&1 </dev/null; then fail "режим db выполнился: $what"; fi
  assert_absent "DROP DATABASE"
}
check_refused "без флага и без ввода (ssh без терминала)" bash -c "bash '$script' db --drop crm,erp </dev/null"
check_refused "неверный ввод" bash -c "echo crm | bash '$script' db --drop crm,erp"
check_refused "ввод только одной базы" bash -c "echo erp | bash '$script' db --drop crm,erp"
check_refused "пустой --dump-taken" bash "$script" db --drop crm,erp --dump-taken ""
check_refused "относительный --dump-taken" bash "$script" db --drop crm,erp --dump-taken dump-1
check_refused "флаг-тестовый переключатель на боевом RT_STATE" env RT_STATE=/opt/rt/state bash -c "echo crm,erp | bash '$script' db --drop crm,erp"
: > "$LOG"; echo "crm,erp" | bash "$script" db --drop crm,erp >"$tmp/out" 2>&1 || fail "режим db отказал при верном вводе crm,erp"
assert_present 'DROP DATABASE IF EXISTS "crm"'
# VPS-1-часть передаёт --dump-taken ssh-ом только после дампа
reset_fake
SSH_TARGET=root@vps2.example.org run_reset <<<"$domain" || fail "сценарий с ssh упал"
assert_before "predeploy-dump.sh" "ssh -o BatchMode=yes root@vps2.example.org .*--dump-taken /"

# ── 9a. сброс оборвался между DROP и CREATE: базы нет вовсе — это не «нет подключения», шаг 3 выполняется ───────────────
reset_fake; echo missing > "$FAKE/dbstate"
SSH_TARGET=root@vps2.example.org run_reset <<<"$domain" || fail "повтор при отсутствующих базах упал"
assert_present "ssh -o BatchMode=yes"; assert_present "DROP DATABASE"; assert_present "deploy.sh $tag"

# ── 9c. тег по умолчанию: скрипт запущен не из каталога релиза current_tag — отказ; явный тег — работает ──────────────────────
reset_fake
: > "$LOG"
if TAG_ARG= RT_RESET_DB_SSH= bash "$script" > "$tmp/out" 2>&1 <<<"$domain"; then fail "тег по умолчанию принят при чужом каталоге релиза"; fi
[[ ! -s "$LOG" ]] || fail "при несовпадении релиза выполнены действия"
grep -q 'укажите тег явно' "$tmp/out" || fail "нет подсказки про явный тег"

# ── 9d. приложения снова запущены после прерванной попытки: дамп снимается заново ─────────────────────────────────────────
reset_fake; touch "$tmp/ssh-fails"
if SSH_TARGET=root@vps2.example.org run_reset <<<"$domain"; then fail "сценарий прошёл при сбое ssh"; fi
rm "$tmp/ssh-fails" "$FAKE/stopped"; : > "$LOG"      # кто-то поднял приложения
SSH_TARGET=root@vps2.example.org run_reset <<<"$domain" || fail "повтор при поднятых приложениях упал"
assert_present "predeploy-dump.sh"; grep -q '^dump_prev=' "$tmp/state/reset/done-"* || fail "прежний дамп не записан как dump_prev"

# ── 9e. неверное имя проекта compose: нет rustfs/caddy — отказ до остановки ──────────────────────────────────────────────
reset_fake; : > "$FAKE/ps_all"; : > "$FAKE/ps"
if run_reset <<<"$domain"; then fail "сценарий прошёл при проекте без контейнеров"; fi
assert_absent "docker stop"; assert_absent "predeploy-dump.sh"; assert_absent "volume rm"
grep -q 'неверное имя проекта' "$tmp/out" || fail "нет подсказки про имя проекта"

# ── 10. запуск от root на VPS 1 запрещён ───────────────────────────────────────────────────────────────────────────────
reset_fake; touch "$tmp/as-root"
if echo "$domain" | run_reset; then fail "VPS 1 режим выполнился от root"; fi
[[ ! -s "$LOG" ]] || fail "от root выполнены действия"

echo "reset-prod-test: ok"
