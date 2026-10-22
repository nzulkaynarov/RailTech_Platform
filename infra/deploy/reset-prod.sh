#!/usr/bin/env bash
# Сброс прода на чистые базы и первый запуск (S0-8, стратегия §7; runbook — docs/runbooks/deploy.md, «Сброс прода и первый запуск»).
# РАЗРУШАЕТ данные приложений: базы crm и erp, бакеты RustFS приложений, тома Redis. Прод сбрасывается один раз — данных
# и аккаунтов в нём нет (решение владельца 2026-10-23); дальше скрипт не нужен, а запуск на живых данных — потеря данных.
#
#   VPS 1, под deploy:   reset-prod.sh [тег]       тег — релиз, на который сбрасываем (по умолчанию state/current_tag)
#   VPS 2, под root:     reset-prod.sh db --drop crm,erp      только пересоздание баз (запускает шаг 3 ниже)
#
# Подтверждение — ввод имени домена CRM из .env.prod (с терминала, /dev/tty); флага «без вопросов» нет.
# Порядок на VPS 1 (каждый шаг идемпотентен, повтор после сбоя безопасен):
#   0. проверки до разрушения: env, релиз, подтверждение, pull образов, CPU-база образов
#   1. остановка приложений проекта (кроме rustfs, caddy, litellm, clickhouse: файлы, вход и ключи моделей остаются)
#   2. предмиграционный дамп crm и erp (predeploy-dump.sh) + копия в $RT_STATE/reset/dumps/: откат возможен
#   3. пересоздание баз crm и erp на VPS 2 (DROP + CREATE с владельцем-ролью, pgvector в crm) — ssh root@VPS 2 или команда
#      вручную; litellm (ключи моделей) и langfuse не трогаются; затем проверка с VPS 1, что базы пусты
#   4. очистка бакетов приложений RustFS (erp-private, erp-public, erp-temp, client-documents, tg-attachments, kb-sources);
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
# Для теста (infra/deploy/tests/reset-prod-test.sh): RT_RESET_TEST_STDIN=1 — читать ответы из stdin, а не с терминала.
set -euo pipefail
# shellcheck source=infra/deploy/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Бакеты приложений. backups (дампы), wal (WAL-архив) и langfuse сюда не входят намеренно (тест это проверяет).
APP_BUCKETS=(erp-private erp-public erp-temp client-documents tg-attachments kb-sources)
# Тома приложений. s3_data (RustFS), caddy_data (сертификаты), caddy_config, postgres_* сюда не входят намеренно.
APP_VOLUMES=(redis_data redis_broker_data redis_cache_data)
# Сервисы, которые при сбросе остаются работать (остальное проекта останавливается).
KEEP_SERVICES=(rustfs caddy litellm clickhouse)
# Контейнеры каких сервисов вправе держать тома Redis (иначе том не трогаем).
REDIS_SERVICES=(redis redis-broker redis-cache)
RESET_DBS=(crm erp)
PG_IMAGE="${PG_IMAGE:-pgvector/pgvector:0.8.7-pg17}"
RT_DB_DIR="${RT_DB_DIR:-/opt/rt-db}"   # каталог на VPS 2 (db-up.sh)
RESUME_MAX_AGE_S=86400

in_list() { local x="$1"; shift; local i; for i in "$@"; do [[ "$i" == "$x" ]] && return 0; done; return 1; }

# --- ввод оператора -------------------------------------------------------------------------------------------------------
ask() { # текст приглашения -> ответ в $REPLY
  printf '%s' "$1" >&2
  if [[ "${RT_RESET_TEST_STDIN:-}" == 1 ]]; then
    IFS= read -r REPLY || die "ввод закрыт — сброс не подтверждён"
  else
    IFS= read -r REPLY </dev/tty || die "нет терминала для подтверждения — запустите скрипт в интерактивной сессии (ssh -t)"
  fi
}

# --- режим VPS 2: пересоздание баз ---------------------------------------------------------------------------------------
run_db() {
  local drop="" list=() d
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --drop) drop="${2:-}"; shift 2 ;;
      *) die "неизвестный аргумент: $1 (usage: reset-prod.sh db --drop crm,erp)" ;;
    esac
  done
  [[ -n "$drop" ]] || die "usage: reset-prod.sh db --drop crm,erp (список баз задаётся явно)"
  IFS=',' read -ra list <<<"$drop"
  for d in "${list[@]}"; do
    in_list "$d" "${RESET_DBS[@]}" || die "база '$d' не входит в сброс: разрешены только ${RESET_DBS[*]} (litellm хранит ключи моделей, langfuse не сбрасывается)"
  done
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
tag="${1:-$(state_get current_tag)}"
[[ -n "$tag" ]] || die "нет тега: state/current_tag пуст — укажите: reset-prod.sh <тег>"
[[ "$tag" =~ ^[A-Za-z0-9_.-]+$ ]] || die "недопустимый тег: $tag"
rel="$(release_dir "$tag")"
for f in deploy.sh predeploy-dump.sh cpu-baseline-check.sh smoke.sh; do
  [[ -x "$rel/infra/deploy/$f" ]] || die "в релизе $rel нет исполняемого infra/deploy/$f (релиз загружен deploy.yml? хранятся пять последних)"
done
require_env_file
for v in CRM_DOMAIN ERP_DOMAIN CABINET_DOMAIN PLATFORM_DOMAIN DB_INTERNAL_IP DB_CRM_PASSWORD DB_ERP_PASSWORD; do
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

# Пусты ли crm и erp (нет ни одного отношения вне системных схем). Не удаётся подключиться — остановка.
dbs_empty() {
  local pair db role var cnt
  for pair in crm:crm_app:DB_CRM_PASSWORD erp:erp_app:DB_ERP_PASSWORD; do
    IFS=: read -r db role var <<<"$pair"
    cnt="$(PGPASSWORD="$(env_get "$var")" "$PG_DOCKER" run --rm -e PGPASSWORD -e PGSSLMODE=require "$PG_IMAGE" \
      psql -h "$db_host" -p 5432 -U "$role" -d "$db" -tAc \
      "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE c.relkind IN ('r','p','v','m','f','S') AND n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%'")" \
      || die "нет подключения к базе $db на VPS 2 ($db_host:5432): ufw/pg_hba/пароль роли ${role}"
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

step_stop() {
  local id svc ids=() names=()
  while read -r id svc; do
    [[ -n "$id" ]] || continue
    in_list "$svc" "${KEEP_SERVICES[@]}" && continue
    ids+=("$id"); names+=("$svc")
  done < <(project_containers)
  if [[ ${#ids[@]} -gt 0 ]]; then
    log "1. остановка приложений: ${names[*]}"
    docker stop -t 30 "${ids[@]}" >/dev/null
  else
    log "1. работающих приложений нет (остаются: ${KEEP_SERVICES[*]})"
  fi
}

step_dump() {
  local saved out keep
  saved="$(rs_get dump)"
  if [[ -n "$saved" && -s "$saved/crm.dump" && -s "$saved/erp.dump" ]]; then
    log "2. дамп до сброса уже снят: $saved"
    return
  fi
  log "2. предмиграционный дамп crm и erp (обязателен: нет читаемого дампа — сброса нет)"
  "$rel/infra/deploy/predeploy-dump.sh" "pre-reset-$tag"
  # shellcheck disable=SC2012
  out="$(ls -1dt "$RT_STATE"/predeploy/pre-reset-"$tag"-*/ | sed -n 1p)"
  out="${out%/}"
  [[ -n "$out" && -s "$out/crm.dump" && -s "$out/erp.dump" ]] || die "дамп после predeploy-dump.sh не найден в $RT_STATE/predeploy"
  # predeploy хранит пять последних каталогов, а сброс и деплой после него снимут ещё дампы — копия живёт отдельно.
  keep="$reset_dir/dumps/$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir -p "$reset_dir/dumps"
  mkdir -m 700 "$keep"
  cp -a "$out/." "$keep/"
  diff -r "$out" "$keep" >/dev/null || die "копия дампа не совпала с оригиналом ($keep)"
  rs_set dump "$keep"
  log "   дамп сохранён: $keep (откат — docs/runbooks/deploy.md, «Восстановление боевой базы»)"
}

step_db() {
  if dbs_empty; then
    log "3. базы crm и erp уже пустые — пересоздание на VPS 2 пропущено"
    vector_present
    return
  fi
  local remote="$RT_DB_DIR/infra/deploy/reset-prod.sh db --drop crm,erp"
  log "3. пересоздание баз crm и erp на VPS 2 (litellm и langfuse не трогаются)"
  if [[ -n "${RT_RESET_DB_SSH:-}" ]]; then
    log "   ssh $RT_RESET_DB_SSH: $remote"
    ssh -o BatchMode=yes "$RT_RESET_DB_SSH" "$remote" || die "пересоздание баз на VPS 2 не выполнено (ssh)"
  else
    {
      echo
      echo "   Выполните НА VPS 2 от root (у deploy sudo нет; скрипт там обновляется вместе с каталогом infra, см. runbook):"
      echo
      echo "       ssh root@<VPS 2>  $remote"
      echo
      echo "   (RT_RESET_DB_SSH=root@<адрес VPS 2> — и скрипт сделает это сам, если у VPS 1 есть ключ.)"
      echo
    } >&2
    ask "   Когда команда на VPS 2 завершилась без ошибок — нажмите Enter (нет — Ctrl+C, повтор безопасен): "
  fi
  dbs_empty || die "базы crm/erp на VPS 2 не пусты — пересоздание не выполнено; повторите шаг 3 и запустите скрипт снова (повтор безопасен)"
  vector_present
  log "   базы пусты, pgvector на месте"
}

step_buckets() {
  log "4. очистка бакетов RustFS: ${APP_BUCKETS[*]} (backups, wal, langfuse не трогаются)"
  compose "$rel" up -d --wait rustfs
  # Одноразовый контейнер образа CRM (aiobotocore уже в нём); ключи и адрес S3 — из окружения сервиса, как у самого CRM.
  compose "$rel" run --rm -T --no-deps crm-migrate python - "${APP_BUCKETS[@]}" <<'PY'
import asyncio, os, sys
from aiobotocore.session import get_session
from botocore.exceptions import ClientError


async def purge(s3, bucket):
    try:
        await s3.head_bucket(Bucket=bucket)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchBucket", "NotFound"):
            print(f"бакета {bucket} нет — пропуск (создаст s3-init)", flush=True)
            return
        raise
    deleted = 0
    while True:
        keys = []
        async for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket):
            keys += [o["Key"] for o in page.get("Contents", [])]
        if not keys:
            break
        for i in range(0, len(keys), 16):
            await asyncio.gather(*(s3.delete_object(Bucket=bucket, Key=k) for k in keys[i:i + 16]))
        deleted += len(keys)
    print(f"{bucket}: удалено объектов {deleted}, осталось 0", flush=True)


async def main(buckets):
    session = get_session()
    async with session.create_client(
        "s3",
        endpoint_url=os.environ["S3_ENDPOINT"].rstrip("/"),
        aws_access_key_id=os.environ["S3_ACCESS_KEY"],
        aws_secret_access_key=os.environ["S3_SECRET_KEY"],
        region_name=os.environ.get("S3_REGION", "us-east-1"),
    ) as s3:
        for bucket in buckets:
            await purge(s3, bucket)


asyncio.run(main(sys.argv[1:]))
PY
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
   - базы crm и erp на VPS 2 (дамп снимется до удаления: ${RT_STATE}/reset/dumps/)
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

log "0. проверки до разрушения (конфигурация, pull образов, CPU-база образов)"
compose "$rel" config -q
compose "$rel" pull
"$rel/infra/deploy/cpu-baseline-check.sh" "$rel" "$tag"

if [[ -n "$(rs_get data_reset)" ]]; then
  log "данные уже сброшены ($(rs_get data_reset)) — шаги 1–5 пропущены, остаётся деплой"
else
  step_stop
  step_dump
  step_db
  step_buckets
  step_volumes
  rs_set data_reset "$(date -u +%FT%TZ)"
fi

log "6. deploy.sh $tag: миграции на пустые базы, up, smoke"
"$rel/infra/deploy/deploy.sh" "$tag" || die "deploy.sh не прошёл: данные уже сброшены. Чините причину (docker compose logs, smoke) и либо запустите reset-prod.sh снова (пропустит шаги 1–5, 24 ч), либо $rel/infra/deploy/deploy.sh $tag"

archive="$reset_dir/done-$(date -u +%Y%m%dT%H%M%SZ)"
mv "$run_file" "$archive"
log "сброс завершён (запись: $archive; дамп до сброса: $(grep -E '^dump=' "$archive" | cut -d= -f2-))"

api_name="$(docker ps --filter "label=com.docker.compose.project=$project" --filter "label=com.docker.compose.service=crm-api" --format '{{.Names}}' | sed -n 1p)"
issued="$( { [[ -n "$api_name" ]] && docker logs "$api_name" 2>&1 | grep -c setup_code_issued; } || true)"
cat >&2 <<EOF

7. Первый запуск (код живёт 24 ч, пишется в лог CRM один раз; сам скрипт его не печатает):
     docker logs ${api_name:-<контейнер crm-api>} 2>&1 | grep setup_code_issued     # строк сейчас: ${issued:-0}
   Дальше в браузере:
     https://$crm_domain/setup  →  код, e-mail и пароль первого администратора
     Платформа: Admin → Подключения  →  бот Telegram; ERP — кнопка «Подключить ERP» (адрес http://erp-backend:8000, без кода)
     затем роли пользователей. Полный порядок и проверки — docs/runbooks/deploy.md, «Сброс прода и первый запуск».
EOF
