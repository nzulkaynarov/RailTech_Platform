#!/bin/sh
# s3-init (S0-9, ADR-0013 п. 6): одноразовый инициализатор RustFS. Работает в образе rustfs/rc (Alpine: sh, jq, rc) и
# идемпотентен — запускается при каждом `up`/деплое и приводит хранилище к описанному здесь состоянию:
#   1. создаёт бакеты (S3_BUCKETS);
#   2. на каждый сервис заводит своего пользователя (ключ S3_<СЕРВИС>_ACCESS_KEY / _SECRET_KEY) и политику rt-<сервис>
#      с доступом только к его бакетам; повторный запуск обновляет секрет и политику (так делается ротация ключа);
#   3. удаляет пользователей, которых здесь нет (сменили идентификатор ключа — старый перестаёт действовать);
#   4. ставит правило жизненного цикла erp-temp: объекты старше 1 суток удаляются;
#   5. проверяет матрицу доступа реальными запросами под ключом каждого сервиса и падает при расхождении.
# Корневой ключ (S3_ROOT_*) нужен только RustFS и этому скрипту; ни один сервис его не получает. Секреты не печатаются.
set -eu

: "${S3_ENDPOINT:?}" "${S3_BUCKETS:?}" "${S3_ROOT_ACCESS_KEY:?}" "${S3_ROOT_SECRET_KEY:?}"

log() { printf 's3-init: %s\n' "$*"; }
die() { printf 's3-init: ОШИБКА: %s\n' "$*" >&2; exit 1; }

# Сервисы и их доступ. Бакеты: erp-* — файлы ERP; kb-sources, client-documents, tg-attachments — CRM; langfuse — события и
# медиа Langfuse; wal — архив WAL-G (VPS 2); backups — ежедневные дампы (VPS 2 пишет, CRM читает статус бэкапа).
SERVICES="erp crm langfuse wal backup"
rw_of() {
  case "$1" in
    erp) echo "erp-private erp-public erp-temp" ;;
    crm) echo "kb-sources client-documents tg-attachments" ;;
    langfuse) echo "langfuse" ;;
    wal) echo "wal" ;;
    backup) echo "backups" ;;
  esac
}
ro_of() {
  case "$1" in
    crm) echo "backups" ;; # статус бэкапа в «Центре внешних сервисов»: только чтение
    *) echo "" ;;
  esac
}
key_of() { # <сервис> <ACCESS_KEY|SECRET_KEY>
  upper="$(printf '%s' "$1" | tr '[:lower:]' '[:upper:]')"
  eval "printf '%s' \"\${S3_${upper}_$2:-}\""
}

# Политика: чтение/запись/удаление объектов в rw-бакетах, чтение — в ro-бакетах. Больше ничего (ни создания бакетов, ни IAM).
policy_json() { # <rw-бакеты> <ro-бакеты>
  jq -n --arg rw "$1" --arg ro "$2" '
    ($rw | split(" ") | map(select(. != ""))) as $rw
    | ($ro | split(" ") | map(select(. != ""))) as $ro
    | {Version: "2012-10-17", Statement: (
        (if ($rw | length) > 0 then [
          {Effect: "Allow", Action: ["s3:ListBucket", "s3:GetBucketLocation", "s3:ListBucketMultipartUploads"],
           Resource: ($rw | map("arn:aws:s3:::" + .))},
          {Effect: "Allow", Action: ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"],
           Resource: ($rw | map("arn:aws:s3:::" + . + "/*"))}] else [] end)
        + (if ($ro | length) > 0 then [
          {Effect: "Allow", Action: ["s3:ListBucket", "s3:GetBucketLocation"], Resource: ($ro | map("arn:aws:s3:::" + .))},
          {Effect: "Allow", Action: ["s3:GetObject"], Resource: ($ro | map("arn:aws:s3:::" + . + "/*"))}] else [] end))}'
}

contains() { case " $1 " in *" $2 "*) return 0 ;; esac; return 1; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# Ключи: заданы, не совпадают с корневым и друг с другом (иначе разграничение теряет смысл).
: >"$work/access"
for svc in $SERVICES; do
  ak="$(key_of "$svc" ACCESS_KEY)"; sk="$(key_of "$svc" SECRET_KEY)"
  [ -n "$ak" ] && [ -n "$sk" ] || die "не заданы S3_$(printf '%s' "$svc" | tr '[:lower:]' '[:upper:]')_ACCESS_KEY / _SECRET_KEY"
  [ "$ak" != "$S3_ROOT_ACCESS_KEY" ] || die "ключ сервиса $svc совпадает с корневым"
  printf '%s\n' "$ak" >>"$work/access"
done
[ -z "$(sort "$work/access" | uniq -d)" ] || die "у двух сервисов одинаковый идентификатор ключа"

rc alias set root "$S3_ENDPOINT" "$S3_ROOT_ACCESS_KEY" "$S3_ROOT_SECRET_KEY" >/dev/null

# 1. Бакеты.
for bucket in $S3_BUCKETS; do
  rc bucket create "root/$bucket" -p >/dev/null
  log "бакет готов: $bucket"
done

# 2. Пользователи и политики.
for svc in $SERVICES; do
  ak="$(key_of "$svc" ACCESS_KEY)"; sk="$(key_of "$svc" SECRET_KEY)"
  policy_json "$(rw_of "$svc")" "$(ro_of "$svc")" >"$work/$svc.json"
  rc admin policy create root "rt-$svc" "$work/$svc.json" >/dev/null
  rc admin user add root "$ak" "$sk" >/dev/null
  rc admin policy attach root "rt-$svc" --user "$ak" >/dev/null
  log "ключ сервиса $svc: политика rt-$svc (запись: $(rw_of "$svc"); только чтение: $(ro_of "$svc"))"
done

# 3. Чужие пользователи (старые ключи после смены идентификатора, заведённые вручную) удаляются. Корневой ключ не трогается никогда,
# даже если RustFS покажет его в списке пользователей.
prune_users() { # <файл со списком допустимых ключей> — на stdin текущие ключи, по одному на строку
  while IFS= read -r existing; do
    [ -n "$existing" ] || continue
    [ "$existing" != "$S3_ROOT_ACCESS_KEY" ] || continue
    grep -qxF -- "$existing" "$1" || { rc admin user rm root "$existing" >/dev/null; log "удалён пользователь вне списка"; }
  done
}
rc admin user ls root --json | jq -r '.users[].accessKey' >"$work/existing"
prune_users "$work/access" <"$work/existing"

# 4. Жизненный цикл erp-temp: 1 сутки. Импорт заменяет набор правил целиком — повтор ничего не дублирует.
cat >"$work/lifecycle.json" <<'JSON'
{"Rules":[{"ID":"rt-erp-temp-expire-1d","Status":"Enabled","Filter":{"Prefix":""},"Expiration":{"Days":1}}]}
JSON
rc bucket lifecycle rule import root/erp-temp "$work/lifecycle.json" >/dev/null
log "erp-temp: удаление объектов через 1 сутки"

# 5. Матрица доступа: каждый сервис видит свои бакеты и не видит чужие; ro-бакет читается, но не пишется.
for svc in $SERVICES; do
  alias_name="u-$svc"
  rc alias set "$alias_name" "$S3_ENDPOINT" "$(key_of "$svc" ACCESS_KEY)" "$(key_of "$svc" SECRET_KEY)" >/dev/null
  rw="$(rw_of "$svc")"; ro="$(ro_of "$svc")"
  for bucket in $S3_BUCKETS; do
    if contains "$rw" "$bucket"; then
      rc ls "$alias_name/$bucket" >/dev/null 2>&1 || die "$svc: нет чтения своего бакета $bucket"
      printf 'probe' | rc pipe "$alias_name/$bucket/.s3-init-probe" >/dev/null 2>&1 || die "$svc: нет записи в свой бакет $bucket"
      rc rm "$alias_name/$bucket/.s3-init-probe" >/dev/null 2>&1 || die "$svc: нет удаления в своём бакете $bucket"
    elif contains "$ro" "$bucket"; then
      rc ls "$alias_name/$bucket" >/dev/null 2>&1 || die "$svc: нет чтения бакета $bucket"
      if printf 'probe' | rc pipe "$alias_name/$bucket/.s3-init-probe" >/dev/null 2>&1; then
        rc rm "root/$bucket/.s3-init-probe" >/dev/null 2>&1 || true
        die "$svc: запись в бакет $bucket должна быть закрыта"
      fi
    else
      if rc ls "$alias_name/$bucket" >/dev/null 2>&1; then die "$svc: чужой бакет $bucket доступен"; fi
    fi
  done
  log "проверка доступа сервиса $svc: ok"
done
log "готово"
