#!/usr/bin/env bash
# Тест ХРАН-1: копия файловых бакетов за пределы сервера (infra/offsite/offsite-sync.sh, этап файлов). Без Диска и без секретов:
# RustFS и Диск подменены локальными каталогами (бэкенд local закреплённого образа rclone).
#  - файлы уходят в files/<бакет>/ на Диске, лишних бакетов (erp-temp, langfuse, backups) там нет;
#  - повторный запуск ничего не копирует; удалённое у нас на Диске остаётся (copy, а не sync);
#  - сбой одного бакета (нет бакета, сбой копирования) не останавливает остальные, итог по каждому — в status.json без имён файлов;
#  - прежние поля status.json (для строки CRM) на месте; OFFSITE_FILE_BUCKETS= отключает этап;
#  - --estimate печатает объём источника; healthcheck: красный только если копия работала и встала на 26 часов.
# Запуск: bash этот-файл [путь к скрипту] — второй вариант нужен мутационной проверке (скрипт с подменой copy на sync).
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
    -e OFFSITE_FILES_SRC=/t/files/ -e OFFSITE_FILES_DST=/t/drive/files -e OFFSITE_CONFIG_SRC=/t/cfg \
    -e OFFSITE_GDRIVE_SA_FILE=/t/secrets/gdrive-sa.json -e "OFFSITE_GDRIVE_FOLDER_ID=$FOLDER_ID" -e OFFSITE_KEEP_DAYS=14 \
    ${extra[@]+"${extra[@]}"} --entrypoint sh "$image" /offsite/offsite-sync.sh "$@"
}
in_box() { docker run --rm -v "$w:/t" --entrypoint sh "$image" -c "$1; chmod -R a+rwX /t"; }
status() { cat "$w/status/status.json"; }
jqs() { jq -r "$1" "$w/status/status.json"; }
drive_files() { (cd "$w/drive/files" 2>/dev/null && find . -type f | sed 's|^\./||' | sort | tr '\n' ' ') || true; }

# Исходные данные: WAL (одна свежая базовая копия), ключ сервисного аккаунта-заглушка, файлы в бакетах и в бакетах, которые копировать нельзя.
in_box '
set -e
rm -rf /t/src /t/files /t/drive /t/status /t/state /t/secrets /t/cfg; mkdir -p /t/status /t/secrets /t/cfg
s=/t/src/pg17; mkdir -p $s/basebackups_005/base_000000010000000000000004 $s/wal_005
echo data > $s/basebackups_005/base_000000010000000000000004/part_1.tar.zst
echo "{}" > $s/basebackups_005/base_000000010000000000000004_backup_stop_sentinel.json
echo wal > $s/wal_005/000000010000000000000004.zst
for b in eds-private erp-private erp-public client-documents tg-attachments kb-sources erp-temp langfuse backups; do
  mkdir -p /t/files/$b/sub; echo "doc-$b-1" > /t/files/$b/a-$b.pdf; echo "doc-$b-2" > /t/files/$b/sub/секретное-имя-$b.docx
done'
printf '{"type": "service_account", "client_email": "x@example.iam.gserviceaccount.com", "private_key": "%s\\nfake\\n%s\\n"}' "$PEM_BEGIN" "$PEM_END" > "$w/secrets/gdrive-sa.json"

# 1. Первая копия: все шесть бакетов в files/<бакет>/, чужих нет; в журнале оценка объёма до выгрузки.
run --now > "$tmp/out" 2>&1 || { cat "$tmp/out"; fail "первая копия не прошла"; }
for b in $BUCKETS; do
  [[ -s "$w/drive/files/$b/a-$b.pdf" && -s "$w/drive/files/$b/sub/секретное-имя-$b.docx" ]] || fail "бакет $b не скопирован"
  cmp -s "$w/files/$b/a-$b.pdf" "$w/drive/files/$b/a-$b.pdf" || fail "содержимое $b отличается"
done
for b in erp-temp langfuse backups; do [[ ! -e "$w/drive/files/$b" ]] || fail "бакет $b копироваться не должен"; done
[[ -s "$w/drive/pg17/wal_005/000000010000000000000004.zst" ]] || fail "архив WAL не скопирован"
grep -q '"offsite_files_estimate_total"' "$tmp/out" || fail "в журнале нет оценки объёма к первой выгрузке"
jq -es 'map(select(.event == "offsite_files_estimate_total")) | .[0].files == 12' "$tmp/out" >/dev/null || { cat "$tmp/out"; fail "оценка: ожидалось 12 файлов"; }
[[ "$(jqs .files.result)" == ok && "$(jqs .files.files)" == 12 && "$(jqs '.files.buckets | length')" == 6 ]] || { status; fail "итог файлов: ok, 12 файлов, 6 бакетов"; }
[[ "$(jqs '.files.buckets["erp-public"].files')" == 2 && "$(jqs '.files.buckets["erp-public"].bytes')" -gt 0 && "$(jqs '.files.buckets["erp-public"].last_success_at')" =~ Z$ ]] \
  || { status; fail "бакет: файлы, байты, время успеха"; }
[[ "$(jqs '.files.last_success_at')" =~ Z$ && "$(jqs '.files.buckets["erp-public"].last_error')" == null ]] || { status; fail "время полной копии и пустая ошибка"; }
! grep -q "секретное-имя" "$w/status/status.json" || fail "имена файлов попали в status.json"
! grep -rq "$FOLDER_ID" "$w/status" || fail "ID папки попал в status.json"

# 2. Прежние поля status.json (строка CRM) на месте и с прежними типами.
jq -e '.schema == 1 and .provider == "gdrive" and .result == "ok" and .reason == "" and (.attempt_at | test("Z$")) and (.last_success_at | test("Z$"))
  and (.bytes | type == "number") and (.objects | type == "number") and (.base_backups == 1) and (.quota_bytes == 107374182400)
  and .keep_days == 14 and .prefix == "pg17" and has("message") and has("detail") and has("duration_s") and has("speed_bps")
  and has("oldest_base_at") and has("newest_base_at")' "$w/status/status.json" >/dev/null || { status; fail "прежние поля status.json изменились"; }

# 3. Повтор: ничего не копируется заново.
run --now > "$tmp/out" 2>&1 || { cat "$tmp/out"; fail "повтор не прошёл"; }
[[ "$(jqs '[.files.buckets[].copied_files] | add')" == 0 ]] || { status; fail "повтор скопировал файлы заново"; }
grep '"offsite_files_bucket_done"' "$tmp/out" | jq -e '.copied_files == 0' >/dev/null || fail "повтор: copied_files не 0"

# 4. Не удаляет на Диске: файл пропал у нас — на Диске остаётся (copy, не sync); новый файл — приходит.
in_box 'rm /t/files/eds-private/a-eds-private.pdf; echo new > /t/files/erp-public/new.pdf'
run --now > "$tmp/out" 2>&1 || { cat "$tmp/out"; fail "копия после удаления не прошла"; }
[[ -s "$w/drive/files/eds-private/a-eds-private.pdf" ]] || fail "удалённое у нас пропало на Диске (нужен copy, не sync)"
[[ -s "$w/drive/files/erp-public/new.pdf" ]] || fail "новый файл не скопирован"
[[ "$(jqs '.files.buckets["eds-private"].files')" == 2 && "$(jqs '.files.buckets["erp-public"].copied_files')" == 1 ]] || { status; fail "итог после удаления и добавления"; }

# 5. Сбой одного бакета: kb-sources нет в хранилище, копирование erp-private падает — остальные скопированы, итог по каждому в status.json.
in_box 'rm -rf /t/drive/files /t/files/kb-sources /t/state/files /t/state/files_last_success; echo again > /t/files/tg-attachments/more.jpg; echo back > /t/files/eds-private/a-eds-private.pdf'
mkdir -p "$w/bin"
cat > "$w/bin/rclone" <<'WRAP'
#!/bin/sh
if [ "$1" = copy ] && [ -n "${FAIL_COPY_BUCKET:-}" ]; then
  case "$2" in */"$FAIL_COPY_BUCKET") echo "ERROR : injected copy failure for $2/a-secret-name.pdf" >&2; exit 1 ;; esac
fi
exec /usr/local/bin/rclone "$@"
WRAP
chmod +x "$w/bin/rclone"
extra=(-e PATH=/t/bin:/usr/local/bin:/usr/bin:/bin -e FAIL_COPY_BUCKET=erp-private)
rc=0; run --now > "$tmp/out" 2>&1 || rc=$?
[[ "$rc" == 0 ]] || { cat "$tmp/out"; fail "сбой файлов не должен менять код выхода архива (rc=$rc)"; }
for b in eds-private erp-public client-documents tg-attachments; do [[ -s "$w/drive/files/$b/a-$b.pdf" ]] || fail "сбой соседа остановил копию $b"; done
[[ -s "$w/drive/files/tg-attachments/more.jpg" ]] || fail "новый файл tg-attachments не скопирован"
[[ ! -e "$w/drive/files/kb-sources/a-kb-sources.pdf" && ! -e "$w/drive/files/erp-private/a-erp-private.pdf" ]] || fail "сбойные бакеты не должны появляться на Диске"
[[ "$(jqs .files.result)" == partial ]] || { status; fail "итог при сбое двух бакетов из шести: partial"; }
[[ "$(jqs '.files.buckets["kb-sources"].result')" == fail && "$(jqs '.files.buckets["kb-sources"].last_error_reason')" == source ]] || { status; fail "kb-sources: fail/source"; }
[[ "$(jqs '.files.buckets["erp-private"].result')" == fail && "$(jqs '.files.buckets["erp-private"].last_error')" == *"Копирование файлов"* ]] || { status; fail "erp-private: fail с читаемой причиной"; }
[[ "$(jqs '.files.buckets["eds-private"].result')" == ok && "$(jqs '.files.last_success_at')" == null ]] || { status; fail "полной копии не было: last_success_at файлов должен быть null"; }
! grep -q "a-secret-name" "$w/status/status.json" || fail "имя файла из журнала rclone попало в status.json"
[[ "$(jqs .result)" == ok ]] || { status; fail "итог архива WAL при сбое файлов должен остаться ok"; }
# Сбой файлов — повтор через RETRY_MIN, а не через сутки.
docker run --rm -v "$w:/t" -v "$script:/offsite/offsite-sync.sh:ro" -e TZ=UTC -e OFFSITE_LIB=1 -e OFFSITE_STATE_DIR=/t/state -e OFFSITE_RETRY_MIN=30 \
  --entrypoint sh "$image" -c '
set -e
. /offsite/offsite-sync.sh
t=$(date -u +%s)
echo ok > /t/state/last_result; echo $t > /t/state/last_success; echo $((t - 60)) > /t/state/last_attempt
[ "$(if due; then echo due; else echo wait; fi)" = wait ] || { echo "сразу после попытки ждать"; exit 1; }
echo $((t - 1900)) > /t/state/last_attempt
[ "$(if due; then echo due; else echo wait; fi)" = due ] || { echo "файлы не докопированы: повтор через 30 минут"; exit 1; }' > "$tmp/out" 2>&1 || { cat "$tmp/out"; fail "расписание повтора файлов"; }

# 6. Бакеты вернулись — следующая попытка докопирует всё, итог ok и время полной копии заполнено.
in_box 'mkdir -p /t/files/kb-sources; echo k > /t/files/kb-sources/a-kb-sources.pdf'
extra=()
run --now > "$tmp/out" 2>&1 || { cat "$tmp/out"; fail "копия после восстановления не прошла"; }
[[ "$(jqs .files.result)" == ok && "$(jqs '.files.last_success_at')" =~ Z$ && "$(jqs '.files.buckets["kb-sources"].last_error')" == null ]] || { status; fail "после восстановления: ok и время полной копии"; }
[[ -s "$w/drive/files/erp-private/a-erp-private.pdf" && -s "$w/drive/files/kb-sources/a-kb-sources.pdf" ]] || fail "сбойные бакеты не докопированы"

# 7. --estimate: объём источника по бакетам без копирования.
in_box 'rm -rf /t/drive/files'
run --estimate > "$tmp/out" 2>&1 || { cat "$tmp/out"; fail "--estimate"; }
grep -qE '^eds-private: [0-9]+ файлов, [0-9]+ байт$' "$tmp/out" && grep -qE '^всего: [0-9]+ файлов, [0-9]+ байт$' "$tmp/out" || { cat "$tmp/out"; fail "--estimate: формат"; }
[[ ! -d "$w/drive/files" ]] || fail "--estimate ничего копировать не должен"

# 8. OFFSITE_FILE_BUCKETS= — этап отключён: архив копируется как раньше, раздел files — configured:false.
extra=(-e OFFSITE_FILE_BUCKETS=)
run --now > "$tmp/out" 2>&1 || { cat "$tmp/out"; fail "копия без файлов не прошла"; }
[[ "$(jqs .files.configured)" == false && ! -d "$w/drive/files" ]] || { status; fail "пустой OFFSITE_FILE_BUCKETS должен отключать копию файлов"; }
extra=()

# 9. Healthcheck: красный, только если копия уже работала и встала на 26 часов; ни разу не удавшаяся — зелёная.
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
