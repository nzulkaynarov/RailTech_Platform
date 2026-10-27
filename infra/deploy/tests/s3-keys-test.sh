#!/usr/bin/env bash
# Тест S0-9: ключ S3 на сервис (ADR-0013 п. 6), правило erp-temp, закреплённые образы. Секретов не требует: env — копия примеров
# с заглушками, у каждого ключа своё значение, чтобы по значению было видно, кому ключ достался. Матрицу доступа на живом
# RustFS проверяет сам s3-init (infra/s3/init.sh, шаг 5) — на стенде; здесь — состав конфигурации и генерация ключей.
#  1. Примеры env: все ключи S3 — CHANGE_ME, старых общих S3_ACCESS_KEY/S3_SECRET_KEY нет.
#  2. Корневой ключ — только у rustfs и s3-init; ERP, CRM (все сервисы), Langfuse получают каждый свой ключ.
#  3. s3-init: образ rustfs/rc с версией и digest, init.sh смонтирован, бакеты включают backups и wal (прод и стенд одинаковы),
#     ждёт rustfs; потребители ждут s3-init. В init.sh: правило erp-temp 1 сутки и проверка матрицы.
#  4. make-env-prod.sh init: ключи разные и не печатаются; WAL_S3_* и BACKUP_RUSTFS_* равны ключам сервисов wal и backup;
#     extract-db отдаёт их VPS 2, но не корневой ключ и не ключи ERP/CRM/Langfuse.
# Запуск: bash этот-файл
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fail() { echo "FAIL: $*"; exit 1; }
base="$root/infra/compose/base.yml"; prod="$root/infra/compose/prod.yml"; dev="$root/infra/compose/dev.yml"
init="$root/infra/s3/init.sh"
names=(ROOT ERP CRM EDS LANGFUSE WAL BACKUP)

# 1. Примеры.
for example in "$root/.env.example" "$root/infra/.env.prod.example"; do
  for n in "${names[@]}"; do
    for part in ACCESS SECRET; do
      grep -q "^S3_${n}_${part}_KEY=CHANGE_ME$" "$example" || fail "$example: нет S3_${n}_${part}_KEY=CHANGE_ME"
    done
  done
  ! grep -qE '^S3_(ACCESS|SECRET)_KEY=' "$example" || fail "$example: остался общий ключ S3_ACCESS_KEY/S3_SECRET_KEY"
done

# Окружение с РАЗНЫМИ значениями ключей.
mkenv() { # mkenv <пример> <выход>
  sed 's/CHANGE_ME/ci-only-value/' "$1" | grep -vE '^S3_[A-Z]+_(ACCESS|SECRET)_KEY=' > "$2"
  for n in "${names[@]}"; do printf 'S3_%s_ACCESS_KEY=ak-%s\nS3_%s_SECRET_KEY=sk-%s\n' "$n" "$n" "$n" "$n" >> "$2"; done
}
mkenv "$root/infra/.env.prod.example" "$tmp/env.prod"
grep -v '^#' "$root/.env.example" | grep -v '^$' > "$tmp/env.dev.raw"; mkenv "$tmp/env.dev.raw" "$tmp/env.dev"
export RT_IMAGE_TAG=s3-keys-test
profiles=(--profile observability --profile kb-ingest --profile mcp)
docker compose -f "$base" -f "$prod" --env-file "$tmp/env.prod" "${profiles[@]}" config --format json > "$tmp/prod.json"
docker compose -f "$base" -f "$dev" --env-file "$tmp/env.dev" --profile observability config --format json > "$tmp/dev.json"

for f in prod dev; do
  j="$tmp/$f.json"
  env_of() { jq -r --arg s "$1" --arg k "$2" '.services[$s].environment[$k] // "none"' "$j"; }
  # 2. Кто какой ключ получил.
  holders() { # holders <подстрока значения> — сервисы, у которых она встречается в окружении
    jq -r --arg v "$1" '[.services | to_entries[] | select(.value.environment // {} | tostring | test($v)) | .key] | sort | join(",")' "$j"
  }
  [[ "$(holders 'ak-ROOT|sk-ROOT')" == rustfs,s3-init ]] || fail "$f: корневой ключ у лишних сервисов: $(holders 'ak-ROOT|sk-ROOT')"
  [[ "$(env_of rustfs RUSTFS_ACCESS_KEY)" == ak-ROOT && "$(env_of rustfs RUSTFS_SECRET_KEY)" == sk-ROOT ]] || fail "$f: rustfs не на корневом ключе"
  [[ "$(holders 'ak-ERP|sk-ERP')" == erp-ai-gateway,erp-backend,erp-beat,erp-mcp,erp-worker,erp-worker-ai,s3-init ]] \
    || fail "$f: ключ ERP у лишних сервисов: $(holders 'ak-ERP|sk-ERP')"
  for svc in erp-backend erp-worker erp-worker-ai erp-beat erp-mcp erp-ai-gateway; do
    [[ "$(env_of "$svc" MINIO_ACCESS_KEY)" == ak-ERP && "$(env_of "$svc" MINIO_SECRET_KEY)" == sk-ERP ]] || fail "$f: $svc не на ключе ERP"
  done
  crm_holders="$(holders 'ak-CRM|sk-CRM')"
  [[ "$crm_holders" == *crm-api* && "$crm_holders" == *crm-worker* && "$crm_holders" == *crm-bot* ]] || fail "$f: ключ CRM не у crm-api/crm-worker/crm-bot: $crm_holders"
  [[ "$crm_holders" != *erp-* && "$crm_holders" != *eds-* && "$crm_holders" != *langfuse* && "$crm_holders" != *rustfs* ]] || fail "$f: ключ CRM попал не в CRM: $crm_holders"
  # EDS (волна 12): свой ключ, только бакет eds-private; кроме EDS и s3-init его не знает никто.
  [[ "$(holders 'ak-EDS|sk-EDS')" == eds-api,eds-migrate,eds-worker,s3-init ]] || fail "$f: ключ EDS у лишних сервисов: $(holders 'ak-EDS|sk-EDS')"
  for svc in eds-api eds-worker eds-migrate; do
    [[ "$(env_of "$svc" S3_ACCESS_KEY)" == ak-EDS && "$(env_of "$svc" S3_SECRET_KEY)" == sk-EDS ]] || fail "$f: $svc не на ключе EDS"
  done
  for svc in crm-api crm-worker crm-bot; do
    [[ "$(env_of "$svc" S3_ACCESS_KEY)" == ak-CRM && "$(env_of "$svc" S3_SECRET_KEY)" == sk-CRM ]] || fail "$f: $svc не на ключе CRM"
  done
  [[ "$(holders 'ak-LANGFUSE|sk-LANGFUSE')" == langfuse-web,langfuse-worker,s3-init ]] || fail "$f: ключ Langfuse у лишних сервисов: $(holders 'ak-LANGFUSE|sk-LANGFUSE')"
  for svc in langfuse-web langfuse-worker; do
    for k in LANGFUSE_S3_EVENT_UPLOAD LANGFUSE_S3_MEDIA_UPLOAD; do
      [[ "$(env_of "$svc" ${k}_ACCESS_KEY_ID)" == ak-LANGFUSE && "$(env_of "$svc" ${k}_SECRET_ACCESS_KEY)" == sk-LANGFUSE ]] || fail "$f: $svc ($k) не на ключе Langfuse"
    done
  done
  # Ключи wal и backup — только у s3-init: потребляет их VPS 2 по своим переменным (db.yml), а не стек VPS 1.
  [[ "$(holders 'ak-WAL|sk-WAL|ak-BACKUP|sk-BACKUP')" == s3-init ]] || fail "$f: ключи WAL-G/бэкапа у лишних сервисов: $(holders 'ak-WAL|sk-WAL|ak-BACKUP|sk-BACKUP')"

  # 3. s3-init.
  image="$(jq -r '.services["s3-init"].image' "$j")"
  [[ "$image" =~ ^rustfs/rc:v[0-9]+\.[0-9]+\.[0-9]+@sha256:[0-9a-f]{64}$ ]] || fail "$f: образ s3-init не rustfs/rc:<версия>@sha256:<digest>: $image"
  [[ "$(jq -r '.services["s3-init"].entrypoint | join(" ")' "$j")" == "sh /init.sh" ]] || fail "$f: entrypoint s3-init не sh /init.sh"
  [[ "$(jq -r '[.services["s3-init"].volumes[] | select(.target == "/init.sh" and .read_only == true)] | length' "$j")" == 1 ]] || fail "$f: init.sh не смонтирован в s3-init только на чтение"
  buckets="$(jq -r '.services["s3-init"].environment.S3_BUCKETS' "$j")"
  for b in langfuse kb-sources client-documents tg-attachments erp-private erp-public erp-temp eds-private backups wal; do
    [[ " $buckets " == *" $b "* ]] || fail "$f: s3-init не создаёт бакет $b"
  done
  [[ "$(jq -r '.services["s3-init"].depends_on.rustfs.condition' "$j")" == service_healthy ]] || fail "$f: s3-init не ждёт rustfs"
  for svc in erp-backend crm-api langfuse-web; do
    [[ "$(jq -r --arg s "$svc" '.services[$s].depends_on["s3-init"].condition' "$j")" == service_completed_successfully ]] || fail "$f: $svc не ждёт s3-init"
  done
  [[ "$(jq -r '.services["s3-init"].restart' "$j")" == no ]] || fail "$f: s3-init должен быть одноразовым (restart: no)"
done

# Содержимое init.sh: доступы, правило erp-temp, проверка матрицы, секреты не печатаются.
grep -qE '^    erp\) echo "erp-private erp-public erp-temp" ;;$' "$init" || fail "init.sh: ERP не ограничен бакетами erp-*"
grep -qE '^    crm\) echo "kb-sources client-documents tg-attachments" ;;$' "$init" || fail "init.sh: бакеты CRM"
grep -qE '^    eds\) echo "eds-private" ;;' "$init" || fail "init.sh: EDS не ограничен бакетом eds-private"
grep -qE '^    crm\) echo "backups" ;;' "$init" || fail "init.sh: CRM должен читать бакет backups (только чтение)"
grep -qE '^    crm\) echo "wal" ;;' "$init" || fail "init.sh: CRM должен видеть список бакета wal (без чтения объектов)"
grep -qE '^    wal\) echo "wal" ;;$' "$init" || fail "init.sh: WAL-G не ограничен бакетом wal"
grep -qE '^    backup\) echo "backups" ;;$' "$init" || fail "init.sh: бэкап не ограничен бакетом backups"
grep -qE '^    langfuse\) echo "langfuse" ;;$' "$init" || fail "init.sh: Langfuse не ограничен бакетом langfuse"
grep -q '"Expiration":{"Days":1}' "$init" || fail "init.sh: нет правила жизненного цикла «1 сутки»"
grep -q 'rule import root/erp-temp' "$init" || fail "init.sh: правило жизненного цикла не на erp-temp"
grep -q 'чужой бакет' "$init" || fail "init.sh: нет проверки доступа к чужим бакетам"
! grep -qE '^set -[a-z]*x|--debug' "$init" || fail "init.sh: трассировка выведет секреты в журнал"
bash -n "$init" || fail "init.sh: синтаксис"
# Политику можно собрать и она не даёт лишнего (проверка на самом jq из init.sh).
if command -v jq >/dev/null; then
  fn="$(sed -n '/^policy_json() {/,/^}/p' "$init")"
  pol="$(bash -c "$fn; policy_json 'erp-private erp-public' 'backups'")"
  jq -e '.Statement | length == 4' <<<"$pol" >/dev/null || fail "политика: ожидается 4 утверждения (rw: бакеты и объекты, ro: бакеты и объекты)"
  jq -e '[.Statement[].Action[]] | all(. != "s3:*" and (startswith("s3:") ))' <<<"$pol" >/dev/null || fail "политика: подстановочные действия"
  jq -e '[.Statement[] | select(.Resource | tostring | test("backups")) | .Action[]] | all(. == "s3:ListBucket" or . == "s3:GetBucketLocation" or . == "s3:GetObject")' <<<"$pol" >/dev/null \
    || fail "политика: в ro-бакете есть что-то кроме чтения"
fi

# Удаление «лишних» пользователей: корневой ключ не трогается, чужие удаляются, свои остаются (rc подменён заглушкой).
fn="$(sed -n '/^prune_users() {/,/^}/p' "$init")"
[[ -n "$fn" ]] || fail "init.sh: нет prune_users"
printf 'keep-erp\nroot-ak\nstranger\n' > "$tmp/users.now"; printf 'keep-erp\n' > "$tmp/users.allowed"
removed="$(bash -c 'log() { :; }; rc() { [ "$1 $2 $3" = "admin user rm" ] && echo "$5" >&2; }; S3_ROOT_ACCESS_KEY=root-ak; '"$fn"'; prune_users "$1" < "$2"' _ "$tmp/users.allowed" "$tmp/users.now" 2>&1)"
[[ "$removed" == stranger ]] || fail "prune_users удалил не то: '$removed' (ожидался только stranger; корень и свои не трогаются)"

# 4. Генерация ключей и перенос на VPS 2.
file="$tmp/generated.env"
out="$(bash "$root/infra/deploy/make-env-prod.sh" init "$file")"
for n in "${names[@]}"; do
  for part in ACCESS SECRET; do
    v="$(grep "^S3_${n}_${part}_KEY=" "$file" | cut -d= -f2-)"
    [[ -n "$v" && "$v" != CHANGE_ME ]] || fail "init не сгенерировал S3_${n}_${part}_KEY"
    [[ "$out" != *"$v"* ]] || fail "init напечатал значение S3_${n}_${part}_KEY"
  done
done
all="$(grep -E '^S3_[A-Z]+_(ACCESS|SECRET)_KEY=' "$file" | cut -d= -f2- | sort)"
[[ "$(wc -l <<<"$all" | tr -d ' ')" == 14 && "$(uniq -d <<<"$all" | wc -l | tr -d ' ')" == 0 ]] || fail "ключи S3 не уникальны"
val() { grep "^$1=" "$file" | cut -d= -f2-; }
[[ "$(val BACKUP_RUSTFS_ACCESS_KEY)" == "$(val S3_BACKUP_ACCESS_KEY)" && "$(val BACKUP_RUSTFS_SECRET_KEY)" == "$(val S3_BACKUP_SECRET_KEY)" ]] || fail "BACKUP_RUSTFS_* не равны ключу сервиса backup"
[[ "$(val WAL_S3_ACCESS_KEY)" == "$(val S3_WAL_ACCESS_KEY)" && "$(val WAL_S3_SECRET_KEY)" == "$(val S3_WAL_SECRET_KEY)" ]] || fail "WAL_S3_* не равны ключу сервиса wal"
# Ротация: сменили ключ сервиса — `s3-keys` обновляет копию для VPS 2, `extract-s3` отдаёт её (после drop-db-only extract-db/init не годятся:
# они заново сгенерировали бы WAL_ENC_KEY и пароли VPS 2).
bash "$root/infra/deploy/make-env-prod.sh" extract-db "$file" > "$tmp/env.db"
for v in WAL_S3_ACCESS_KEY WAL_S3_SECRET_KEY BACKUP_RUSTFS_ACCESS_KEY BACKUP_RUSTFS_SECRET_KEY; do grep -q "^$v=" "$tmp/env.db" || fail "extract-db не отдаёт $v"; done
for n in ROOT ERP CRM EDS LANGFUSE; do
  v="$(val "S3_${n}_SECRET_KEY")"; ! grep -qF -- "$v" "$tmp/env.db" || fail "extract-db отдал VPS 2 ключ $n"
done
enc_before="$(val WAL_ENC_KEY)"
bash "$root/infra/deploy/make-env-prod.sh" drop-db-only "$file" >/dev/null
sed -i.bak 's/^S3_WAL_SECRET_KEY=.*/S3_WAL_SECRET_KEY=rotated-secret/' "$file" && rm -f "$file.bak"
bash "$root/infra/deploy/make-env-prod.sh" s3-keys "$file" >/dev/null
! grep -qE '^(WAL_ENC_KEY|DB_SUPERUSER_PASSWORD|BACKUP_ENC_PASSPHRASE)=' "$file" || fail "s3-keys вернул переменные VPS 2 после drop-db-only"
bash "$root/infra/deploy/make-env-prod.sh" extract-s3 "$file" > "$tmp/s3.vps2"
[[ "$(grep '^WAL_S3_SECRET_KEY=' "$tmp/s3.vps2" | cut -d= -f2-)" == rotated-secret ]] || fail "после ротации S3_WAL_SECRET_KEY extract-s3 не отдал новый секрет"
[[ -n "$enc_before" ]] || fail "WAL_ENC_KEY не был сгенерирован"
# Прод до S0-9: прежний общий ключ становится корневым (RustFS и старая копия на VPS 2 не рвутся), остальные ключи генерируются.
legacy="$tmp/legacy.env"
grep -vE '^S3_(ROOT|ERP|CRM|EDS|LANGFUSE|WAL|BACKUP)_(ACCESS|SECRET)_KEY=' "$root/infra/.env.prod.example" > "$legacy"
printf 'S3_ACCESS_KEY=legacy-access\nS3_SECRET_KEY=legacy-secret\nWAL_S3_ACCESS_KEY=legacy-access\nWAL_S3_SECRET_KEY=legacy-secret\n' >> "$legacy"
sed -i.bak -E '/^WAL_S3_(ACCESS|SECRET)_KEY=$/d' "$legacy" && rm -f "$legacy.bak"
bash "$root/infra/deploy/make-env-prod.sh" init "$legacy" >/dev/null
lv() { grep "^$1=" "$legacy" | cut -d= -f2-; }
[[ "$(lv S3_ROOT_ACCESS_KEY)" == legacy-access && "$(lv S3_ROOT_SECRET_KEY)" == legacy-secret ]] || fail "прежний S3_ACCESS_KEY/S3_SECRET_KEY не стал корневым"
! grep -qE '^S3_(ACCESS|SECRET)_KEY=' "$legacy" || fail "прежние S3_ACCESS_KEY/S3_SECRET_KEY не убраны"
[[ "$(lv S3_ERP_SECRET_KEY)" != CHANGE_ME && -n "$(lv S3_ERP_SECRET_KEY)" ]] || fail "ключ ERP не сгенерирован в старом файле"
[[ "$(lv WAL_S3_SECRET_KEY)" == "$(lv S3_WAL_SECRET_KEY)" && "$(lv WAL_S3_SECRET_KEY)" != legacy-secret ]] || fail "копия WAL_S3_* не переведена на ключ сервиса wal"
# s3-keys: только ключи S3; переменные VPS 2, убранные drop-db-only, не возвращаются; extract-s3 отдаёт VPS 2 ключи сервисов.
sk="$tmp/s3keys.env"
printf 'CRM_DOMAIN=crm.example.org\nS3_ACCESS_KEY=legacy-access\nS3_SECRET_KEY=legacy-secret\n' > "$sk"
bash "$root/infra/deploy/make-env-prod.sh" s3-keys "$sk" >/dev/null
skv() { grep "^$1=" "$sk" | cut -d= -f2-; }
[[ "$(skv S3_ROOT_ACCESS_KEY)" == legacy-access && "$(skv S3_ROOT_SECRET_KEY)" == legacy-secret ]] || fail "s3-keys: прежний ключ не стал корневым"
for n in ERP CRM EDS LANGFUSE WAL BACKUP; do [[ -n "$(skv "S3_${n}_SECRET_KEY")" && "$(skv "S3_${n}_SECRET_KEY")" != CHANGE_ME ]] || fail "s3-keys: нет ключа $n"; done
! grep -qE '^(WAL_|BACKUP_|DB_SUPERUSER|REDIS_)' "$sk" || fail "s3-keys вернул/добавил переменные не про S3"
before="$(cat "$sk")"; bash "$root/infra/deploy/make-env-prod.sh" s3-keys "$sk" >/dev/null
[[ "$(cat "$sk")" == "$before" ]] || fail "повторный s3-keys изменил файл"
bash "$root/infra/deploy/make-env-prod.sh" extract-s3 "$sk" > "$tmp/s3.vps2"
[[ "$(grep '^WAL_S3_SECRET_KEY=' "$tmp/s3.vps2" | cut -d= -f2-)" == "$(skv S3_WAL_SECRET_KEY)" ]] || fail "extract-s3: WAL_S3_SECRET_KEY"
[[ "$(grep '^BACKUP_RUSTFS_ACCESS_KEY=' "$tmp/s3.vps2" | cut -d= -f2-)" == "$(skv S3_BACKUP_ACCESS_KEY)" ]] || fail "extract-s3: BACKUP_RUSTFS_ACCESS_KEY"
[[ "$(wc -l < "$tmp/s3.vps2" | tr -d ' ')" == 4 ]] || fail "extract-s3 должен отдавать ровно 4 переменные"
! grep -qF -- "$(skv S3_ROOT_SECRET_KEY)" "$tmp/s3.vps2" || fail "extract-s3 отдал корневой ключ"
echo "s3-keys-test: ok"
