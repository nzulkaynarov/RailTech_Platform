#!/usr/bin/env bash
# Тест OPS-YADISK: ветка Яндекс Диска сервиса внешней копии (infra/offsite/offsite-sync.sh). Без Яндекса и без секретов: Яндекс
# подменён настоящим WebDAV-сервером `rclone serve webdav` (Basic-авторизация, тот же закреплённый образ rclone) на 127.0.0.1
# внутри контейнера; пароль приложения — фиктивный, собран из частей.
#  1. Конфигурация rclone (режим библиотеки): webdav, vendor other, адрес https://webdav.yandex.ru по умолчанию, логин из
#     settings.json, пароль — `rclone obscure` (раскрывается в исходный); в томе состояния открытого пароля нет, файл — chmod 600.
#  2. Копия на «Яндекс Диск» из интерфейса (бакет offsite-config: settings.json с провайдером и yandex-password): итог ok,
#     провайдер yandex в status.json, объекты в папке с кириллицей, событие offsite_sync_finished со средней скоростью; пароль и
#     логин не попадают ни в журнал, ни в status.json, ни в том состояния.
#  3. Неверный пароль — сбой access с сообщением про Яндекс Диск; пароль не печатается.
#  4. Не настроено: нет логина — no_login, нет пароля — no_password; OFFSITE_PROVIDER сильнее интерфейса.
#  5. Причины по журналу rclone WebDAV: 401/403 — access, 507 — quota.
# Запуск: bash этот-файл
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
script="$root/infra/offsite/offsite-sync.sh"
image="$(sed -n 's|^[[:space:]]*image:[[:space:]]*\(rclone/rclone:[^[:space:]]*\)[[:space:]]*$|\1|p' "$root/infra/compose/prod.yml" | head -n 1)"
[[ -n "$image" ]] || { echo "FAIL: нет образа rclone в prod.yml"; exit 1; }
tmp="$(mktemp -d)"; trap 'docker run --rm -v "$tmp:/t" --entrypoint sh "$image" -c "rm -rf /t/w" >/dev/null 2>&1 || true; rm -rf "$tmp"' EXIT
fail() { echo "FAIL: $*"; exit 1; }
w="$tmp/w"; mkdir -p "$w"
LOGIN="backup@example.org"
APP_PASSWORD="fake""pass""word""test"   # фиктивный пароль приложения (16 латинских букв, как у Яндекса)
FOLDER="Бэкапы/прод"

in_box() { docker run --rm -v "$w:/t" --entrypoint sh "$image" -c "$1"; }
field() { jq -r ".$1" "$w/status/status.json"; }
status() { cat "$w/status/status.json"; }

# Архив: базовая копия 1 сутки назад и её WAL.
in_box '
set -e
mk() { mkdir -p "$(dirname "$1")"; printf "%s" "$3" > "$1"; touch -d "$2" "$1"; }
d=$(date -u -d "@$(( $(date -u +%s) - 86400 ))" "+%Y-%m-%d %H:%M:%S")
s=/t/src/pg17; hex=000000010000000000000006
mk $s/basebackups_005/base_$hex/tar_partitions/part_1.tar.zst "$d" "data-$hex-$(head -c 20000 /dev/urandom | od -An -tx1 | tr -d " \n")"
mk $s/basebackups_005/base_$hex/metadata.json "$d" "{}"
mk $s/basebackups_005/base_${hex}_backup_stop_sentinel.json "$d" "{\"x\":1}"
mk $s/wal_005/$hex.zst "$d" "wal-$hex"; mk $s/wal_005/000000010000000000000007.zst "$d" "wal-7"
mkdir -p /t/cfg /t/status /t/dav
'
cfg() { # cfg <provider> <login> <папка> [пароль] — объекты offsite-config, как их кладёт CRM
  in_box 'rm -f /t/cfg/*'
  printf '{"provider": "%s", "login": "%s", "folder_path": "%s"}' "$1" "$2" "$3" > "$w/cfg/settings.json"
  if [[ -n "${4:-}" ]]; then printf '%s' "$4" > "$w/cfg/yandex-password"; fi
}

# run <пароль сервера WebDAV> <аргументы offsite-sync.sh> — «Яндекс» на 127.0.0.1:8080 в том же контейнере.
run() {
  local dav_pass="$1"; shift
  docker run --rm -v "$w:/t" -v "$script:/offsite/offsite-sync.sh:ro" -e TZ=UTC -e OFFSITE_RETRIES=1 -e OFFSITE_RETRIES_SLEEP=1s \
    -e OFFSITE_CONFIG_SRC=/t/cfg -e OFFSITE_STATE_DIR=/t/state -e OFFSITE_SRC=/t/src/pg17 -e OFFSITE_STATUS_DST=/t/status/status.json \
    -e OFFSITE_GDRIVE_SA_FILE=/t/nokey.json -e OFFSITE_YANDEX_URL=http://127.0.0.1:8080 -e DAV_USER="$LOGIN" -e DAV_PASS="$dav_pass" \
    ${extra[@]+"${extra[@]}"} --entrypoint sh "$image" -c '
      rclone serve webdav /t/dav --addr 127.0.0.1:8080 --user "$DAV_USER" --pass "$DAV_PASS" > /tmp/serve.log 2>&1 &
      i=0; until grep -q "Serving" /tmp/serve.log 2>/dev/null || [ $i -ge 50 ]; do i=$((i + 1)); sleep 0.1; done
      sh /offsite/offsite-sync.sh "$@"' sh "$@"
}
extra=()

# --- 1. Конфигурация rclone и пароль в томе состояния --------------------------------------------------------------------
cfg yandex "$LOGIN" "$FOLDER" "$APP_PASSWORD"
docker run --rm -v "$w:/t" -v "$script:/offsite/offsite-sync.sh:ro" -e TZ=UTC -e OFFSITE_LIB=1 -e OFFSITE_CONFIG_SRC=/t/cfg \
  -e OFFSITE_STATE_DIR=/t/libstate -e OFFSITE_GDRIVE_SA_FILE=/t/nokey.json -e WANT="$APP_PASSWORD" --entrypoint sh "$image" -c '
set -e
mkdir -p /t/libstate
. /offsite/offsite-sync.sh
load_config
[ "$PROVIDER" = yandex ] || { echo "провайдер: $PROVIDER"; exit 1; }
[ "$RCLONE_CONFIG_YADISK_TYPE" = webdav ] && [ "$RCLONE_CONFIG_YADISK_VENDOR" = other ] || { echo "не webdav/other"; exit 1; }
[ "$RCLONE_CONFIG_YADISK_URL" = https://webdav.yandex.ru ] || { echo "адрес WebDAV: $RCLONE_CONFIG_YADISK_URL"; exit 1; }
[ "$RCLONE_CONFIG_YADISK_USER" = backup@example.org ] || { echo "логин: $RCLONE_CONFIG_YADISK_USER"; exit 1; }
[ "$RCLONE_CONFIG_YADISK_PASS" != "$WANT" ] || { echo "пароль в окружении открытым текстом"; exit 1; }
[ "$(rclone reveal "$RCLONE_CONFIG_YADISK_PASS")" = "$WANT" ] || { echo "obscure не раскрывается в пароль"; exit 1; }
[ "$DST" = "yadisk:Бэкапы/прод/pg17" ] || { echo "назначение: $DST"; exit 1; }
[ "$(stat -c %a /t/libstate/config/yandex-pass.obscured)" = 600 ] || { echo "файл пароля не chmod 600"; exit 1; }
[ -z "$(config_problem)" ] || { echo "настроено, а config_problem: $(config_problem)"; exit 1; }
' > "$tmp/out" 2>&1 || { cat "$tmp/out"; fail "конфигурация rclone для Яндекс Диска"; }
! grep -rq "$APP_PASSWORD" "$w/libstate" || fail "пароль приложения открытым текстом в томе состояния"

# --- 2. Копия на «Яндекс Диск» ------------------------------------------------------------------------------------------------
run "$APP_PASSWORD" --now > "$tmp/out" 2>&1 || { cat "$tmp/out"; status || true; fail "копия на Яндекс Диск не прошла"; }
[[ "$(field result)" == ok && "$(field provider)" == yandex ]] || { status; fail "итог: ok и провайдер yandex"; }
[[ -s "$w/dav/$FOLDER/pg17/basebackups_005/base_000000010000000000000006/tar_partitions/part_1.tar.zst" \
  && -e "$w/dav/$FOLDER/pg17/basebackups_005/base_000000010000000000000006_backup_stop_sentinel.json" \
  && -e "$w/dav/$FOLDER/pg17/wal_005/000000010000000000000007.zst" ]] || { find "$w/dav"; fail "состав копии на «Диске»"; }
[[ "$(field speed_bps)" =~ ^[1-9][0-9]*$ ]] || { status; fail "в status.json нет средней скорости (speed_bps)"; }
finished="$(grep '"offsite_sync_finished"' "$tmp/out" || true)"
[[ -n "$finished" ]] || { cat "$tmp/out"; fail "нет события offsite_sync_finished"; }
jq -e '.provider == "yandex" and .copied_files == 5 and .copied_bytes > 20000 and .avg_bytes_per_s > 0 and (.avg_speed | test("(КБ|МБ)/с$"))' \
  <<<"$finished" >/dev/null || fail "offsite_sync_finished без скорости или объёма: $finished"
for where in "$tmp/out" "$w/status" "$w/state"; do
  ! grep -rq "$APP_PASSWORD" "$where" || fail "пароль приложения попал в $where"
done
! grep -rq "$LOGIN" "$tmp/out" "$w/status" || fail "логин попал в журнал или status.json"
# Повтор без нового: ничего не выгружено, скорость прошлой выгрузки в status.json остаётся.
speed="$(field speed_bps)"
run "$APP_PASSWORD" --now > "$tmp/out" 2>&1 || { cat "$tmp/out"; fail "повтор копии не прошёл"; }
grep '"offsite_sync_finished"' "$tmp/out" | jq -e '.copied_files == 0' >/dev/null || fail "повтор выгрузил объекты заново"
[[ "$(field speed_bps)" == "$speed" ]] || fail "повтор без выгрузки затёр среднюю скорость"

# --- 3. Неверный пароль --------------------------------------------------------------------------------------------------------
cfg yandex "$LOGIN" "$FOLDER" "wrong""pass""word""test"
rc=0; run "$APP_PASSWORD" --now > "$tmp/out" 2>&1 || rc=$?
[[ "$rc" == 1 && "$(field result)" == fail && "$(field reason)" == access ]] || { cat "$tmp/out"; status; fail "неверный пароль: fail/access"; }
[[ "$(field message)" == *"Яндекс Диск отказал в доступе"* ]] || { status; fail "сообщение про Яндекс Диск"; }
! grep -rq "wrongpasswordtest\|$APP_PASSWORD" "$tmp/out" "$w/status" "$w/state" || fail "пароль попал в журнал сбоя"

# --- 4. Не настроено и аварийный выбор провайдера --------------------------------------------------------------------------
cfg yandex "" "$FOLDER" "$APP_PASSWORD"
rc=0; run "$APP_PASSWORD" --now > "$tmp/out" 2>&1 || rc=$?
[[ "$rc" == 3 && "$(field reason)" == no_login && "$(field provider)" == yandex ]] || { status; fail "нет логина: not_configured/no_login"; }
in_box 'rm -rf /t/state/config'
cfg yandex "$LOGIN" "$FOLDER"
rc=0; run "$APP_PASSWORD" --now > "$tmp/out" 2>&1 || rc=$?
[[ "$rc" == 3 && "$(field reason)" == no_password ]] || { status; fail "нет пароля: not_configured/no_password"; }
[[ "$(field message)" == *"Admin → Подключения"* ]] || fail "сообщение не ведёт в интерфейс"
cfg yandex "$LOGIN" "$FOLDER" "$APP_PASSWORD"
extra=(-e OFFSITE_PROVIDER=gdrive)
rc=0; run "$APP_PASSWORD" --now > "$tmp/out" 2>&1 || rc=$?
[[ "$rc" == 3 && "$(field provider)" == gdrive && "$(field reason)" == no_key ]] || { status; fail "OFFSITE_PROVIDER=gdrive сильнее интерфейса"; }
extra=()

# --- 5. Причины по журналу WebDAV ---------------------------------------------------------------------------------------------
docker run --rm -v "$script:/offsite/offsite-sync.sh:ro" -e OFFSITE_LIB=1 -e OFFSITE_STATE_DIR=/tmp/s --entrypoint sh "$image" -c '
set -e
. /offsite/offsite-sync.sh
t() { printf "%s\n" "$2" > /tmp/log; got="$(classify /tmp/log)"; [ "$got" = "$1" ] || { echo "ждали $1, получили $got: $2"; exit 1; }; }
t access "ERROR : error listing: couldn'"'"'t list files: 401 Unauthorized: 401 Unauthorized"
t access "CRITICAL: Failed to create file system: read metadata failed: 403 Forbidden: 403 Forbidden"
t quota "ERROR : x.zst: Failed to copy: 507 Insufficient Storage: Insufficient Storage"
t network "ERROR : dial tcp: lookup webdav.yandex.ru: no such host"
PROVIDER=yandex; m="$(message_of quota)"; case "$m" in *"Яндекс Диске"*) ;; *) echo "сообщение quota: $m"; exit 1 ;; esac
' > "$tmp/out" 2>&1 || { cat "$tmp/out"; fail "классификация ошибок WebDAV"; }
echo "offsite-yandex-test: ok"
