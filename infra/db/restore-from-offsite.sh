#!/usr/bin/env bash
# Восстановление и учения из внешней копии архива — Яндекс Диск или Google Drive (OPS-GDRIVE, OPS-YADISK; runbook
# docs/runbooks/offsite-gdrive.md, «Учения»). Нужно, когда потеряны оба сервера или хранилище RustFS; ежемесячно — проверка, что копия
# пригодна. Боевую базу не трогает. Работает на любой машине с Docker и этим репозиторием (VPS 2, новый сервер, ноутбук): доступ к
# Диску и ключ шифрования архива WAL_ENC_KEY (из офлайн-копии или /opt/rt-db/.env.db) передаются явно.
#
#   restore-from-offsite.sh --login <почта Яндекс 360> --password-file <файл с паролем приложения> [--folder-path <папка>] \
#       --env-file <файл с WAL_ENC_KEY> --check                                     (Яндекс Диск, WebDAV)
#   restore-from-offsite.sh --sa-file <ключ.json> --folder-id <ID> --env-file <файл с WAL_ENC_KEY> --check   (Google Drive)
#       учения: скачать копию в пустой каталог, показать базовые копии (wal-g backup-list), развернуть последнее состояние в
#       одноразовый контейнер PostgreSQL, проверить базы (--expect-dbs) и удалить контейнер и том. Код 0 — копия пригодна
#   restore-from-offsite.sh ... --latest | --target-time "YYYY-MM-DD HH:MM:SS+00"
#       восстановление: то же без удаления — контейнер rt-pitr-offsite остаётся, дальше — backup-pitr.md, раздел 3, «Действие 2»
# Провайдер: --provider yandex|gdrive (по умолчанию — по параметрам: --login → yandex, --sa-file → gdrive). Яндекс: пароль приложения
#   «Файлы» — только из файла (chmod 600; в аргументах и журнале его нет), --folder-path — папка на Диске (по умолчанию
#   RailTech-backups/prod, как в Платформе). Google: --shared-drive-id <ID> — если общий диск нужно указать явно.
# Параметры: --dir <каталог> (куда скачать; по умолчанию новый в /var/tmp; должен быть пуст или не существовать), --prefix <каталог
#   архива> (по умолчанию pg17 — как WAL_S3_PREFIX), --name <контейнер> (по умолчанию rt-pitr-offsite), --image <образ> (по
#   умолчанию rt-db-postgres:local; нет — соберите: docker build -t rt-db-postgres:local -f infra/db/Dockerfile.postgres infra/db),
#   --expect-dbs "crm erp eds" (что обязано быть после восстановления), --bwlimit <полоса rclone> (по умолчанию без ограничения),
#   --keep-dir (не удалять скачанное после учений).
# Места на диске нужно ≈ объём копии (строка CRM «Внешняя копия бэкапов») + размер базы.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
sa="" folder="" envf="" dir="" prefix=pg17 shared="" name=rt-pitr-offsite image=rt-db-postgres:local expect="crm erp eds"
bwlimit=0 keep_dir=0 mode="" target="" provider="" login="" passfile="" folder_path=RailTech-backups/prod
# Источник копии — локальный каталог вместо Диска (тесты: offsite-restore-live-test.sh); пусто — Яндекс Диск или Google Drive.
local_remote="${RESTORE_OFFSITE_REMOTE:-${RESTORE_GDRIVE_REMOTE:-}}"
yandex_url="${RESTORE_YANDEX_URL:-https://webdav.yandex.ru}"

die() { echo "restore-from-offsite: $*" >&2; exit 1; }
say() { printf '▸ %s\n' "$*"; }
usage() { sed -n '2,25p' "$0"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --provider) provider="${2:?}"; shift 2 ;;
    --login) login="${2:?}"; shift 2 ;;
    --password-file) passfile="${2:?}"; shift 2 ;;
    --folder-path) folder_path="${2:?}"; shift 2 ;;
    --sa-file) sa="${2:?}"; shift 2 ;;
    --folder-id) folder="${2:?}"; shift 2 ;;
    --env-file) envf="${2:?}"; shift 2 ;;
    --dir) dir="${2:?}"; shift 2 ;;
    --prefix) prefix="${2:?}"; shift 2 ;;
    --shared-drive-id) shared="${2:?}"; shift 2 ;;
    --name) name="${2:?}"; shift 2 ;;
    --image) image="${2:?}"; shift 2 ;;
    --expect-dbs) expect="${2:?}"; shift 2 ;;
    --bwlimit) bwlimit="${2:?}"; shift 2 ;;
    --keep-dir) keep_dir=1; shift ;;
    --check) mode=check; shift ;;
    --latest) mode=latest; shift ;;
    --target-time) mode=target; target="${2:?}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "неизвестный аргумент: $1" ;;
  esac
done

[[ -n "$mode" ]] || { usage >&2; die "нужен один из --check, --latest, --target-time"; }
[[ -n "$envf" && -f "$envf" ]] || die "нужен --env-file с WAL_ENC_KEY (офлайн-копия или /opt/rt-db/.env.db)"
grep -qE '^WAL_ENC_KEY=[0-9a-fA-F]{64}$' "$envf" || die "в $envf нет WAL_ENC_KEY (64 hex-символа): без него архив не расшифровать"
[[ "$prefix" =~ ^[A-Za-z0-9._-]+$ ]] || die "--prefix: только буквы, цифры, точка, дефис, подчёркивание"
[[ "$name" =~ ^rt-pitr[a-z0-9_.-]*$ ]] || die "--name должно начинаться с rt-pitr (боевые контейнеры rt-db-* не трогаем)"
if [[ -z "$provider" ]]; then
  if [[ -n "$login" || -n "$passfile" ]]; then provider=yandex; elif [[ -n "$sa" || -n "$folder" ]]; then provider=gdrive; fi
fi
if [[ -z "$local_remote" ]]; then
  case "$provider" in
    yandex)
      [[ -n "$login" ]] || die "нужен --login — адрес почты Яндекс 360, на Диске которого лежит копия"
      [[ -n "$passfile" && -s "$passfile" ]] || die "нужен --password-file — файл с паролем приложения «Файлы» (chmod 600)"
      [[ "$folder_path" =~ ^[^\"\\]+$ && ! "$folder_path" =~ (^|/)\.\.(/|$) ]] || die "--folder-path: путь без кавычек и «..»" ;;
    gdrive)
      [[ -n "$sa" && -s "$sa" ]] || die "нужен --sa-file — ключ сервисного аккаунта Google (JSON)"
      [[ -n "$folder" ]] || die "нужен --folder-id — ID папки общего диска (часть адреса после /folders/)" ;;
    *) die "нужен провайдер: --login и --password-file (Яндекс Диск) или --sa-file и --folder-id (Google Drive); --provider yandex|gdrive" ;;
  esac
fi
command -v docker >/dev/null || die "docker не найден"
docker image inspect "$image" >/dev/null 2>&1 \
  || die "нет образа $image — соберите: docker build -t $image -f $here/Dockerfile.postgres $here"
rclone_image="$(sed -n 's|^[[:space:]]*image:[[:space:]]*\(rclone/rclone:[^[:space:]]*\)[[:space:]]*$|\1|p' "$here/../compose/prod.yml" | head -n 1)"
[[ -n "$rclone_image" ]] || die "не нашёл образ rclone в infra/compose/prod.yml"

auto_dir=0 pitr_started=0
if [[ -z "$dir" ]]; then dir="$(mktemp -d /var/tmp/rt-offsite-XXXXXX)"; auto_dir=1; fi
mkdir -p "$dir"
dir="$(cd "$dir" && pwd)"
[[ -z "$(ls -A "$dir")" ]] || die "$dir не пуст — нужен пустой каталог (или не существующий)"
# Учения (--check) после себя ничего не оставляют — и при успехе, и при сбое: одноразовый контейнер и том восстановления (только если
# их создал этот запуск), скачанную копию и созданный здесь каталог /var/tmp/rt-offsite-*. Восстановление (--latest, --target-time)
# оставляет всё: контейнер нужен для переключения. Файл переменных rclone с паролем (obscure) удаляется всегда.
rclone_env="$(umask 077; mktemp)"
cleanup() {
  rm -f "$rclone_env"
  [[ "$mode" == check ]] || return 0
  [[ $pitr_started -eq 0 ]] || "$here/restore-pitr.sh" --drop --name "$name" >/dev/null 2>&1 || true
  [[ $keep_dir -eq 0 ]] || return 0
  docker run --rm -v "$dir:/d" --entrypoint sh "$rclone_image" -c 'rm -rf /d/* /d/.files' >/dev/null 2>&1 || true
  [[ $auto_dir -eq 0 ]] || rmdir "$dir" 2>/dev/null || true
}
trap cleanup EXIT

# 1. Скачать копию. Ключ Google монтируется только на чтение; пароль приложения Яндекса — только как `rclone obscure` в файле
# переменных (chmod 600, удаляется при выходе): ни в аргументах docker, ни в журнале его нет. ID папки и логин — в переменных rclone.
say "скачиваю копию архива ($prefix, ${provider:-локальный каталог}) в $dir"
args=(--rm -v "$dir:/dl" --env-file "$rclone_env")
if [[ -n "$local_remote" ]]; then
  args+=(-v "$local_remote:/remote:ro"); src="/remote/$prefix"
elif [[ "$provider" == yandex ]]; then
  obscured="$(docker run --rm -i --entrypoint rclone "$rclone_image" obscure - < "$passfile")" \
    || die "rclone obscure не прочитал пароль из $passfile"
  printf 'RCLONE_CONFIG_YADISK_TYPE=webdav\nRCLONE_CONFIG_YADISK_VENDOR=other\nRCLONE_CONFIG_YADISK_URL=%s\nRCLONE_CONFIG_YADISK_USER=%s\nRCLONE_CONFIG_YADISK_PASS=%s\n' \
    "$yandex_url" "$login" "$obscured" > "$rclone_env"
  obscured=""
  src="yadisk:$folder_path/$prefix"
else
  printf 'RCLONE_CONFIG_GDRIVE_TYPE=drive\nRCLONE_CONFIG_GDRIVE_SCOPE=drive.readonly\nRCLONE_CONFIG_GDRIVE_SERVICE_ACCOUNT_FILE=/sa.json\nRCLONE_CONFIG_GDRIVE_ROOT_FOLDER_ID=%s\n' \
    "$folder" > "$rclone_env"
  [[ -z "$shared" ]] || printf 'RCLONE_CONFIG_GDRIVE_TEAM_DRIVE=%s\n' "$shared" >> "$rclone_env"
  args+=(-v "$(cd "$(dirname "$sa")" && pwd)/$(basename "$sa"):/sa.json:ro")
  src="gdrive:$prefix"
fi
net=(--retries 5 --low-level-retries 10 --timeout 5m)
# Для --check и --latest нужна только последняя базовая копия и WAL с её начала (плюс история веток) — меньше скачивать и места на
# диске; для --target-time — всё окно (момент может быть раньше последней копии).
only=()
if [[ "$mode" != target ]]; then
  listing="$(docker run "${args[@]}" "$rclone_image" lsf -R --files-only "$src" "${net[@]}")" \
    || die "не удалось прочитать папку на Диске: логин и пароль приложения или ключ Google, доступ к папке, путь или ID папки (runbook offsite-gdrive.md, «Диагностика»)"
  newest="$(grep -E '^basebackups_005/base_[0-9A-F]{24}_backup_stop_sentinel\.json$' <<<"$listing" | sort | tail -n 1 | cut -c22-45)"
  [[ -n "$newest" ]] || die "на Диске в $prefix нет ни одной базовой копии — неверный --prefix или --folder-path, или копия ещё не делалась"
  awk -v b="x$newest" '
    /^basebackups_005\/base_[0-9A-F]{24}/ { if (("x" substr($0, 22, 24)) == b) print; next }
    /^wal_005\/[0-9A-F]{24}/ { if (("x" substr($0, 9, 24)) >= b) print; next }
    /^wal_005\// { print }' <<<"$listing" > "$dir/.files"
  only=(--files-from-raw /dl/.files)
  say "последняя базовая копия: base_$newest; скачиваю её и WAL после неё ($(wc -l < "$dir/.files" | tr -d ' ') объектов)"
fi
docker run "${args[@]}" "$rclone_image" copy "$src" "/dl/$prefix" ${only[@]+"${only[@]}"} --transfers 4 --checkers 8 "${net[@]}" \
  --bwlimit "$bwlimit" --stats 1m --stats-one-line \
  || die "не удалось скачать копию: доступ к Диску и папке (runbook offsite-gdrive.md, «Диагностика»)"
rm -f "$dir/.files"
[[ -d "$dir/$prefix/basebackups_005" ]] || die "в копии нет basebackups_005/ — неверный --prefix или папка пуста"

# 2. Что видит WAL-G: базовые копии в скачанном каталоге (метаданные копий не зашифрованы, данные — да).
say "базовые копии во внешней копии (wal-g backup-list):"
tmpenv="$(umask 077; mktemp)"
trap 'rm -f "$tmpenv"; cleanup' EXIT
grep -E '^WAL_ENC_KEY=' "$envf" | tail -n 1 > "$tmpenv"
printf 'WAL_FILE_PREFIX=/walg-file\n' >> "$tmpenv"
list="$(docker run --rm --user postgres --env-file "$tmpenv" -v "$dir/$prefix:/walg-file:ro" -v "$here/rt-walg.sh:/usr/local/bin/rt-walg:ro" \
  --entrypoint rt-walg "$image" --source file backup-list --detail)" || die "wal-g не прочитал копию (backup-list)"
printf '%s\n' "$list" | sed 's/^/    /'
[[ "$(printf '%s\n' "$list" | grep -c '^base_')" -gt 0 ]] || die "в копии нет ни одной базовой копии"

# 3. Развернуть в одноразовый контейнер (restore-pitr.sh: отдельный том, archive_mode=off, боевые rt-db-* не трогаются).
pitr=("$here/restore-pitr.sh" --source file --file-dir "$dir/$prefix" --env-file "$envf" --image "$image" --name "$name")
case "$mode" in
  check|latest) pitr+=(--latest) ;;
  target) pitr+=(--target-time "$target") ;;
esac
if docker inspect "$name" >/dev/null 2>&1 || docker volume inspect "$name-data" >/dev/null 2>&1; then
  die "контейнер или том $name уже есть (прошлое восстановление?): уберите — $here/restore-pitr.sh --drop --name $name — или задайте --name"
fi
pitr_started=1
"${pitr[@]}" || die "восстановление из внешней копии не удалось (причина выше); убрать остатки: $here/restore-pitr.sh --drop --name $name"

if [[ "$mode" != check ]]; then
  say "готово: контейнер $name с восстановленными базами; каталог копии $dir (нужен контейнеру для WAL, не удаляйте до переключения)"
  exit 0
fi

# 4. Учения: базы на месте — копия пригодна. Затем всё одноразовое убирается.
got="$(docker exec -u postgres "$name" psql -X -At -U postgres -d postgres -c "SELECT datname FROM pg_database" | tr '\n' ' ')"
missing=""
for db in $expect; do [[ " $got " == *" $db "* ]] || missing+="$db "; done
"$here/restore-pitr.sh" --drop --name "$name" >/dev/null
pitr_started=0
[[ -z "$missing" ]] || die "учения НЕ пройдены: в восстановленном кластере нет баз: ${missing% } (есть: ${got% })"
say "учения пройдены: внешняя копия разворачивается, базы на месте (${expect}); контейнер и том удалены"
