#!/usr/bin/env bash
# АВАРИЙНЫЙ путь включения внешней копии на Google Drive — ключ на сервере (OPS-GDRIVE; docs/runbooks/offsite-gdrive.md, раздел 1а).
# Основной путь — интерфейс: Admin → Подключения → «Хранилище» → «Внешняя копия бэкапов» (OPS-GDRIVE-2, OPS-YADISK: там же Яндекс
# Диск — рекомендуемый провайдер; для него этот скрипт не нужен). VPS 1, от deploy:
#   /opt/rt/current/infra/deploy/offsite-check.sh
# 1. Проверяет ключ сервисного аккаунта ($RT_SECRETS_DIR/gdrive-sa.json): есть, chmod 600, владелец — текущий пользователь, это ключ
#    сервисного аккаунта Google (печатает только адрес аккаунта — ему владелец даёт доступ к папке; сам ключ не печатается).
# 2. Проверяет OFFSITE_GDRIVE_FOLDER_ID в .env.prod (ID папки, не адрес целиком).
# 3. Пересоздаёт сервис offsite-backup текущего релиза (новые значения .env.prod доходят только так) и сразу копирует (--now).
# 4. Печатает итог (status.json — его же видит строка CRM «Внешняя копия бэкапов») и выходит с его кодом.
# Ничего не меняет в .env.prod и в ключе; при сбое проверок контейнер не трогает.
set -euo pipefail
# shellcheck source=infra/deploy/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

rel="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
key="$RT_SECRETS_DIR/gdrive-sa.json"
problems=0
bad() { printf '✘ %s\n' "$*" >&2; problems=$((problems + 1)); }

require_env_file
if [[ ! -s "$key" ]]; then
  bad "нет ключа $key — положите JSON сервисного аккаунта (runbook offsite-gdrive.md, шаг 4)"
else
  mode="$(stat -c '%a' "$key" 2>/dev/null || stat -f '%Lp' "$key")"
  [[ "$mode" == 600 ]] || bad "$key должен быть chmod 600 (сейчас $mode): chmod 600 $key"
  owner="$(stat -c '%U' "$key" 2>/dev/null || stat -f '%Su' "$key")"
  [[ "$owner" == "$(id -un)" ]] || bad "владелец $key — $owner, а не $(id -un): sudo chown $(id -un): $key"
  dir_mode="$(stat -c '%a' "$RT_SECRETS_DIR" 2>/dev/null || stat -f '%Lp' "$RT_SECRETS_DIR")"
  [[ "$dir_mode" == 700 ]] || bad "$RT_SECRETS_DIR должен быть chmod 700 (сейчас $dir_mode)"
  if grep -qE '"type"[[:space:]]*:[[:space:]]*"service_account"' "$key" && grep -q '"private_key"' "$key"; then
    email="$(sed -n 's/.*"client_email"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$key" | head -n 1)"
    log "ключ сервисного аккаунта: ${email:-адрес не найден} — именно ему нужна роль «Менеджер контента» в папке общего диска"
  else
    bad "$key — не ключ сервисного аккаунта Google (нужен JSON с \"type\": \"service_account\" и private_key)"
  fi
fi
folder="$(env_get OFFSITE_GDRIVE_FOLDER_ID || true)"
if [[ -z "$folder" ]]; then
  bad "в $RT_ENV_FILE пусто OFFSITE_GDRIVE_FOLDER_ID — впишите ID папки (часть адреса после /folders/)"
elif [[ ! "$folder" =~ ^[A-Za-z0-9_-]{10,}$ ]]; then
  bad "OFFSITE_GDRIVE_FOLDER_ID похож не на ID папки: нужен только ID (часть адреса после /folders/, без ?usp=...)"
fi
(( problems == 0 )) || die "исправьте $problems пункт(а) выше и запустите снова; сервис offsite-backup не тронут"

tag="$(state_get current_tag)"
[[ -n "$tag" ]] || die "нет текущего релиза ($RT_STATE/current_tag): сначала деплой"
export RT_IMAGE_TAG="$tag" RT_SECRETS_DIR
log "пересоздаю offsite-backup (релиз $tag) и запускаю копирование; первая выгрузка может идти часы — полоса ограничена"
compose "$rel" up -d --no-deps --force-recreate offsite-backup
sleep 5
rc=0
compose "$rel" exec -T offsite-backup sh /offsite/offsite-sync.sh --now || rc=$?
if [[ "$rc" == 75 ]]; then
  # Демон после пересоздания начал копирование сам: ждём его итога (идёт, пока есть /state/lock).
  log "копирование уже начал сам сервис — жду итога (Ctrl+C не мешает копированию; журнал: docker compose logs -f offsite-backup)"
  while compose "$rel" exec -T offsite-backup test -d /state/lock; do sleep 30; done
  compose "$rel" exec -T offsite-backup cat /state/status.json
  [[ "$(compose "$rel" exec -T offsite-backup cat /state/last_result)" == ok ]] && rc=0 || rc=1
fi
case "$rc" in
  0) log "готово: строка «Внешняя копия бэкапов» в Платформе (Admin → Подключения) станет «В порядке» после ближайшей проверки (до 1 минуты)" ;;
  3) die "сервис считает копию не настроенной (\"reason\" выше): проверьте, что ключ лежит в $RT_SECRETS_DIR и ID папки в $RT_ENV_FILE" ;;
  *) die "копирование не удалось: причина — в \"message\" выше и в docker compose logs offsite-backup (runbook offsite-gdrive.md, «Диагностика»)" ;;
esac
