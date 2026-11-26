#!/usr/bin/env bash
# Тест ХРАН-1: копия файловых бакетов за пределы сервера, ЗАШИФРОВАННАЯ (infra/offsite/offsite-sync.sh, этап файлов). Без Диска и без
# секретов: RustFS и Диск подменены локальными каталогами (бэкенд local закреплённого образа rclone).
#  - файлы копируются с первой ночи с созданным ключом; пока он не отмечен сохранённым, status.json напоминает (files.key_saved=false); ключ нигде не печатается;
#  - файлы на Диске нечитаемы (ни имён, ни содержимого), восстановление ключом даёт исходные; архив WAL копируется ДО файлов;
#  - повтор ничего не копирует, ночью — только недавние объекты без обхода Диска, неделя — полный проход;
#  - удалённое у нас остаётся на Диске; изменённый файл — прежняя версия в _replaced;
#  - сбой одного бакета не останавливает другие; нехватка времени на первой выгрузке — pending, не сбой; нехватка места на Диске
#    пропускает файлы, архив не страдает; в журнал и status.json — ни имён файлов, ни ключа;
#  - прежние поля status.json на месте; --estimate; OFFSITE_FILE_BUCKETS= отключает этап; восстановление отметок из status.json;
#    блокировка длинной попытки не считается устаревшей; healthcheck.
# Запуск: bash этот-файл [путь к скрипту] — второй вариант нужен мутационной проверке.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
script="${1:-$root/infra/offsite/offsite-sync.sh}"
PEM_BEGIN="-----BEGIN PRIVATE"" KEY-----"; PEM_END="-----END PRIVATE"" KEY-----"
tmp="$(mktemp -d)"; trap 'docker run --rm -v "$tmp:/t" alpine:3.22 rm -rf /t/w >/dev/null 2>&1 || true; rm -rf "$tmp"' EXIT
fail() { echo "FAIL: $*"; exit 1; }
image="$(grep -m1 -oE 'rclone/rclone:[0-9.]+@sha256:[0-9a-f]{64}' "$root/infra/compose/prod.yml")"
[[ -n "$image" ]] || fail "образ rclone не найден в prod.yml"
w="$tmp/w"; mkdir -p "$w"
FOLDER_ID=TESTFOLDERID1234567890
BUCKETS="eds-private erp-private erp-public client-documents tg-attachments kb-sources"

extra=()
run() { # run <аргументы offsite-sync.sh>
  docker run --rm -v "$w:/t" -v "$script:/offsite/offsite-sync.sh:ro" -e TZ=UTC -e OFFSITE_RETRIES=1 -e OFFSITE_RETRIES_SLEEP=1s \
    -e OFFSITE_STATE_DIR=/t/state -e OFFSITE_SRC=/t/src/pg17 -e OFFSITE_DST=/t/drive/pg17 -e OFFSITE_STATUS_DST=/t/status/status.json \
    -e OFFSITE_FILES_SRC=/t/files/ -e OFFSITE_FILES_DST=/t/drive/files -e OFFSITE_CONFIG_SRC=/t/cfg -e OFFSITE_FILES_KEY_DIR=/t/key \
    -e OFFSITE_GDRIVE_SA_FILE=/t/secrets/gdrive-sa.json -e "OFFSITE_GDRIVE_FOLDER_ID=$FOLDER_ID" -e OFFSITE_KEEP_DAYS=14 \
    -e PATH=/t/bin:/usr/local/bin:/usr/bin:/bin \
    ${extra[@]+"${extra[@]}"} --entrypoint sh "$image" /offsite/offsite-sync.sh "$@"
}
in_box() { docker run --rm -v "$w:/t" --entrypoint sh "$image" -c "$1"$'\n'"chmod -R a+rwX /t"; }
status() { cat "$w/status/status.json"; }
jqs() { jq -r "$1" "$w/status/status.json"; }
restore() { # restore <бакет> — расшифровать бакет с Диска ключом в /t/rest/<бакет>
  in_box "rm -rf /t/rest/$1"; run --restore "$1" "/t/rest/$1" > "$tmp/restore.out" 2>&1 || { cat "$tmp/restore.out"; fail "восстановление $1"; }
}
key_leaked() { # ключ (обе строки) не должен встречаться в переданных файлах/каталогах
  local line f
  while read -r line; do
    for f in "$@"; do ! grep -rqF -- "$line" "$f" 2>/dev/null || return 0; done
  done < "$w/key/files-crypt.key"
  return 1
}

# Исходные данные.
in_box '
set -e
rm -rf /t/src /t/files /t/drive /t/status /t/state /t/secrets /t/cfg /t/key /t/rest /t/bin; mkdir -p /t/status /t/secrets /t/cfg /t/bin
s=/t/src/pg17; mkdir -p $s/basebackups_005/base_000000010000000000000004 $s/wal_005
echo data > $s/basebackups_005/base_000000010000000000000004/part_1.tar.zst
echo "{}" > $s/basebackups_005/base_000000010000000000000004_backup_stop_sentinel.json
echo wal > $s/wal_005/000000010000000000000004.zst
for b in eds-private erp-private erp-public client-documents tg-attachments kb-sources erp-temp langfuse backups; do
  mkdir -p /t/files/$b/sub; echo "doc-$b-1" > /t/files/$b/a-$b.pdf; echo "doc-$b-2" > /t/files/$b/sub/секретное-имя-$b.docx
done'
printf '{"type": "service_account", "client_email": "x@example.iam.gserviceaccount.com", "private_key": "%s\\nfake\\n%s\\n"}' "$PEM_BEGIN" "$PEM_END" > "$w/secrets/gdrive-sa.json"
# Обёртка rclone: журнал вызовов и внедрение сбоев; всё остальное — настоящий rclone.
cat > "$w/bin/rclone" <<'WRAP'
#!/bin/sh
echo "$*" >> /t/rclone.args
if [ "$1" = copy ] && [ -n "${FAIL_COPY_BUCKET:-}" ]; then
  case "$2" in */"$FAIL_COPY_BUCKET") echo "ERROR : injected copy failure for $2/a-secret-name.pdf" >&2; exit 1 ;; esac
fi
if [ "$1" = copy ] && [ -n "${SLOW_COPY_BUCKET:-}" ]; then
  case "$2" in */"$SLOW_COPY_BUCKET") sleep 3 ;; esac
fi
if [ "$1" = copy ] && [ -n "${TIMEOUT_COPY_BUCKET:-}" ]; then
  case "$2" in */"$TIMEOUT_COPY_BUCKET") echo "ERROR : max transfer duration reached" >&2; exit 10 ;; esac
fi
if [ "$1" = about ] && [ -n "${FAKE_ABOUT_FREE:-}" ]; then echo "{\"total\":1000,\"used\":990,\"free\":$FAKE_ABOUT_FREE}"; exit 0; fi
exec /usr/local/bin/rclone "$@"
WRAP
chmod +x "$w/bin/rclone"

# 1. Первая ночь: файлы копируются сразу, с созданным ключом, зашифрованными; ключ не отмечен сохранённым — status.json напоминает.
run --now > "$tmp/out" 2>&1 || { cat "$tmp/out"; fail "первая попытка не прошла"; }
[[ "$(jqs .files.result)" == ok && "$(jqs .files.key_saved)" == false && "$(jqs .result)" == ok ]] || { status; fail "первая ночь: files ok, key_saved=false, архив ok"; }
[[ -s "$w/drive/pg17/wal_005/000000010000000000000004.zst" && -d "$w/drive/files" ]] || fail "архив и файлы должны копироваться сразу"
[[ "$(docker run --rm -v "$w:/t" --entrypoint sh "$image" -c 'echo "$(stat -c %a /t/key /t/key/files-crypt.key | tr "\n" " ")$(wc -l < /t/key/files-crypt.key)"')" == "700 600 2" ]] \
  || fail "ключ: два значения, каталог 700, файл 600"
in_box true # дальше хост читает ключ только для проверки утечек
! key_leaked "$tmp/out" "$w/status" "$w/state" || fail "ключ попал в журнал, status.json или состояние"

# 2. Показ ключа оператору (один раз) и отметка «сохранён» — напоминание исчезает; копирование продолжается.
run --show-key > "$tmp/shown" 2>/dev/null || fail "--show-key"
[[ "$(grep -cE '^[0-9a-f]{64}$' "$tmp/shown")" == 2 ]] || fail "--show-key: две строки ключа"
run --key-saved > "$tmp/out" 2>&1 || fail "--key-saved"
[[ "$(jqs .files.key_saved)" == true ]] || { status; fail "после --key-saved key_saved должен быть true"; }
run --now > "$tmp/out" 2>&1 || { cat "$tmp/out"; fail "копия после отметки ключа не прошла"; }
[[ "$(jqs .files.result)" == ok && "$(jqs .files.files)" == 12 && "$(jqs '.files.buckets | length')" == 6 ]] || { status; fail "итог файлов: ok, 12 файлов, 6 бакетов"; }
n="$(jqs '.files.buckets["erp-public"].files')"; [[ "$n" == 2 ]] || { status; fail "бакет erp-public: 2 файла"; }
# Диск: ни имён, ни содержимого.
all_names="$(cd "$w/drive/files" && find . | tr '\n' ' ')"
for plain in a-eds-private секретное-имя eds-private erp-public client-documents sub; do
  [[ "$all_names" != *"$plain"* ]] || fail "на Диске читаемое имя: $plain"
done
! grep -rqE 'doc-[a-z-]+-[12]' "$w/drive/files" || fail "на Диске читаемое содержимое файлов"
(( $(find "$w/drive/files" -mindepth 1 -maxdepth 1 -type d | wc -l) == 6 )) || fail "на Диске должно быть 6 зашифрованных каталогов (erp-temp, langfuse, backups не копируются)"
# Восстановление ключом совпадает с исходным; лишних бакетов нет.
for b in $BUCKETS; do restore "$b"; diff -r "$w/files/$b" "$w/rest/$b" >/dev/null || fail "восстановленный $b отличается от исходного"; done
# Порядок: архив WAL — до файлов.
w_line="$(grep -n '"offsite_sync_finished"' "$tmp/out" | head -1 | cut -d: -f1)"; f_line="$(grep -n '"offsite_files_started"' "$tmp/out" | head -1 | cut -d: -f1)"
[[ -n "$w_line" && -n "$f_line" && "$w_line" -lt "$f_line" ]] || { cat "$tmp/out"; fail "архив WAL должен копироваться ДО файлов"; }
! grep -q "секретное-имя" "$tmp/out" "$w/status/status.json" || fail "имена файлов попали в журнал или status.json"
! key_leaked "$tmp/out" "$w/status" "$w/state" || fail "ключ попал в журнал, status.json или состояние"
! grep -rq "$FOLDER_ID" "$w/status" || fail "ID папки попал в status.json"
grep -q '"offsite_files_estimate_total"' "$tmp/out" || fail "в журнале нет оценки объёма"

# 3. Прежние поля status.json (строка CRM) на месте.
jq -e '.schema == 1 and .provider == "gdrive" and .result == "ok" and .reason == "" and (.attempt_at | test("Z$")) and (.last_success_at | test("Z$"))
  and (.bytes | type == "number") and (.objects | type == "number") and (.base_backups == 1) and (.quota_bytes == 107374182400)
  and .keep_days == 14 and .prefix == "pg17" and has("message") and has("detail") and has("duration_s") and has("speed_bps")
  and has("oldest_base_at") and has("newest_base_at")' "$w/status/status.json" >/dev/null || { status; fail "прежние поля status.json изменились"; }

# 4. Повтор: ночной проход — только недавние объекты, без обхода Диска; ничего не копируется заново.
in_box 'rm -f /t/rclone.args'
run --now > "$tmp/out" 2>&1 || { cat "$tmp/out"; fail "повтор не прошёл"; }
[[ "$(jqs '[.files.buckets[].copied_files] | add')" == 0 ]] || { status; fail "повтор скопировал файлы заново"; }
grep '"offsite_files_bucket_done"' "$tmp/out" | jq -e '.full_pass == 0' >/dev/null || fail "ночной проход должен быть неполным"
copies="$(grep '^copy .*FCRYPT:' "$w/rclone.args")"
(( $(grep -c -- '--max-age 48h --no-traverse' <<<"$copies") == 6 )) || { echo "$copies"; fail "ночью копирование должно идти с --max-age 48h --no-traverse"; }
! grep -qE '^(size|lsf|ls|lsl|lsjson) .*FCRYPT:' "$w/rclone.args" || fail "Диск обходится каждую ночь"
# Неделя: полный проход (OFFSITE_FILES_FULL_EVERY_S=0).
extra=(-e OFFSITE_FILES_FULL_EVERY_S=0)
run --now > "$tmp/out" 2>&1 || { cat "$tmp/out"; fail "полный проход не прошёл"; }
grep '"offsite_files_bucket_done"' "$tmp/out" | jq -e '.full_pass == 1' >/dev/null || fail "полный проход не выполнен"
extra=()

# 5. Не удаляет на Диске: файл пропал у нас — на Диске остаётся; новый — приходит. Изменённый — прежняя версия в _replaced.
in_box 'rm /t/files/eds-private/a-eds-private.pdf; echo new > /t/files/erp-public/new.pdf; echo "doc-erp-public-changed-and-longer" > /t/files/erp-public/a-erp-public.pdf'
run --now > "$tmp/out" 2>&1 || { cat "$tmp/out"; fail "копия после изменений не прошла"; }
restore eds-private; [[ -s "$w/rest/eds-private/a-eds-private.pdf" ]] || fail "удалённое у нас пропало на Диске (нужен copy, не sync)"
restore erp-public
[[ -s "$w/rest/erp-public/new.pdf" && "$(cat "$w/rest/erp-public/a-erp-public.pdf")" == "doc-erp-public-changed-and-longer" ]] || fail "новый или изменённый файл не скопирован"
[[ "$(jqs '.files.buckets["erp-public"].replaced_files')" == 1 ]] || { status; fail "replaced_files должен быть 1"; }
in_box 'rm -rf /t/rest; mkdir -p /t/rest'
run --restore _replaced /t/rest/replaced > "$tmp/restore.out" 2>&1 || fail "_replaced не читается ключом"
grep -rqF "doc-erp-public-2" "$w/rest/replaced" || grep -rqF "doc-erp-public-1" "$w/rest/replaced" || fail "прежняя версия изменённого файла не сохранена в _replaced"

# 6. Сбой двух бакетов (нет бакета, сбой copy): остальные скопированы, итог partial, имён и ключа в журнале нет.
in_box 'rm -rf /t/drive/files /t/files/kb-sources /t/state/files /t/state/files_last_success; echo again > /t/files/tg-attachments/more.jpg; echo back > /t/files/eds-private/a-eds-private.pdf'
extra=(-e FAIL_COPY_BUCKET=erp-private)
rc=0; run --now > "$tmp/out" 2>&1 || rc=$?
[[ "$rc" == 0 ]] || { cat "$tmp/out"; fail "сбой файлов не должен менять код выхода архива (rc=$rc)"; }
for b in eds-private erp-public client-documents tg-attachments; do restore "$b"; [[ -n "$(ls -A "$w/rest/$b")" ]] || fail "сбой соседа остановил копию $b"; done
[[ "$(jqs .files.result)" == partial && "$(jqs .result)" == ok ]] || { status; fail "итог при сбое двух бакетов: files partial, архив ok"; }
[[ "$(jqs '.files.buckets["kb-sources"].last_error_reason')" == source && "$(jqs '.files.buckets["erp-private"].result')" == fail ]] || { status; fail "причины по бакетам"; }
[[ "$(jqs '.files.last_success_at')" == null ]] || { status; fail "полной копии не было: last_success_at файлов null"; }
! grep -q "a-secret-name" "$tmp/out" "$w/status/status.json" || fail "имя файла из ошибки rclone попало в журнал или status.json"
# Сбой — повтор через RETRY_MIN, а не через сутки.
docker run --rm -v "$w:/t" -v "$script:/offsite/offsite-sync.sh:ro" -e TZ=UTC -e OFFSITE_LIB=1 -e OFFSITE_STATE_DIR=/t/state -e OFFSITE_RETRY_MIN=30 \
  --entrypoint sh "$image" -c '
set -e
. /offsite/offsite-sync.sh
t=$(date -u +%s)
echo ok > /t/state/last_result; echo $t > /t/state/last_success; echo $((t - 60)) > /t/state/last_attempt
[ "$(if due; then echo due; else echo wait; fi)" = wait ] || { echo "сразу после попытки ждать"; exit 1; }
echo $((t - 1900)) > /t/state/last_attempt
[ "$(if due; then echo due; else echo wait; fi)" = due ] || { echo "файлы не докопированы: повтор через 30 минут"; exit 1; }' > "$tmp/out" 2>&1 || { cat "$tmp/out"; fail "расписание повтора файлов"; }

# 7. Первая выгрузка не доезжает за срок: бакеты pending (не сбой), last_error пуст; следующая попытка заканчивает.
in_box 'rm -rf /t/drive/files /t/state/files /t/state/files_last_success; mkdir -p /t/files/kb-sources; echo k > /t/files/kb-sources/a-kb-sources.pdf'
extra=(-e SLOW_COPY_BUCKET=eds-private -e OFFSITE_FILES_TIMEOUT_S=2)
run --now > "$tmp/out" 2>&1 || { cat "$tmp/out"; fail "попытка со сроком не прошла"; }
[[ "$(jqs '[.files.buckets[] | select(.result == "fail")] | length')" == 0 ]] || { status; fail "нехватка времени на первой выгрузке не должна быть сбоем"; }
[[ "$(jqs '[.files.buckets[] | select(.result == "pending")] | length')" -ge 1 && "$(jqs '[.files.buckets[].last_error] | map(select(. != null)) | length')" == 0 ]] \
  || { status; fail "бакеты, до которых не дошли, должны быть pending без ошибки"; }
extra=(-e TIMEOUT_COPY_BUCKET=erp-public)
in_box 'rm -rf /t/state/files'
run --now > "$tmp/out" 2>&1 || true
[[ "$(jqs '.files.buckets["erp-public"].result')" == pending ]] || { status; fail "срок rclone (max-duration) на первой выгрузке — pending, не fail"; }
extra=()
run --now > "$tmp/out" 2>&1 || { cat "$tmp/out"; fail "довыгрузка не прошла"; }
[[ "$(jqs .files.result)" == ok && "$(jqs '.files.last_success_at')" =~ Z$ ]] || { status; fail "после довыгрузки: ok и время полной копии"; }

# 8. Места на Диске мало: файлы пропущены с причиной quota, архив WAL не страдает.
in_box 'rm -rf /t/state/files /t/state/files_last_success /t/drive/files; echo wal2 > /t/src/pg17/wal_005/000000010000000000000005.zst'
extra=(-e FAKE_ABOUT_FREE=10)
run --now > "$tmp/out" 2>&1 || { cat "$tmp/out"; fail "архив при нехватке места под файлы не прошёл"; }
[[ "$(jqs .result)" == ok && -s "$w/drive/pg17/wal_005/000000010000000000000005.zst" ]] || { status; fail "архив WAL пострадал от нехватки места под файлы"; }
[[ "$(jqs '.files.buckets["eds-private"].last_error_reason')" == quota && ! -d "$w/drive/files" ]] || { status; fail "файлы при нехватке места: пропуск с причиной quota"; }
extra=()
run --now > "$tmp/out" 2>&1 || fail "копия после освобождения места"
[[ "$(jqs .files.result)" == ok ]] || { status; fail "после освобождения места файлы копируются"; }

# 9. Отметки восстанавливаются из настоящего status.json: WAL — верхний last_success_at, файлы — последний полный проход (не бакетный).
jq -c '.last_success_at = "2026-01-01T01:01:01Z" | .files.last_success_at = "2026-02-02T02:02:02Z" | .files.buckets[].last_success_at = "2026-03-03T03:03:03Z"' \
  "$w/status/status.json" > "$w/status/real.json"
in_box 'chmod a+r /t/status/real.json'
docker run --rm -v "$w:/t" -v "$script:/offsite/offsite-sync.sh:ro" -e TZ=UTC -e OFFSITE_LIB=1 -e OFFSITE_STATE_DIR=/t/rec -e OFFSITE_STATUS_DST=/t/status/real.json \
  --entrypoint sh "$image" -c '
set -e
mkdir -p /t/rec; rm -f /t/rec/*
. /offsite/offsite-sync.sh
recover_marker; recover_files_marker
[ "$(cat /t/rec/last_success)" = "$(date -u -d "2026-01-01 01:01:01" +%s)" ] || { echo "отметка архива восстановлена не из верхнего поля: $(cat /t/rec/last_success)"; exit 1; }
[ "$(cat /t/rec/files_last_success)" = "$(date -u -d "2026-02-02 02:02:02" +%s)" ] || { echo "отметка файлов восстановлена не из files.last_success_at"; exit 1; }' > "$tmp/out" 2>&1 || { cat "$tmp/out"; fail "восстановление отметок из status.json"; }

# 10. Блокировка: попытка до ~12,5 ч не считается зависшей; старше — снимается.
docker run --rm -v "$w:/t" -v "$script:/offsite/offsite-sync.sh:ro" -e TZ=UTC -e OFFSITE_LIB=1 -e OFFSITE_STATE_DIR=/t/lk -e OFFSITE_STATUS_DST=/t/status/lk.json \
  -e OFFSITE_CONFIG_SRC=/t/nocfg -e OFFSITE_GDRIVE_SA_FILE=/t/nokey.json --entrypoint sh "$image" -c '
set -e
. /offsite/offsite-sync.sh
age() { touch -d "$(date -u -d "@$(( $(date -u +%s) - $1 ))" "+%Y-%m-%d %H:%M:%S")" "$STATE/lock"; }
mkdir -p "$STATE/lock"; age $((11 * 3600))
rc=0; locked_run > /dev/null || rc=$?
[ "$rc" = 75 ] || { echo "попытка идёт 11 ч (архив + файлы до 12 ч): блокировка не должна сниматься, rc=$rc"; exit 1; }
age $((13 * 3600)); rc=0; locked_run > /dev/null || rc=$?
[ "$rc" != 75 ] || { echo "блокировка старше 12,5 ч должна сниматься"; exit 1; }' > "$tmp/out" 2>&1 || { cat "$tmp/out"; fail "блокировка длинной попытки"; }

# 11. --estimate: объём источника без копирования.
in_box 'rm -rf /t/drive/files'
run --estimate > "$tmp/out" 2>&1 || { cat "$tmp/out"; fail "--estimate"; }
grep -qE '^eds-private: [0-9]+ файлов, [0-9]+ байт$' "$tmp/out" && grep -qE '^всего: [0-9]+ файлов, [0-9]+ байт$' "$tmp/out" || { cat "$tmp/out"; fail "--estimate: формат"; }
[[ ! -d "$w/drive/files" ]] || fail "--estimate ничего копировать не должен"

# 12. OFFSITE_FILE_BUCKETS= — этап отключён.
extra=(-e OFFSITE_FILE_BUCKETS=)
run --now > "$tmp/out" 2>&1 || { cat "$tmp/out"; fail "копия без файлов не прошла"; }
[[ "$(jqs .files.configured)" == false && ! -d "$w/drive/files" ]] || { status; fail "пустой OFFSITE_FILE_BUCKETS должен отключать копию файлов"; }
extra=()

# 13. Healthcheck: красный, только если копия уже работала и встала на 26 часов; ни разу не удавшаяся — зелёная.
docker run --rm -v "$w:/t" -v "$script:/offsite/offsite-sync.sh:ro" -e TZ=UTC -e OFFSITE_LIB=1 -e OFFSITE_STATE_DIR=/t/h --entrypoint sh "$image" -c '
set -e
mkdir -p /t/h; rm -f /t/h/*
. /offsite/offsite-sync.sh
t=$(date -u +%s); echo $t > /t/h/heartbeat
(health) || { echo "нет отметок о файлах: должен быть healthy"; exit 1; }
echo $((t - 3600)) > /t/h/files_last_success
(health) || { echo "файлы копировались час назад: healthy"; exit 1; }
echo $((t - 100000)) > /t/h/files_last_success
if out="$(health 2>&1)"; then echo "файлы 27 часов без полной копии: должен быть unhealthy"; exit 1; fi
case "$out" in *"файлы не копировались"*"26 часов"*) ;; *) echo "причина нечитаема: $out"; exit 1 ;; esac
echo $t > /t/h/files_last_success
echo ok > /t/h/last_result; echo $((t - 100000)) > /t/h/last_success
(health) || { echo "архив ok: healthy"; exit 1; }
echo fail > /t/h/last_result
if out="$(health 2>&1)"; then echo "архив не копируется 27 часов: unhealthy"; exit 1; fi
case "$out" in *"архив базы"*) ;; *) echo "причина нечитаема: $out"; exit 1 ;; esac
' > "$tmp/out" 2>&1 || { cat "$tmp/out"; fail "healthcheck"; }

echo "offsite-files-test: ok"
