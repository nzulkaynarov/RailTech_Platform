#!/usr/bin/env bash
# Тест BEK-1: внешняя копия бэкапов переживает выкладки (сервис offsite-backup не пересоздаётся без смены образа или скрипта).
# Секретов и сети не требует; Drive и RustFS подменены локальными каталогами, rclone в «копировании» подменён заглушкой sleep.
#  1. stable_ops_file (lib.sh): путь зависит от СОДЕРЖИМОГО скрипта, а не от каталога релиза; смена содержимого — новый путь;
#     хранятся пять последних копий; нет прав на каталог — путь из релиза (прежнее поведение).
#  2. compose: описание сервиса offsite-backup из двух разных каталогов релиза совпадает (значит, compose его не пересоздаёт);
#     контроль: без переменной OFFSITE_SCRIPT_PATH описания различаются (тест краснеет без защиты); смена содержимого — различаются.
#  3. Демон: SIGTERM посреди копирования — rclone остановлен, блокировка снята, status.json «interrupted», выход 0 быстрее grace;
#     после перезапуска копирование стартует сразу (без паузы повтора) и блокировка прежнего контейнера не мешает.
# Запуск: bash этот-файл
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
tmp="$(mktemp -d)"
cname="rt-bek1-$$"
cleanup() { [[ -n "${KEEP:-}" ]] && { docker logs "$cname" 2>&1 | tail -20; return 0; }; docker rm -f "$cname" >/dev/null 2>&1 || true; docker run --rm -v "$tmp:/t" alpine:3.22 rm -rf /t/w >/dev/null 2>&1 || true; rm -rf "$tmp"; }
trap cleanup EXIT
fail() { echo "FAIL: $*"; exit 1; }

# --- 1. stable_ops_file -----------------------------------------------------------------------------------------------------
mkrel() { mkdir -p "$1/infra/offsite"; cp "$root/infra/offsite/offsite-sync.sh" "$1/infra/offsite/offsite-sync.sh"; }
mkrel "$tmp/rel1"; mkrel "$tmp/rel2"
ops() { ( RT_ROOT="$tmp/rt" RT_OPS_DIR="${OPS:-$tmp/ops}"; export RT_ROOT RT_OPS_DIR; source "$root/infra/deploy/lib.sh"; stable_ops_file "$1" ); }
p1="$(ops "$tmp/rel1/infra/offsite/offsite-sync.sh")"; p2="$(ops "$tmp/rel2/infra/offsite/offsite-sync.sh")"
[[ "$p1" == "$p2" && "$p1" == "$tmp"/ops/offsite-sync.*.sh ]] || fail "одинаковое содержимое из разных релизов должно давать один путь: $p1 / $p2"
cmp -s "$p1" "$root/infra/offsite/offsite-sync.sh" || fail "копия в ops не совпадает с исходником"
echo "# changed" >> "$tmp/rel2/infra/offsite/offsite-sync.sh"
p3="$(ops "$tmp/rel2/infra/offsite/offsite-sync.sh")"
[[ "$p3" != "$p1" && -f "$p3" && -f "$p1" ]] || fail "смена содержимого должна давать новый путь, старый остаётся"
for i in 1 2 3 4 5 6 7; do echo "# v$i" >> "$tmp/rel2/infra/offsite/offsite-sync.sh"; ops "$tmp/rel2/infra/offsite/offsite-sync.sh" >/dev/null; sleep 0.05; done
[[ "$(find "$tmp/ops" -name 'offsite-sync.*.sh' | wc -l)" -eq 5 ]] || fail "должно храниться пять последних копий"
touch "$tmp/ro"; got="$(OPS="$tmp/ro/x" ops "$tmp/rel1/infra/offsite/offsite-sync.sh" 2>/dev/null)"
[[ "$got" == "$tmp/rel1/infra/offsite/offsite-sync.sh" ]] || fail "нет прав на каталог: ожидался путь из релиза, получен $got"

# --- 2. compose не пересоздаёт сервис между релизами --------------------------------------------------------------------------
sed 's/CHANGE_ME/ci-only-value/' "$root/infra/.env.prod.example" | grep -vE '^S3_OFFSITE_(ACCESS|SECRET)_KEY=' > "$tmp/env.prod"
printf 'S3_OFFSITE_ACCESS_KEY=a\nS3_OFFSITE_SECRET_KEY=b\n' >> "$tmp/env.prod"
for r in relA relB; do mkdir -p "$tmp/$r"; cp -r "$root/infra" "$tmp/$r/infra"; done
cfg() { # cfg <релиз> [путь скрипта для OFFSITE_SCRIPT_PATH]
  local e=(RT_IMAGE_TAG=bek1)
  [[ -z "${2:-}" ]] || e+=("OFFSITE_SCRIPT_PATH=$2")
  env "${e[@]}" docker compose -f "$tmp/$1/infra/compose/base.yml" -f "$tmp/$1/infra/compose/prod.yml" --env-file "$tmp/env.prod" \
    config --format json 2>/dev/null | jq -S '.services["offsite-backup"]'
}
[[ "$(cfg relA "$p1")" == "$(cfg relB "$p1")" ]] || fail "описание offsite-backup различается между релизами при одном содержимом скрипта"
[[ "$(cfg relA)" != "$(cfg relB)" ]] || fail "контроль: без OFFSITE_SCRIPT_PATH описания должны различаться (тест не ловит регресс)"
[[ "$(cfg relA "$p1")" != "$(cfg relA "$p3")" ]] || fail "смена содержимого скрипта должна менять описание сервиса (пересоздание)"
[[ "$(cfg relA "$p1" | jq -r '.stop_grace_period')" == 1m0s ]] || fail "stop_grace_period offsite-backup должен быть 60s"

# --- 3. SIGTERM посреди копирования -----------------------------------------------------------------------------------------
image="$(cfg relA "$p1" | jq -r .image)"
w="$tmp/w"; mkdir -p "$w/shim" "$w/secrets" "$w/status"
cat > "$w/shim/rclone" <<'SH'
#!/bin/sh
# Заглушка: «copy» длится вечно (как долгая выгрузка), остальное — настоящий rclone.
case " $* " in *" copy "*) date +%s%N >> /t/shim/copies; exec sleep 600 ;; esac
exec /usr/local/bin/rclone "$@"
SH
chmod +x "$w/shim/rclone"
docker run --rm -v "$w:/t" --entrypoint sh "$image" -c '
set -e
s=/t/src/pg17; mkdir -p $s/basebackups_005/base_000000010000000000000002 $s/wal_005
echo data > $s/basebackups_005/base_000000010000000000000002/part_1.tar.zst
echo "{}" > $s/basebackups_005/base_000000010000000000000002_backup_stop_sentinel.json
echo wal > $s/wal_005/000000010000000000000002.zst
printf "{\"type\": \"service_account\", \"client_email\": \"x@example.iam.gserviceaccount.com\", \"private_key\": \"k\"}" > /t/secrets/gdrive-sa.json'
daemon() {
  docker rm -f "$cname" >/dev/null 2>&1 || true
  docker run -d --name "$cname" -v "$w:/t" -v "$root/infra/offsite/offsite-sync.sh:/offsite/offsite-sync.sh:ro" -e PATH=/t/shim:/usr/local/bin:/usr/bin:/bin:/sbin -e TZ=UTC \
    -e OFFSITE_RETRIES=1 -e OFFSITE_RETRIES_SLEEP=1s -e OFFSITE_STATE_DIR=/t/state -e OFFSITE_CONFIG_SRC=/t/cfg -e OFFSITE_SRC=/t/src/pg17 \
    -e OFFSITE_DST=/t/drive/pg17 -e OFFSITE_STATUS_DST=/t/status/status.json -e OFFSITE_GDRIVE_SA_FILE=/t/secrets/gdrive-sa.json \
    -e OFFSITE_GDRIVE_FOLDER_ID=TESTFOLDERID1234567890 -e OFFSITE_FILE_BUCKETS= -e OFFSITE_PROGRESS_S=1 --entrypoint sh "$image" /offsite/offsite-sync.sh --daemon >/dev/null
}
waitlog() { for _ in $(seq 1 40); do docker logs "$cname" 2>&1 | grep -q "$1" && return 0; sleep 0.5; done; docker logs "$cname" 2>&1 | tail -20; fail "в журнале нет $1"; }
copies() { cat "$w/shim/copies" 2>/dev/null | wc -l; }
waitcopy() { for _ in $(seq 1 40); do [[ "$(copies)" -ge "$1" ]] && return 0; sleep 0.5; done; docker logs "$cname" 2>&1 | tail -30; { docker logs "$cname" 2>&1 | tail -30; fail "копирование №$1 не началось"; }; }
daemon; waitcopy 1
[[ -d "$w/state/lock" ]] || fail "во время копирования блокировки нет"
sleep 3
[[ "$(jq -r '.progress.files_total' "$w/status/status.json")" == 2 && "$(jq -r .message "$w/status/status.json")" == "Идёт копирование: скопировано 0 из 2 файлов;"* ]] \
  || { cat "$w/status/status.json"; fail "во время копирования в status.json нет хода прохода (progress, «Идёт копирование…»)"; }
t0=$(date +%s); docker stop -t 30 "$cname" >/dev/null; took=$(( $(date +%s) - t0 ))
logs="$(docker logs "$cname" 2>&1)"
[[ "$(docker inspect -f '{{.State.ExitCode}}' "$cname")" == 0 && "$took" -lt 25 ]] || { echo "$logs" | tail; fail "SIGTERM: ожидался выход 0 до grace-периода (took=$took)"; }
if ! { grep -q '"offsite_sync_interrupted"' <<<"$logs" && grep -q '"offsite_daemon_stopped"' <<<"$logs"; }; then echo "$logs" | tail; fail "нет событий interrupted/stopped"; fi
[[ ! -d "$w/state/lock" ]] || fail "блокировка осталась после остановки"
[[ "$(jq -r '.result + "/" + .reason' "$w/status/status.json")" == fail/interrupted ]] || { cat "$w/status/status.json"; fail "status.json должен быть fail/interrupted"; }
[[ "$(jq -r .message "$w/status/status.json")" == *"прервано выкладкой"* ]] || fail "в status.json нет текста «прервано выкладкой»"
# Перезапуск: копирование стартует сразу, без паузы повтора, хотя последняя попытка — «сбой» меньше минуты назад.
docker start "$cname" >/dev/null; waitcopy 2
# SIGKILL посреди копии (grace истёк): блокировка остаётся, следующий старт её снимает и тоже продолжает сразу.
docker kill "$cname" >/dev/null; [[ -d "$w/state/lock" ]] || fail "контроль: после SIGKILL блокировка должна остаться"
docker start "$cname" >/dev/null; waitlog offsite_stale_lock_removed; waitcopy 3
echo "offsite-survives-deploy: ok"
