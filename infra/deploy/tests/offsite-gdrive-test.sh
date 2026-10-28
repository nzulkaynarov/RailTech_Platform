#!/usr/bin/env bash
# Тест OPS-GDRIVE: внешняя копия архива WAL-G на Google Drive (infra/offsite/gdrive-sync.sh, сервис offsite-backup). Секретов и
# доступа к Google не требует: Drive и RustFS подменены локальными каталогами (бэкенд local того же закреплённого образа rclone).
#  1. Конфигурация: сервис только в проде, образ rclone закреплён версией и digest, ключ S3 свой (S3_OFFSITE_*) и только у
#     offsite-backup и s3-init; каталог секретов — только чтение; лимит памяти; CRM не получает ключ; ensure-secrets создаёт
#     S3_OFFSITE_*; deploy.sh создаёт каталог секретов до up и тянет образ; политики init.sh: offsite читает wal (без записи и
#     удаления), пишет только offsite; CRM читает offsite.
#  2. Поведение (docker run образа rclone): нет ключа / битый ключ / нет ID папки — not_configured без падения; окно 14 суток —
#     копируются копия, покрывающая границу, более новые копии и WAL с её начала, история веток; старое на «Drive» удаляется;
#     пустой архив — сбой source_empty без удалений; выборка больше квоты — сбой quota без выгрузки; ID папки не попадает в
#     status.json; расписание (due) и healthcheck.
# Запуск: bash этот-файл
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
tmp="$(mktemp -d)"; trap 'docker run --rm -v "$tmp:/t" alpine:3.22 rm -rf /t/w >/dev/null 2>&1 || true; rm -rf "$tmp"' EXIT
fail() { echo "FAIL: $*"; exit 1; }
base="$root/infra/compose/base.yml"; prod="$root/infra/compose/prod.yml"; dev="$root/infra/compose/dev.yml"
init="$root/infra/s3/init.sh"; deploy="$root/infra/deploy/deploy.sh"; script="$root/infra/offsite/gdrive-sync.sh"

# --- 1. Конфигурация ------------------------------------------------------------------------------------------------------
mkenv() { # mkenv <пример> <выход>
  sed 's/CHANGE_ME/ci-only-value/' "$1" | grep -vE '^S3_OFFSITE_(ACCESS|SECRET)_KEY=' > "$2"
  printf 'S3_OFFSITE_ACCESS_KEY=ak-OFFSITE\nS3_OFFSITE_SECRET_KEY=sk-OFFSITE\n' >> "$2"
}
mkenv "$root/infra/.env.prod.example" "$tmp/env.prod"
grep -v '^#' "$root/.env.example" | grep -v '^$' > "$tmp/env.dev.raw"; mkenv "$tmp/env.dev.raw" "$tmp/env.dev"
export RT_IMAGE_TAG=offsite-gdrive-test
profiles=(--profile observability --profile kb-ingest --profile mcp)
docker compose -f "$base" -f "$prod" --env-file "$tmp/env.prod" "${profiles[@]}" config --format json > "$tmp/prod.json"
docker compose -f "$base" -f "$dev" --env-file "$tmp/env.dev" "${profiles[@]}" config --format json > "$tmp/dev.json"
j="$tmp/prod.json"
svc() { jq -r --arg k "$1" '.services["offsite-backup"] | getpath($k | split(".")) // "none" | if type == "string" then . else tojson end' "$j"; }
[[ "$(jq -r '.services["offsite-backup"] // "none"' "$tmp/dev.json")" == none ]] || fail "dev: offsite-backup не нужен на стенде (архива WAL нет)"
image="$(svc image)"
[[ "$image" =~ ^rclone/rclone:[0-9]+\.[0-9]+\.[0-9]+@sha256:[0-9a-f]{64}$ ]] || fail "образ offsite-backup не rclone/rclone:<версия>@sha256:<digest>: $image"
[[ "$(jq -r '.services["offsite-backup"].entrypoint | join(" ")' "$j")" == "sh /offsite/gdrive-sync.sh" ]] || fail "entrypoint offsite-backup"
[[ "$(svc environment.OFFSITE_S3_ACCESS_KEY)" == ak-OFFSITE && "$(svc environment.OFFSITE_S3_SECRET_KEY)" == sk-OFFSITE ]] || fail "offsite-backup не на ключе S3_OFFSITE_*"
[[ "$(svc environment.OFFSITE_WAL_BUCKET)" == wal && "$(svc environment.OFFSITE_STATUS_BUCKET)" == offsite ]] || fail "бакеты offsite-backup"
[[ "$(svc environment.OFFSITE_KEEP_DAYS)" == 14 && "$(svc environment.OFFSITE_BWLIMIT)" == 2M ]] || fail "окно 14 суток и полоса 2M по умолчанию"
[[ "$(svc environment.OFFSITE_GDRIVE_FOLDER_ID)" == "" ]] || fail "ID папки в примере должен быть пуст"
[[ "$(svc environment.OFFSITE_GDRIVE_SA_FILE)" == /secrets/gdrive-sa.json ]] || fail "путь ключа в контейнере"
[[ "$(svc deploy.resources.limits.memory)" =~ ^[0-9]+$ ]] || fail "у offsite-backup нет лимита памяти"
[[ "$(svc restart)" == unless-stopped ]] || fail "offsite-backup: restart unless-stopped"
[[ "$(jq -r '[.services["offsite-backup"].volumes[] | select(.target == "/secrets" and .read_only == true and .source == "/opt/rt/secrets")] | length' "$j")" == 1 ]] \
  || fail "каталог секретов /opt/rt/secrets должен монтироваться только на чтение"
[[ "$(jq -r '[.services["offsite-backup"].volumes[] | select(.target == "/offsite/gdrive-sync.sh" and .read_only == true)] | length' "$j")" == 1 ]] || fail "скрипт не смонтирован только на чтение"
[[ "$(jq -r '[.services["offsite-backup"].volumes[] | select(.target == "/state" and .type == "volume")] | length' "$j")" == 1 ]] || fail "нет тома состояния /state"
[[ "$(svc depends_on.s3-init.condition)" == service_completed_successfully ]] || fail "offsite-backup не ждёт s3-init (политики)"
[[ "$(jq -r '.services["offsite-backup"].healthcheck.test | join(" ")' "$j")" == "CMD sh /offsite/gdrive-sync.sh --health" ]] || fail "healthcheck offsite-backup"
holders="$(jq -r '[.services | to_entries[] | select(.value.environment // {} | tostring | test("ak-OFFSITE|sk-OFFSITE")) | .key] | sort | join(",")' "$j")"
[[ "$holders" == offsite-backup,s3-init ]] || fail "ключ offsite у лишних сервисов: $holders"
[[ "$(jq -r '.services["offsite-backup"].environment | tostring | test("S3_WAL|WAL_S3_(ACCESS|SECRET)|WAL_ENC_KEY|S3_ROOT")' "$j")" == false ]] \
  || fail "offsite-backup не должен знать ключи WAL-G, ключ шифрования архива и корневой ключ"
for f in prod dev; do
  buckets="$(jq -r '.services["s3-init"].environment.S3_BUCKETS' "$tmp/$f.json")"
  [[ " $buckets " == *" offsite "* ]] || fail "$f: s3-init не создаёт бакет offsite"
done
grep -qE '^    offsite\) echo "offsite" ;;$' "$init" || fail "init.sh: offsite пишет только в бакет offsite"
grep -qE '^    offsite\) echo "wal" ;;$' "$init" || fail "init.sh: offsite читает бакет wal (только чтение)"
grep -qE '^    crm\) echo "backups offsite" ;;$' "$init" || fail "init.sh: CRM читает backups и offsite"
grep -qE '^SERVICES=".* offsite"$' "$init" || fail "init.sh: сервиса offsite нет в SERVICES"
fn="$(sed -n '/^policy_json() {/,/^}/p' "$init")"
pol="$(bash -c "$fn; policy_json 'offsite' 'wal'")"
[[ "$(jq -r '[.Statement[] | select(.Resource | tostring | test("wal")) | .Action[]] | sort | unique | join(",")' <<<"$pol")" == s3:GetBucketLocation,s3:GetObject,s3:ListBucket ]] \
  || fail "политика offsite: на бакет wal только список и чтение"
for f in "$root/.env.example" "$root/infra/.env.prod.example"; do
  grep -q '^S3_OFFSITE_ACCESS_KEY=CHANGE_ME$' "$f" && grep -q '^S3_OFFSITE_SECRET_KEY=CHANGE_ME$' "$f" || fail "$f: нет S3_OFFSITE_*=CHANGE_ME"
done
! grep -qE '^OFFSITE_GDRIVE_FOLDER_ID=.+' "$root/infra/.env.prod.example" || fail "в примере не должно быть ID папки"
envf="$tmp/ens.env"; printf 'A=1\nS3_OFFSITE_ACCESS_KEY=CHANGE_ME\n' > "$envf"; chmod 600 "$envf"
bash "$root/infra/deploy/make-env-prod.sh" ensure-secrets "$envf" >/dev/null
grep -qE '^S3_OFFSITE_ACCESS_KEY=[0-9a-f]{48}$' "$envf" && grep -qE '^S3_OFFSITE_SECRET_KEY=[0-9a-f]{48}$' "$envf" || fail "ensure-secrets: ключ offsite не создан"
first="$(grep '^S3_OFFSITE_' "$envf")"; bash "$root/infra/deploy/make-env-prod.sh" ensure-secrets "$envf" >/dev/null
[[ "$(grep '^S3_OFFSITE_' "$envf")" == "$first" ]] || fail "ensure-secrets: заданный ключ offsite изменился"
sec="$(grep -nE '^install -d -m 700 "\$RT_SECRETS_DIR"' "$deploy" | head -1 | cut -d: -f1)"
up="$(grep -nE '^up_stack "\$rel"$' "$deploy" | head -1 | cut -d: -f1)"
[[ -n "$sec" && -n "$up" && "$sec" -lt "$up" ]] || fail "deploy.sh: каталог секретов (chmod 700) должен создаваться до up"
grep -qE '^retry "pull образов" .* offsite-backup' "$deploy" || fail "deploy.sh: образ offsite-backup не входит в pull с повторами"
bash -n "$root/infra/deploy/offsite-check.sh" || fail "offsite-check.sh: синтаксис"

# --- 2. Поведение -----------------------------------------------------------------------------------------------------------
w="$tmp/w"; mkdir -p "$w"
FOLDER_ID=TESTFOLDERID1234567890
run() { # run <аргументы gdrive-sync.sh> — переменные OFFSITE_* из массива extra
  docker run --rm -v "$w:/t" -v "$script:/offsite/gdrive-sync.sh:ro" -e TZ=UTC -e OFFSITE_RETRIES=1 -e OFFSITE_RETRIES_SLEEP=1s \
    -e OFFSITE_STATE_DIR=/t/state -e OFFSITE_SRC=/t/src/pg17 -e OFFSITE_DST=/t/drive/pg17 -e OFFSITE_STATUS_DST=/t/status/status.json \
    -e OFFSITE_GDRIVE_SA_FILE=/t/secrets/gdrive-sa.json -e OFFSITE_SA_HOST_PATH=/opt/rt/secrets/gdrive-sa.json \
    "${extra[@]}" --entrypoint sh "$image" /offsite/gdrive-sync.sh "$@"
}
status() { cat "$w/status/status.json"; }
field() { jq -r ".$1" "$w/status/status.json"; }
in_box() { docker run --rm -v "$w:/t" --entrypoint sh "$image" -c "$1"; }

# Архив: три базовые копии — 20 суток (старше границы), 15 суток (покрывает границу 14 суток), 1 сутки; WAL каждой; история ветки.
in_box '
set -e
mk() { mkdir -p "$(dirname "$1")"; printf "%s" "$3" > "$1"; touch -d "$2" "$1"; }
d() { date -u -d "@$(( $(date -u +%s) - $1 * 86400 ))" "+%Y-%m-%d %H:%M:%S"; }
s=/t/src/pg17; rm -rf /t/src /t/drive /t/status /t/state /t/secrets; mkdir -p /t/status /t/secrets
for age_hex in "20 02" "15 04" "1 06"; do
  set -- $age_hex; hex=0000000100000000000000$2; nxt=0000000100000000000000$(printf %02X $((0x$2 + 1)))
  mk $s/basebackups_005/base_$hex/tar_partitions/part_1.tar.zst "$(d $1)" "data-$hex"
  mk $s/basebackups_005/base_$hex/metadata.json "$(d $1)" "{}"
  mk $s/basebackups_005/base_${hex}_backup_stop_sentinel.json "$(d $1)" "{\"x\":1}"
  mk $s/wal_005/$hex.zst "$(d $1)" "wal-$hex"; mk $s/wal_005/$nxt.zst "$(d $1)" "wal-$nxt"
done
mk $s/wal_005/00000002.history.zst "$(d 20)" "history"
'
extra=(-e OFFSITE_KEEP_DAYS=14)

# 2.1 Не настроено: нет ключа — итог not_configured, код 3 у --now, демон бы не упал; ID папки в журнале и статусе нет.
rc=0; run --now > "$tmp/out" 2>&1 || rc=$?
[[ "$rc" == 3 ]] || { cat "$tmp/out"; fail "нет ключа: ожидался код 3 (не настроено), получен $rc"; }
[[ "$(field result)" == not_configured && "$(field reason)" == no_key ]] || { status; fail "нет ключа: not_configured/no_key"; }
[[ "$(field message)" == *"/opt/rt/secrets/gdrive-sa.json"* ]] || fail "сообщение не называет путь ключа на сервере"
[[ ! -d "$w/drive" ]] || fail "без ключа на Drive ничего не должно появиться"
printf '{"type": "authorized_user"}' > "$w/secrets/gdrive-sa.json"
rc=0; run --now > "$tmp/out" 2>&1 || rc=$?
[[ "$rc" == 3 && "$(field reason)" == bad_key ]] || { status; fail "ключ не сервисного аккаунта: not_configured/bad_key"; }
printf '{"type": "service_account", "client_email": "x@example.iam.gserviceaccount.com", "private_key": "-----BEGIN PRIVATE KEY-----\\nfake\\n-----END PRIVATE KEY-----\\n"}' > "$w/secrets/gdrive-sa.json"
rc=0; run --now > "$tmp/out" 2>&1 || rc=$?
[[ "$rc" == 3 && "$(field reason)" == no_folder ]] || { status; fail "нет ID папки: not_configured/no_folder"; }

# 2.2 Первая копия: окно 14 суток.
extra=(-e OFFSITE_KEEP_DAYS=14 -e "OFFSITE_GDRIVE_FOLDER_ID=$FOLDER_ID")
run --now > "$tmp/out" 2>&1 || { cat "$tmp/out"; fail "первая копия не прошла"; }
[[ "$(field result)" == ok && "$(field reason)" == "" ]] || { status; fail "первая копия: итог не ok"; }
got="$(cd "$w/drive/pg17" && find . -type f | sed 's|^\./||' | sort | tr '\n' ' ')"
want="basebackups_005/base_000000010000000000000004/metadata.json basebackups_005/base_000000010000000000000004/tar_partitions/part_1.tar.zst basebackups_005/base_000000010000000000000004_backup_stop_sentinel.json basebackups_005/base_000000010000000000000006/metadata.json basebackups_005/base_000000010000000000000006/tar_partitions/part_1.tar.zst basebackups_005/base_000000010000000000000006_backup_stop_sentinel.json wal_005/000000010000000000000004.zst wal_005/000000010000000000000005.zst wal_005/000000010000000000000006.zst wal_005/000000010000000000000007.zst wal_005/00000002.history.zst "
[[ "$got" == "$want" ]] || fail "состав копии на Drive:
  есть:  $got
  ждали: $want"
[[ "$(field base_backups)" == 2 && "$(field objects)" == 11 ]] || { status; fail "сводка: 2 базовые копии и 11 объектов"; }
[[ "$(field bytes)" -gt 0 && "$(field quota_bytes)" == 107374182400 && "$(field keep_days)" == 14 && "$(field prefix)" == pg17 ]] || { status; fail "сводка: байты, квота, окно, каталог"; }
[[ "$(field last_success_at)" =~ ^20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9:]{8}Z$ && "$(field oldest_base_at)" =~ Z$ ]] || { status; fail "время успеха и самой ранней копии"; }
cmp -s "$w/src/pg17/wal_005/000000010000000000000005.zst" "$w/drive/pg17/wal_005/000000010000000000000005.zst" || fail "содержимое сегмента на Drive отличается"

# 2.3 Срок хранения на Drive: прошлые прогоны оставили старую копию и её WAL — удаляются; повтор ничего не копирует заново.
in_box 'cp -a /t/src/pg17/basebackups_005/base_000000010000000000000002* /t/drive/pg17/basebackups_005/
cp -a /t/src/pg17/wal_005/000000010000000000000002.zst /t/src/pg17/wal_005/000000010000000000000003.zst /t/drive/pg17/wal_005/'
run --now > "$tmp/out" 2>&1 || { cat "$tmp/out"; fail "повторная копия не прошла"; }
[[ ! -e "$w/drive/pg17/basebackups_005/base_000000010000000000000002_backup_stop_sentinel.json" && ! -e "$w/drive/pg17/wal_005/000000010000000000000002.zst" ]] \
  || fail "старая копия и её WAL на Drive не удалены сроком хранения"
[[ ! -d "$w/drive/pg17/basebackups_005/base_000000010000000000000002" ]] || fail "пустой каталог старой копии остался"
[[ -e "$w/drive/pg17/wal_005/00000002.history.zst" ]] || fail "история ветки удалена"
grep -q '"offsite_retention_done"' "$tmp/out" || fail "в журнале нет offsite_retention_done"

# 2.4 Архив в RustFS пропал (пустой каталог): сбой source_empty, копия на Drive не тронута.
in_box 'mv /t/src /t/src.bak && mkdir -p /t/src/pg17'
before="$(cd "$w/drive" && find . -type f | sort | tr '\n' ' ')"
rc=0; run --now > "$tmp/out" 2>&1 || rc=$?
[[ "$rc" == 1 && "$(field result)" == fail && "$(field reason)" == source_empty ]] || { status; fail "пустой архив: fail/source_empty"; }
[[ "$(cd "$w/drive" && find . -type f | sort | tr '\n' ' ')" == "$before" ]] || fail "пустой архив стёр копию на Drive"
[[ "$(field last_success_at)" != null && "$(field base_backups)" == 2 ]] || { status; fail "при сбое должны остаться время последнего успеха и сводка"; }
in_box 'rm -rf /t/src && mv /t/src.bak /t/src'

# 2.5 Квота: выборка больше предела — сбой quota, на Drive ничего нового.
in_box 'rm -rf /t/drive'
extra=(-e OFFSITE_KEEP_DAYS=14 -e "OFFSITE_GDRIVE_FOLDER_ID=$FOLDER_ID" -e OFFSITE_MAX_GB=0)
rc=0; run --now > "$tmp/out" 2>&1 || rc=$?
[[ "$rc" == 1 && "$(field reason)" == quota ]] || { status; fail "квота: fail/quota"; }
[[ ! -d "$w/drive/pg17/wal_005" ]] || fail "при превышении квоты выгрузка не должна начинаться"

# 2.6 Сбой записи на «Drive» (каталог назначения — файл): fail, причина из журнала rclone, ID папки нигде не виден.
in_box 'mkdir -p /t/drive && printf x > /t/drive/pg17'
extra=(-e OFFSITE_KEEP_DAYS=14 -e "OFFSITE_GDRIVE_FOLDER_ID=$FOLDER_ID")
rc=0; run --now > "$tmp/out" 2>&1 || rc=$?
[[ "$rc" == 1 && "$(field result)" == fail && -n "$(field reason)" ]] || { status; fail "сбой записи: ожидался fail"; }
! grep -rq "$FOLDER_ID" "$w/status" "$w/state" "$tmp/out" || fail "ID папки попал в status.json, состояние или журнал"
in_box 'rm -f /t/drive/pg17'

# 2.7 Расписание и healthcheck (функции скрипта в режиме библиотеки).
docker run --rm -v "$w:/t" -v "$script:/offsite/gdrive-sync.sh:ro" -e TZ=UTC --entrypoint sh "$image" -c '
set -e
export OFFSITE_LIB=1 OFFSITE_STATE_DIR=/t/sched OFFSITE_RETRY_MIN=30
mkdir -p /t/sched; rm -f /t/sched/*
. /offsite/gdrive-sync.sh
t=$(date -u +%s)
ok() { if due; then echo "due"; else echo "wait"; fi; }
[ "$(ok)" = due ] || { echo "первый запуск без отметок должен быть сразу"; exit 1; }
echo not_configured > /t/sched/last_result; echo $((t - 60)) > /t/sched/last_attempt
[ "$(ok)" = wait ] || { echo "не настроено: повтор не чаще 10 минут"; exit 1; }
echo $((t - 700)) > /t/sched/last_attempt
[ "$(ok)" = due ] || { echo "не настроено: через 10 минут — проверка снова"; exit 1; }
echo fail > /t/sched/last_result; echo $((t - 600)) > /t/sched/last_attempt
[ "$(ok)" = wait ] || { echo "сбой: повтор через OFFSITE_RETRY_MIN"; exit 1; }
echo $((t - 1900)) > /t/sched/last_attempt
[ "$(ok)" = due ] || { echo "сбой: через 30 минут — повтор"; exit 1; }
echo ok > /t/sched/last_result; echo $((t - 90000)) > /t/sched/last_success
[ "$(ok)" = due ] || { echo "успех старше суток — копировать сразу"; exit 1; }
sched=$(date -u -d "$(date -u +%Y-%m-%d) $(date -u -d @$((t - 60)) +%H:%M)" +%s)
AT_UTC=$(date -u -d @$((t - 60)) +%H:%M); echo $((sched - 3600)) > /t/sched/last_success
[ "$(ok)" = due ] || { echo "время по расписанию наступило — копировать"; exit 1; }
echo $((sched + 1)) > /t/sched/last_success
[ "$(ok)" = wait ] || { echo "уже скопировано после времени расписания — ждать завтра"; exit 1; }
echo $t > /t/sched/heartbeat; (health) || { echo "свежая отметка — healthy"; exit 1; }
echo $((t - 900)) > /t/sched/heartbeat; if (health) >/dev/null; then echo "старая отметка — unhealthy"; exit 1; fi
mkdir /t/sched/lock; (health) || { echo "идёт копирование — healthy"; exit 1; }
' > "$tmp/out" 2>&1 || { cat "$tmp/out"; fail "расписание или healthcheck"; }
echo "offsite-gdrive-test: ok"
