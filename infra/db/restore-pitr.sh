#!/usr/bin/env bash
# Восстановление PostgreSQL на заданный момент времени из WAL-архива (S0-3) в ОТДЕЛЬНЫЙ контейнер с отдельным томом.
# Боевые контейнеры и том postgres_data не затрагиваются; восстановленный экземпляр не пишет в боевой архив (archive_mode=off).
# Запускать на VPS 2 (нужны docker, образ rt-db-postgres:local — его собирает db-up.sh — и файл $RT_DB_DIR/.env.db).
#
#   restore-pitr.sh --target-time "2026-10-22 14:30:00+00"     на момент времени (часовой пояс обязателен: +00, +05, Z)
#   restore-pitr.sh --latest                                   до конца архива (последний сохранённый момент)
#   restore-pitr.sh --drop [--name rt-pitr]                    убрать контейнер и том восстановления
#   restore-pitr.sh --latest --source file --file-dir <каталог>  из копии архива на диске (скачана с Google Drive:
#                                                              infra/db/restore-from-gdrive.sh); ключ — WAL_ENC_KEY из --env-file
# Параметры: --name <имя> (по умолчанию rt-pitr; должно начинаться с rt-pitr), --backup <имя-копии> (по умолчанию — последняя,
#   завершённая до момента), --source primary|ext|file (хранилище: RustFS на VPS 1, внешнее S3 или каталог --file-dir), --port <порт> (опубликовать на
#   127.0.0.1), --memory <лимит> (по умолчанию 512m: VPS 2 — 2 ГБ, боевая база держит 1,25 ГБ), --timeout <сек> (ожидание конца восстановления, по умолчанию 1800),
#   --env-file <файл> (по умолчанию $RT_DB_DIR/.env.db), --image <образ> (по умолчанию rt-db-postgres:local).
# Момент должен быть не позже последней зафиксированной транзакции в архиве: иначе PostgreSQL остановится с сообщением
# «recovery ended before configured recovery target was reached» — тогда укажите более ранний момент или --latest.
set -euo pipefail

RT_DB_DIR="${RT_DB_DIR:-/opt/rt-db}"
envf="$RT_DB_DIR/.env.db"
image="rt-db-postgres:local"
name="rt-pitr"
target="" latest=0 drop=0 backup="" source=primary port="" memory=512m timeout=1800 file_dir=""
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

die() { echo "restore-pitr: $*" >&2; exit 1; }
usage() { sed -n '2,16p' "$0"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target-time) target="${2:?--target-time: \"YYYY-MM-DD HH:MM:SS+00\"}"; shift 2 ;;
    --latest) latest=1; shift ;;
    --drop) drop=1; shift ;;
    --name) name="${2:?}"; shift 2 ;;
    --backup) backup="${2:?}"; shift 2 ;;
    --source) source="${2:?}"; shift 2 ;;
    --file-dir) file_dir="${2:?}"; shift 2 ;;
    --port) port="${2:?}"; shift 2 ;;
    --memory) memory="${2:?}"; shift 2 ;;
    --timeout) timeout="${2:?}"; shift 2 ;;
    --env-file) envf="${2:?}"; shift 2 ;;
    --image) image="${2:?}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "неизвестный аргумент: $1" ;;
  esac
done

[[ "$name" =~ ^rt-pitr[a-z0-9_.-]*$ ]] || die "--name должно начинаться с rt-pitr (боевые контейнеры rt-db-* не трогаем)"
[[ "$source" == primary || "$source" == ext || "$source" == file ]] || die "--source: primary, ext или file"
# Источник file: каталог копии архива (basebackups_005/, wal_005/) монтируется в контейнеры только на чтение; rt-walg — из репозитория
# рядом со скриптом: образ, собранный до OPS-GDRIVE, источника file не знает, а восстанавливать бывает нужно и на чужой машине.
file_mounts=()
if [[ "$source" == file && $drop -eq 0 ]]; then
  [[ -n "$file_dir" && -d "$file_dir/basebackups_005" ]] || die "--source file: нужен --file-dir <каталог с basebackups_005/ и wal_005/>"
  file_dir="$(cd "$file_dir" && pwd)"
  file_mounts=(-v "$file_dir:/walg-file:ro" -v "$here/rt-walg.sh:/usr/local/bin/rt-walg:ro")
fi
[[ "$timeout" =~ ^[0-9]+$ ]] || die "--timeout: число секунд"
[[ -z "$port" || "$port" =~ ^[0-9]+$ ]] || die "--port: число"
volume="${name}-data"

if [[ $drop -eq 1 ]]; then
  docker rm -f "$name" >/dev/null 2>&1 || true
  docker volume rm "$volume" >/dev/null 2>&1 || true
  echo "restore-pitr: контейнер $name и том $volume удалены"
  exit 0
fi

if [[ -n "$target" && $latest -eq 1 ]] || [[ -z "$target" && $latest -eq 0 ]]; then
  usage >&2; die "нужен ровно один из --target-time и --latest"
fi
if [[ -n "$target" ]]; then
  # Часовой пояс обязателен: без него момент зависел бы от настроек сервера.
  [[ "$target" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}[\ T][0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?(Z|[+-][0-9]{2}(:?[0-9]{2})?)$ ]] \
    || die "формат момента: \"YYYY-MM-DD HH:MM:SS+00\" (часовой пояс обязателен), получено: $target"
  target="${target/T/ }"
  target="${target/%Z/+00}"
fi

command -v docker >/dev/null || die "docker не найден"
docker image inspect "$image" >/dev/null 2>&1 || die "нет образа $image — соберите: infra/deploy/db-up.sh (или docker compose -f infra/compose/db.yml build postgres)"
[[ -f "$envf" ]] || die "нет $envf (передайте --env-file)"
docker inspect "$name" >/dev/null 2>&1 && die "контейнер $name уже есть: удалите (--drop) или выберите другое --name"
docker volume inspect "$volume" >/dev/null 2>&1 && die "том $volume уже есть: удалите (--drop) или выберите другое --name"

# Только нужные переменные, во временный файл 0600 (не в аргументы командной строки).
get() { grep -E "^$1=" "$envf" | tail -1 | cut -d= -f2- || true; }
tmpenv="$(umask 077; mktemp)"
trap 'rm -f "$tmpenv"' EXIT
for v in WAL_S3_ENDPOINT WAL_S3_ACCESS_KEY WAL_S3_SECRET_KEY WAL_S3_BUCKET WAL_S3_PREFIX WAL_ENC_KEY \
         BACKUP_EXT_ENDPOINT BACKUP_EXT_ACCESS_KEY BACKUP_EXT_SECRET_KEY BACKUP_EXT_BUCKET BACKUP_EXT_REGION; do
  printf '%s=%s\n' "$v" "$(get "$v")" >> "$tmpenv"
done
[[ "$source" != file ]] || printf 'WAL_FILE_PREFIX=/walg-file\n' >> "$tmpenv"
# С неверным WAL_ENC_KEY backup-fetch не падает, а зависает — предел ожидания (rt-pitr prepare), по умолчанию 2 ч.
printf 'WAL_FETCH_TIMEOUT_S=%s\n' "${WAL_FETCH_TIMEOUT_S:-7200}" >> "$tmpenv"

echo "▸ том $volume: скачиваю базовую копию и настраиваю восстановление (источник: $source)"
docker volume create "$volume" >/dev/null
args=(--source "$source")
[[ -z "$target" ]] || args+=(--target-time "$target")
[[ -z "$backup" ]] || args+=(--backup "$backup")
if ! docker run --rm --user postgres --env-file "$tmpenv" -v "$volume:/var/lib/postgresql/data" ${file_mounts[@]+"${file_mounts[@]}"} --entrypoint rt-pitr "$image" \
    prepare /var/lib/postgresql/data "${args[@]}"; then
  docker volume rm "$volume" >/dev/null 2>&1 || true
  die "не удалось подготовить восстановление (причина выше)"
fi

echo "▸ контейнер $name: запуск восстановления"
run=(docker run -d --name "$name" --user postgres --env-file "$tmpenv" --memory "$memory" --label rt.pitr=1
     -v "$volume:/var/lib/postgresql/data" ${file_mounts[@]+"${file_mounts[@]}"} --entrypoint rt-pitr)
[[ -z "$port" ]] || run+=(-p "127.0.0.1:$port:5432")
"${run[@]}" "$image" serve /var/lib/postgresql/data >/dev/null

start="$(date +%s)"
state=""
while :; do
  if [[ "$(docker inspect -f '{{.State.Running}}' "$name")" != true ]]; then
    echo "--- журнал контейнера $name (хвост):" >&2
    docker logs --tail 25 "$name" >&2 || true
    die "PostgreSQL остановился до конца восстановления (см. журнал выше). Том $volume сохранён; убрать: $0 --drop --name $name"
  fi
  state="$(docker exec -u postgres "$name" psql -X -At -U postgres -d postgres -c 'SELECT pg_is_in_recovery()' 2>/dev/null || true)"
  [[ "$state" == f ]] && break
  (( $(date +%s) - start < timeout )) || die "восстановление не закончилось за ${timeout} с; журнал: docker logs $name"
  sleep 3
done

echo "▸ восстановление завершено за $(( $(date +%s) - start )) с:"
docker logs "$name" 2>&1 | grep -E 'recovery stopping|recovery ended|selected new timeline|archive recovery complete|database system is ready' | sed 's/^/    /' || true
docker exec -u postgres "$name" psql -X -At -U postgres -d postgres -c "SELECT datname FROM pg_database WHERE datname NOT IN ('template0','template1','postgres') ORDER BY 1" | sed 's/^/    база: /'

cat <<EOM

Готово. Боевая база не тронута. Восстановленный экземпляр: контейнер $name, том $volume, WAL-архив он НЕ пополняет.

Проверить данные:
  docker exec -it -u postgres $name psql -U postgres -d <база>          # crm | erp | litellm | langfuse
  docker exec -u postgres $name psql -U postgres -d erp -c 'SELECT count(*) FROM <таблица>'

Переключить (решает владелец; остановка записи обязательна), два пути:
  A) Вернуть часть данных (обычный случай: «удалили не то»). Снять дамп нужной базы и залить в боевую
     (docs/runbooks/deploy.md п. 4, «Восстановление боевой базы»):
       docker exec -u postgres $name pg_dump -U postgres -Fc -d erp > /var/backups/rt/pitr-erp.dump
  B) Заменить весь кластер (потеря/порча тома): остановить приложения на VPS 1 и базу на VPS 2, сохранить том postgres_data,
     подставить в него содержимое тома $volume, запустить и сразу сделать базовую копию — пошаговая команда:
     docs/runbooks/backup-pitr.md, раздел 3, «Действие 2», вариант B. Кластер уйдёт на новую ветку времени (timeline);
     архив продолжится в тот же каталог.
Убрать восстановленный экземпляр: $0 --drop --name $name
EOM
