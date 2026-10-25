#!/usr/bin/env bash
# Сброс прода на чистые базы и первый запуск (S0-8, стратегия §7; runbook — docs/runbooks/deploy.md, «Сброс прода и первый запуск»).
# РАЗРУШАЕТ данные приложений: базы crm, erp и eds, бакеты RustFS приложений, тома Redis. Прод сбрасывается один раз — данных
# и аккаунтов в нём нет (решение владельца 2026-10-23); дальше скрипт не нужен, а запуск на живых данных — потеря данных.
#
#   VPS 1, под deploy:   reset-prod.sh [тег]       тег — релиз, на который сбрасываем (по умолчанию state/current_tag)
#   VPS 2, под root:     reset-prod.sh db --drop crm,erp,eds [--dump-taken <каталог дампа на VPS 1>]
#                        только пересоздание баз (шаг 3 ниже). Барьер: без --dump-taken (его передаёт только VPS-1-часть, после дампа)
#                        нужен ввод «crm,erp,eds» с терминала; без флага и без терминала — отказ
#
# Подтверждение — ввод имени домена CRM из .env.prod (с терминала, /dev/tty); флага «без вопросов» нет.
# Порядок на VPS 1 (каждый шаг идемпотентен, повтор после сбоя безопасен):
#   0. проверки до разрушения: env, релиз, подтверждение, ключи S3 на сервис (make-env-prod.sh s3-keys), pull образов, CPU-база образов
#   1. остановка приложений проекта (кроме rustfs, caddy, litellm, clickhouse: файлы, вход и ключи моделей остаются)
#   2. предмиграционный дамп crm, erp и eds (predeploy-dump.sh) + копия в $RT_STATE/reset/dumps/: откат возможен
#   3. пересоздание баз crm, erp и eds на VPS 2 (DROP + CREATE с владельцем-ролью, pgvector в crm) — ssh root@VPS 2 или команда
#      вручную; litellm (ключи моделей) и langfuse не трогаются; затем проверка с VPS 1, что базы пусты
#   4. очистка бакетов приложений RustFS (erp-private, erp-public, erp-temp, eds-private, client-documents, tg-attachments, kb-sources) корневым
#      ключом через одноразовый s3-init (ключи сервисов чужих бакетов не видят, S0-9);
#      backups, wal и langfuse НЕ трогаются
#   5. удаление томов Redis (redis_data, redis_broker_data, redis_cache_data); s3_data, caddy_data, caddy_config НЕ трогаются
#   6. deploy.sh выбранного релиза: миграции на пустые базы, up, smoke
#   7. печать, где взять код первого запуска CRM
# WAL-архив (WAL_S3_PREFIX): кластер PostgreSQL тот же, DROP/CREATE DATABASE — обычные транзакции в том же потоке WAL, имена
# сегментов не повторяются, поэтому префикс и ключ WAL_ENC_KEY НЕ меняются; на момент до сброса (≤ 14 суток) восстановление
# остаётся возможным (docs/runbooks/backup-pitr.md). Новый префикс нужен только при новом кластере (initdb), не здесь.
#
# Прерванный сброс: состояние в $RT_STATE/reset/run (дамп снят, данные сброшены); повторный запуск в течение 24 ч продолжает
# с первого невыполненного шага. Бросить и начать заново: rm "$RT_STATE/reset/run".
# Для теста (infra/deploy/tests/reset-prod-test.sh): RT_RESET_TEST_STDIN=1 — читать ответы из stdin, а не с терминала;
# действует только при RT_STATE, отличном от боевого /opt/rt/state.
set -euo pipefail
# shellcheck source=infra/deploy/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Бакеты приложений. backups (дампы), wal (WAL-архив) и langfuse сюда не входят намеренно (тест это проверяет).
APP_BUCKETS=(erp-private erp-public erp-temp eds-private client-documents tg-attachments kb-sources)
# Тома приложений. s3_data (RustFS), caddy_data (сертификаты), caddy_config, postgres_* сюда не входят намеренно.
APP_VOLUMES=(redis_data redis_broker_data redis_cache_data)
# Сервисы, которые при сбросе остаются работать (остальное проекта останавливается).
KEEP_SERVICES=(rustfs caddy litellm clickhouse)
# Контейнеры каких сервисов вправе держать тома Redis (иначе том не трогаем).
REDIS_SERVICES=(redis redis-broker redis-cache)
RESET_DBS=(crm erp eds)
PG_IMAGE="${PG_IMAGE:-pgvector/pgvector:0.8.7-pg17}"
RT_DB_DIR="${RT_DB_DIR:-/opt/rt-db}"   # каталог на VPS 2 (db-up.sh)
RESUME_MAX_AGE_S=86400

in_list() { local x="$1"; shift; local i; for i in "$@"; do [[ "$i" == "$x" ]] && return 0; done; return 1; }

# --- ввод оператора -------------------------------------------------------------------------------------------------------
ask() { # текст приглашения -> ответ в $REPLY
  printf '%s' "$1" >&2
  if [[ "${RT_RESET_TEST_STDIN:-}" == 1 ]]; then
    [[ "${RT_STATE:-}" != /opt/rt/state ]] || die "RT_RESET_TEST_STDIN — только для теста: на боевом RT_STATE=/opt/rt/state подтверждение вводится с терминала"
    IFS= read -r REPLY || die "ввод закрыт — сброс не подтверждён"
  else
    IFS= read -r REPLY </dev/tty || die "нет терминала для подтверждения — запустите скрипт в интерактивной сессии (ssh -t)"
  fi
}

# --- режим VPS 2: пересоздание баз ---------------------------------------------------------------------------------------
run_db() {
  local drop="" dump_taken="" list=() d
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --drop) drop="${2:-}"; shift 2 ;;
      --dump-taken) dump_taken="${2:-}"; shift 2 ;;
      *) die "неизвестный аргумент: $1 (usage: reset-prod.sh db --drop crm,erp,eds)" ;;
    esac
  done
  [[ -n "$drop" ]] || die "usage: reset-prod.sh db --drop crm,erp,eds (список баз задаётся явно)"
  IFS=',' read -ra list <<<"$drop"
  for d in "${list[@]}"; do
    in_list "$d" "${RESET_DBS[@]}" || die "база '$d' не входит в сброс: разрешены только ${RESET_DBS[*]} (litellm хранит ключи моделей, langfuse не сбрасывается)"
  done
  # Барьер перед DROP: либо VPS-1-часть подтверждает, что дамп снят (--dump-taken <каталог>), либо человек вводит список баз.
  if [[ -n "$dump_taken" ]]; then
    [[ "$dump_taken" == /* ]] || die "--dump-taken: нужен абсолютный путь каталога дампа на VPS 1, получено '$dump_taken'"
    log "дамп до сброса снят на VPS 1: $dump_taken — продолжаю"
  else
    ask "ВНИМАНИЕ: будут удалены базы $drop на этом сервере, дамп из этого запуска не проверяется. Для подтверждения введите $drop: "
    [[ "$REPLY" == "$drop" ]] || die "введено '$REPLY', ожидалось '$drop' — базы не тронуты (без терминала и без --dump-taken режим db отказывает)"
  fi
  [[ "$(id -u)" -eq 0 ]] || die "режим db запускается от root на VPS 2 (sudo у deploy нет): ssh root@<VPS 2> $0 db --drop $drop"
  local infra envf
  infra="$(cd "$here/.." && pwd)"
  envf="$RT_DB_DIR/.env.db"
  [[ -f "$envf" ]] || die "нет $envf — это не VPS 2 или каталог другой (RT_DB_DIR)"
  dc() { docker compose -f "$infra/compose/db.yml" --env-file "$envf" "$@"; }
  pg() { dc exec -T -u postgres postgres psql -v ON_ERROR_STOP=1 -U postgres "$@"; }
  # Сколько таблиц в litellm — до и после: база с ключами моделей не должна измениться.
  count_tables() { pg -d "$1" -tAc "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE c.relkind IN ('r','p') AND n.nspname NOT IN ('pg_catalog','information_schema')" | tr -d '[:space:]'; }

  [[ "$(dc ps --format '{{.Health}}' postgres)" == healthy ]] || die "postgres на VPS 2 не healthy (docker compose -f $infra/compose/db.yml ps)"
  local lit_before lit_after
  lit_before="$(count_tables litellm)"
  log "litellm до сброса: таблиц $lit_before (должно остаться так же)"
  for d in "${list[@]}"; do
    # WITH (FORCE) отключает оставшиеся сеансы (резервный pg_dump, зависший клиент); приложения VPS 1 уже остановлены.
    pg -d postgres -c "DROP DATABASE IF EXISTS \"$d\" WITH (FORCE)"
    log "база $d удалена"
  done
  # Тот же идемпотентный init, что в db-up.sh: CREATE DATABASE с владельцем-ролью, REVOKE/GRANT CONNECT, pgvector в crm.
  dc exec -T -u postgres postgres bash /docker-entrypoint-initdb.d/10-prod-init.sh
  for d in "${list[@]}"; do
    [[ "$(pg -d postgres -tAc "SELECT count(*) FROM pg_database WHERE datname = '$d'" | tr -d '[:space:]')" == 1 ]] || die "база $d не создана"
  done
  if in_list crm "${list[@]}"; then
    [[ "$(pg -d crm -tAc "SELECT count(*) FROM pg_extension WHERE extname = 'vector'" | tr -d '[:space:]')" == 1 ]] || die "в crm нет расширения vector"
  fi
  lit_after="$(count_tables litellm)"
  [[ "$lit_before" == "$lit_after" ]] || die "litellm изменилась ($lit_before → $lit_after таблиц) — остановитесь и разберитесь"
  log "готово на VPS 2: пересозданы ${list[*]}; litellm цела ($lit_after таблиц); WAL-архив продолжается в том же потоке (WAL_S3_PREFIX не менялся)"
}

if [[ "${1:-}" == db ]]; then shift; run_db "$@"; exit 0; fi

# --- режим VPS 1 ----------------------------------------------------------------------------------------------------------
[[ "$(id -u)" -ne 0 ]] || die "запускайте под пользователем deploy, не под root: файлы состояния и дампов должны принадлежать deploy"
tag="${1:-}"
if [[ -z "$tag" ]]; then
  # Тег не указан: берём state/current_tag, но только если скрипт запущен из каталога именно этого релиза — иначе сброс
  # пошёл бы кодом одного релиза с образами и миграциями другого.
  tag="$(state_get current_tag)"
  [[ -n "$tag" ]] || die "нет тега: state/current_tag пуст — укажите: reset-prod.sh <тег>"
  script_rel="$(basename "$(cd "$here/../.." && pwd)")"
  [[ "$script_rel" == "$tag" ]] || die "скрипт запущен из релиза '$script_rel', а state/current_tag = '$tag': укажите тег явно (reset-prod.sh <тег>), чтобы не смешать релизы"
fi
[[ "$tag" =~ ^[A-Za-z0-9_.-]+$ ]] || die "недопустимый тег: $tag"
rel="$(release_dir "$tag")"
for f in deploy.sh predeploy-dump.sh cpu-baseline-check.sh smoke.sh make-env-prod.sh; do
  [[ -x "$rel/infra/deploy/$f" ]] || die "в релизе $rel нет исполняемого infra/deploy/$f (релиз загружен deploy.yml? хранятся пять последних)"
done
require_env_file
for v in CRM_DOMAIN ERP_DOMAIN CABINET_DOMAIN PLATFORM_DOMAIN DB_INTERNAL_IP DB_CRM_PASSWORD DB_ERP_PASSWORD DB_EDS_PASSWORD; do
  require_env_var "$v" "см. infra/.env.prod.example и docs/runbooks/deploy.md, §1.2"
done
crm_domain="$(env_get CRM_DOMAIN)"
db_host="$(env_get DB_INTERNAL_IP)"
PG_DOCKER="${PG_DOCKER:-docker}"
export RT_IMAGE_TAG="$tag"

compose_project() { # проект compose: -p/COMPOSE_PROJECT_NAME/.env.prod, иначе name: из base.yml
  local p="${COMPOSE_PROJECT_NAME:-}"
  [[ -n "$p" ]] || p="$(env_get COMPOSE_PROJECT_NAME || true)"
  echo "${p:-rt-platform}"
}
project="$(compose_project)"

# Состояние прерванного сброса.
reset_dir="$RT_STATE/reset"
run_file="$reset_dir/run"
rs_get() { [[ -f "$run_file" ]] && grep -E "^$1=" "$run_file" | tail -1 | cut -d= -f2- || true; }
rs_set() { grep -vE "^$1=" "$run_file" 2>/dev/null > "$run_file.new" || true; printf '%s=%s\n' "$1" "$2" >> "$run_file.new"; mv "$run_file.new" "$run_file"; }

mkdir -p "$RT_STATE"
lock="$RT_STATE/reset.lock"
mkdir "$lock" 2>/dev/null || die "сброс уже запущен (или оборвался без очистки): если это не так — rmdir '$lock'"
trap 'rmdir "$lock" 2>/dev/null || true' EXIT
mkdir -p "$reset_dir"
chmod 700 "$reset_dir"

project_containers() { # работающие контейнеры проекта -> строки «id сервис»
  docker ps --filter "label=com.docker.compose.project=$project" --format '{{.ID}} {{.Label "com.docker.compose.service"}}'
}

# Пусты ли crm, erp и eds (нет ни одного отношения вне системных схем). Базы нет вовсе (сброс оборвался между DROP и CREATE) —
# тоже «не готово» (код 1). Не удаётся подключиться по другой причине — остановка.
dbs_empty() {
  local pair db role var cnt err
  for pair in crm:crm_app:DB_CRM_PASSWORD erp:erp_app:DB_ERP_PASSWORD eds:eds_app:DB_EDS_PASSWORD; do
    IFS=: read -r db role var <<<"$pair"
    if ! cnt="$(PGPASSWORD="$(env_get "$var")" "$PG_DOCKER" run --rm -e PGPASSWORD -e PGSSLMODE=require "$PG_IMAGE" \
      psql -h "$db_host" -p 5432 -U "$role" -d "$db" -tAc \
      "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE c.relkind IN ('r','p','v','m','f','S') AND n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%'" 2>&1)"; then
      err="$cnt"
      if grep -q 'does not exist' <<<"$err"; then log "   базы $db нет (будет создана)"; return 1; fi
      printf '%s\n' "$err" | tail -n 3 >&2
      die "нет подключения к базе $db на VPS 2 ($db_host:5432): ufw/pg_hba/пароль роли ${role}"
    fi
    [[ "$(tr -d '[:space:]' <<<"$cnt")" == 0 ]] || return 1
  done
}
vector_present() {
  local cnt
  cnt="$(PGPASSWORD="$(env_get DB_CRM_PASSWORD)" "$PG_DOCKER" run --rm -e PGPASSWORD -e PGSSLMODE=require "$PG_IMAGE" \
    psql -h "$db_host" -p 5432 -U crm_app -d crm -tAc "SELECT count(*) FROM pg_extension WHERE extname = 'vector'")" \
    || die "нет подключения к базе crm на VPS 2"
  [[ "$(tr -d '[:space:]' <<<"$cnt")" == 1 ]] || die "в crm нет расширения vector — пересоздание баз на VPS 2 выполнено не полностью (db-up.sh или reset-prod.sh db)"
}

stopped_count=0
step_stop() {
  local id svc ids=() names=() all
  # Проект должен существовать (хотя бы rustfs или caddy, в том числе остановленные): иначе неверное имя проекта compose
  # (COMPOSE_PROJECT_NAME) — и мы «ничего не остановили», а потом удалили бы не то или не там.
  all="$(docker ps -a --filter "label=com.docker.compose.project=$project" --format '{{.ID}} {{.Label "com.docker.compose.service"}}')"
  grep -qE ' (rustfs|caddy)$' <<<"$all" || die "в проекте compose '$project' нет контейнеров rustfs и caddy — неверное имя проекта (COMPOSE_PROJECT_NAME / .env.prod) или стек не разворачивался; сброс остановлен до любых действий"
  while read -r id svc; do
    [[ -n "$id" ]] || continue
    in_list "$svc" "${KEEP_SERVICES[@]}" && continue
    ids+=("$id"); names+=("$svc")
  done < <(project_containers)
  if [[ ${#ids[@]} -gt 0 ]]; then
    log "1. остановка приложений: ${names[*]}"
    docker stop -t 30 "${ids[@]}" >/dev/null
    stopped_count=${#ids[@]}
  else
    log "1. работающих приложений нет (остаются: ${KEEP_SERVICES[*]})"
  fi
}

step_dump() {
  local saved out keep
  saved="$(rs_get dump)"
  if [[ -n "$saved" && -s "$saved/crm.dump" && -s "$saved/erp.dump" && -s "$saved/eds.dump" ]]; then
    log "2. дамп до сброса уже снят: $saved"
    return
  fi
  log "2. предмиграционный дамп crm, erp и eds (обязателен: нет читаемого дампа — сброса нет)"
  "$rel/infra/deploy/predeploy-dump.sh" "pre-reset-$tag"
  # shellcheck disable=SC2012
  out="$(ls -1dt "$RT_STATE"/predeploy/pre-reset-"$tag"-*/ | sed -n 1p)"
  out="${out%/}"
  [[ -n "$out" && -s "$out/crm.dump" && -s "$out/erp.dump" && -s "$out/eds.dump" ]] || die "дамп после predeploy-dump.sh не найден в $RT_STATE/predeploy"
  # predeploy хранит пять последних каталогов, а сброс и деплой после него снимут ещё дампы — копия живёт отдельно.
  keep="$reset_dir/dumps/$(date -u +%Y%m%dT%H%M%SZ)-$$"
  mkdir -p "$reset_dir/dumps"
  mkdir -m 700 "$keep"
  cp -a "$out/." "$keep/"
  diff -r "$out" "$keep" >/dev/null || die "копия дампа не совпала с оригиналом ($keep)"
  rs_set dump "$keep"
  log "   дамп сохранён: $keep (откат — docs/runbooks/deploy.md, «Восстановление боевой базы»)"
}

step_db() {
  if dbs_empty; then
    log "3. базы crm, erp и eds уже пустые — пересоздание на VPS 2 пропущено"
    vector_present
    return
  fi
  local remote="$RT_DB_DIR/infra/deploy/reset-prod.sh db --drop crm,erp,eds"
  # --dump-taken передаётся только отсюда и только после step_dump: режим db без него просит ввести «crm,erp,eds» с терминала.
  local remote_auto dump_dir
  dump_dir="$(rs_get dump)"
  remote_auto="$remote --dump-taken $dump_dir"
  log "3. пересоздание баз crm, erp и eds на VPS 2 (litellm и langfuse не трогаются)"
  if [[ -n "${RT_RESET_DB_SSH:-}" ]]; then
    log "   ssh $RT_RESET_DB_SSH: $remote_auto"
    ssh -o BatchMode=yes "$RT_RESET_DB_SSH" "$remote_auto" || die "пересоздание баз на VPS 2 не выполнено (ssh)"
  else
    {
      echo
      echo "   Выполните НА VPS 2 от root (у deploy sudo нет; скрипт там обновляется вместе с каталогом infra, см. runbook):"
      echo
      echo "       ssh -t root@<VPS 2>  $remote"
      echo
      echo "   (дамп до сброса уже снят: $(rs_get dump); на VPS 2 скрипт попросит ввести crm,erp,eds — без терминала он откажется.)"
      echo
      echo "   (RT_RESET_DB_SSH=root@<адрес VPS 2> — и скрипт сделает это сам, если у VPS 1 есть ключ.)"
      echo
    } >&2
    ask "   Когда команда на VPS 2 завершилась без ошибок — нажмите Enter (нет — Ctrl+C, повтор безопасен): "
  fi
  dbs_empty || die "базы crm/erp/eds на VPS 2 не пусты — пересоздание не выполнено; повторите шаг 3 и запустите скрипт снова (повтор безопасен)"
  vector_present
  log "   базы пусты, pgvector на месте"
}

step_buckets() {
  log "4. очистка бакетов RustFS: ${APP_BUCKETS[*]} (backups, wal, langfuse не трогаются)"
  compose "$rel" up -d --wait rustfs
  # Ключи сервисов (S0-9) видят только свои бакеты, поэтому чистит корневой ключ: одноразовый s3-init (образ rustfs/rc) с окружением
  # сервиса, где он есть. Корневой ключ нигде больше не используется и наружу не печатается.
  # shellcheck disable=SC2016  # переменные раскрывает sh внутри контейнера, не эта оболочка
  compose "$rel" run --rm -T --no-deps --entrypoint sh s3-init -c '
set -eu
rc alias set root "$S3_ENDPOINT" "$S3_ROOT_ACCESS_KEY" "$S3_ROOT_SECRET_KEY" >/dev/null
for bucket in "$@"; do
  if ! probe="$(rc object list "root/$bucket/" 2>&1)"; then
    case "$probe" in
      *"Bucket not found"* | *NoSuchBucket*) echo "бакета $bucket нет — пропуск (создаст s3-init)"; continue ;;
      *) echo "$bucket: не удалось прочитать бакет: $probe" >&2; exit 1 ;;
    esac
  fi
  # Несколько проходов — предел на случай, если в бакет кто-то пишет (приложения остановлены на шаге 1, но проверяем).
  pass=0
  while :; do
    pass=$((pass + 1))
    rc object remove --recursive --force "root/$bucket/" >/dev/null
    rc object remove --recursive --force --incomplete "root/$bucket/" >/dev/null
    left="$(rc object list --recursive "root/$bucket/" --json | jq ".items | length")"
    [ "$left" = 0 ] && break
    [ "$pass" -lt 5 ] || { echo "$bucket: не опустел за $pass прохода (осталось $left) — кто-то пишет в него; приложения остановлены?" >&2; exit 1; }
  done
  echo "$bucket: очищен, осталось 0"
done
' sh "${APP_BUCKETS[@]}"
}

step_volumes() {
  log "5. тома Redis: ${APP_VOLUMES[*]} (s3_data, caddy_data, caddy_config не трогаются)"
  local key vol id svc found=0
  for key in "${APP_VOLUMES[@]}"; do
    while read -r vol; do
      [[ -n "$vol" ]] || continue
      found=1
      while read -r id svc; do
        [[ -n "$id" ]] || continue
        in_list "$svc" "${REDIS_SERVICES[@]}" || die "том $vol держит контейнер сервиса '$svc' (не Redis) — том не удаляю"
        docker rm -f "$id" >/dev/null
      done < <(docker ps -a --filter "volume=$vol" --format '{{.ID}} {{.Label "com.docker.compose.service"}}')
      docker volume rm "$vol" >/dev/null
      log "   том $vol удалён"
    done < <(docker volume ls -q --filter "label=com.docker.compose.project=$project" --filter "label=com.docker.compose.volume=$key")
  done
  [[ $found -eq 1 ]] || log "   томов Redis нет (уже удалены)"
}

# --- запуск ---------------------------------------------------------------------------------------------------------------
resume=0
if [[ -f "$run_file" ]]; then
  started="$(rs_get started)"
  if [[ -n "$started" && $(( $(date +%s) - started )) -lt $RESUME_MAX_AGE_S ]]; then
    resume=1
  else
    log "найдено состояние старого сброса ($run_file) — старше 24 ч, игнорирую"
    mv "$run_file" "$run_file.stale-$(date -u +%Y%m%dT%H%M%SZ)"
  fi
fi

cat >&2 <<EOF
════════════════════════════════════════════════════════════════════════════════════════
 СБРОС ПРОДА (S0-8): релиз $tag, проект compose $project
 Будет УНИЧТОЖЕНО:
   - базы crm, erp и eds на VPS 2 (дамп снимется до удаления: ${RT_STATE}/reset/dumps/)
   - объекты бакетов RustFS: ${APP_BUCKETS[*]}
   - тома Redis: ${APP_VOLUMES[*]}
 Останется: litellm и langfuse (БД), бакеты backups/wal/langfuse, тома s3_data и caddy_*, файл $RT_ENV_FILE.
════════════════════════════════════════════════════════════════════════════════════════
EOF
if [[ $resume -eq 1 ]]; then
  log "ПРОДОЛЖЕНИЕ прерванного сброса: дамп — $(rs_get dump || true); данные сброшены — $(rs_get data_reset || true)"
fi
ask "Для подтверждения введите имя домена CRM из $RT_ENV_FILE: "
[[ "$REPLY" == "$crm_domain" ]] || die "введено '$REPLY', ожидалось имя домена CRM — сброс отменён, ничего не тронуто"
if [[ $resume -eq 0 ]]; then
  : > "$run_file"
  rs_set started "$(date +%s)"
fi

log "0. ключи S3 на сервис (S0-9): make-env-prod.sh s3-keys дописывает недостающие и генерирует случайные (значения не печатаются)"
s3_vps2_before="$(env_get S3_WAL_SECRET_KEY || true)/$(env_get S3_BACKUP_SECRET_KEY || true)"
"$rel/infra/deploy/make-env-prod.sh" s3-keys "$RT_ENV_FILE" >&2
s3_vps2_after="$(env_get S3_WAL_SECRET_KEY || true)/$(env_get S3_BACKUP_SECRET_KEY || true)"
# Напоминание про VPS 2 запоминается в состоянии сброса: повторный запуск после сбоя его не теряет (в archive уходит вместе с run).
[[ "$s3_vps2_before" == "$s3_vps2_after" ]] || rs_set s3_vps2 1
log "0. проверки до разрушения (конфигурация, pull образов, CPU-база образов)"
compose "$rel" config -q
compose "$rel" pull
"$rel/infra/deploy/cpu-baseline-check.sh" "$rel" "$tag"

if [[ -n "$(rs_get data_reset)" ]]; then
  log "данные уже сброшены ($(rs_get data_reset)) — шаги 1–5 пропущены, остаётся деплой"
else
  step_stop
  # Приложения работали (первый заход или кто-то поднял их между попытками) — дамп прежней попытки мог устареть: снимаем новый,
  # прежний каталог остаётся на диске (dump_prev).
  if [[ $stopped_count -gt 0 && -n "$(rs_get dump)" ]]; then
    log "   приложения были запущены — дамп прежней попытки не используем, снимаем новый"
    rs_set dump_prev "$(rs_get dump)"
    rs_set dump ""
  fi
  step_dump
  step_db
  step_buckets
  step_volumes
  rs_set data_reset "$(date -u +%FT%TZ)"
fi

log "6. deploy.sh $tag: миграции на пустые базы, up, smoke"
"$rel/infra/deploy/deploy.sh" "$tag" || die "deploy.sh не прошёл: данные уже сброшены. Чините причину (docker compose logs, smoke) и либо запустите reset-prod.sh снова (пропустит шаги 1–5, 24 ч), либо $rel/infra/deploy/deploy.sh $tag"

s3_vps2_notice="$(rs_get s3_vps2)"
archive="$reset_dir/done-$(date -u +%Y%m%dT%H%M%SZ)"
mv "$run_file" "$archive"
log "сброс завершён (запись: $archive; дамп до сброса: $(grep -E '^dump=' "$archive" | cut -d= -f2-))"

api_name="$(docker ps --filter "label=com.docker.compose.project=$project" --filter "label=com.docker.compose.service=crm-api" --format '{{.Names}}' | sed -n 1p)"
issued="$( { [[ -n "$api_name" ]] && docker logs "$api_name" 2>&1 | grep -c setup_code_issued; } || true)"
cat >&2 <<EOF

7. Первый запуск (код живёт 24 ч, пишется в лог CRM один раз; сам скрипт его не печатает):
     docker logs ${api_name:-<контейнер crm-api>} 2>&1 | grep setup_code_issued | tail -1     # строк в журнале: ${issued:-0}; нужна ПОСЛЕДНЯЯ (журнал контейнера хранит и прежние запуски)
   Дальше в браузере:
     https://$crm_domain/setup  →  код, e-mail и пароль первого администратора
     Платформа: Admin → Подключения  →  бот Telegram; ERP — кнопка «Подключить ERP» (адрес http://erp-backend:8000, без кода)
     затем роли пользователей. Полный порядок и проверки — docs/runbooks/deploy.md, «Сброс прода и первый запуск».
EOF
if [[ -n "$s3_vps2_notice" ]]; then
  cat >&2 <<REMIND

8. Ключи S3 для VPS 2 созданы заново (S0-9): WAL-G и бэкап ходят в RustFS своими ключами. Пока их нет на VPS 2, архив WAL и дампы в бакеты не уходят
   (WAL копится на диске VPS 2; перенести надо в первые часы). На VPS 1:  infra/deploy/make-env-prod.sh extract-s3  — напечатает 4 строки;
   на VPS 2 заменить такие же строки в /opt/rt-db/.env.db и выполнить  ssh root@<VPS 2> /opt/rt-db/infra/deploy/db-up.sh  (docs/runbooks/deploy.md, «Ключи S3 на сервис»).
REMIND
fi
