#!/usr/bin/env bash
# Общие функции скриптов деплоя (source, не запускать). Раскладка на VPS 1 (docs/runbooks/deploy.md):
#   /opt/rt/.env.prod            переменные прода (chmod 600), только на сервере
#   /opt/rt/releases/<тег>/      infra/ и apps/crm/infra/casbin выбранной версии (кладёт deploy.yml)
#   /opt/rt/state/               current_tag, previous_tag, predeploy/ (дампы перед миграциями)
#   /opt/rt/secrets/             секреты владельца вне .env.prod (gdrive-sa.json — ключ внешней копии), chmod 700
# shellcheck shell=bash

RT_ROOT="${RT_ROOT:-/opt/rt}"
RT_ENV_FILE="${RT_ENV_FILE:-$RT_ROOT/.env.prod}"
RT_RELEASES="${RT_RELEASES:-$RT_ROOT/releases}"
RT_STATE="${RT_STATE:-$RT_ROOT/state}"
# Секреты, которые владелец кладёт на сервер сам (ключ сервисного аккаунта Google для offsite-backup, OPS-GDRIVE): chmod 700, владелец deploy.
RT_SECRETS_DIR="${RT_SECRETS_DIR:-$RT_ROOT/secrets}"

log() { printf '▸ %s\n' "$*"; }
die() { printf '✘ %s\n' "$*" >&2; exit 1; }

# Повтор сетевой команды при плавающих сбоях (ghcr.io: «TLS handshake timeout» при docker login / compose pull).
# retry <метка> <команда...>: до RT_RETRY_MAX (5) попыток с паузами RT_RETRY_DELAY (5) с, затем вдвое больше: 5, 10, 20, 40 с.
# Повтор — при любом коде выхода ≠ 0; после последней неудачной попытки возвращается её код (вызывающий решает, что дальше —
# прежнее поведение). В журнал — метка, номер попытки и код; аргументы команды не печатаются (в них могут быть секреты).
# stdin команде не пробрасывается повторно: для login передавайте источник внутри самой команды (функция с printf | ssh).
retry() {
  local label="$1"; shift
  local max="${RT_RETRY_MAX:-5}" delay="${RT_RETRY_DELAY:-5}" n=1 rc=0
  while true; do
    if "$@"; then
      (( n == 1 )) || log "$label: удалось с попытки $n из $max"
      return 0
    else
      rc=$?
    fi
    if (( n >= max )); then
      log "$label: попытка $n из $max не удалась (код $rc), повторов больше нет" >&2
      return "$rc"
    fi
    log "$label: попытка $n из $max не удалась (код $rc), повтор через $delay с" >&2
    sleep "$delay"
    delay=$((delay * 2)); n=$((n + 1))
  done
}

# Значение переменной из env-файла (без source: в значениях могут быть спецсимволы).
env_get() { grep -E "^$1=" "$RT_ENV_FILE" | tail -1 | cut -d= -f2-; }

require_env_file() {
  [[ -f "$RT_ENV_FILE" ]] || die "нет $RT_ENV_FILE — создайте: infra/deploy/make-env-prod.sh init"
  local mode
  mode="$(stat -c '%a' "$RT_ENV_FILE" 2>/dev/null || stat -f '%Lp' "$RT_ENV_FILE")"
  [[ "$mode" == 600 ]] || die "$RT_ENV_FILE должен быть chmod 600 (сейчас $mode)"
  if grep -qE '^[A-Z0-9_]+=.*(CHANGE_ME|192\.0\.2\.)' "$RT_ENV_FILE"; then
    grep -nE '^[A-Z0-9_]+=.*(CHANGE_ME|192\.0\.2\.)' "$RT_ENV_FILE" | cut -d= -f1 | sed 's/^/    не заполнено: /' >&2
    die "в $RT_ENV_FILE остались CHANGE_ME или адреса-заглушки 192.0.2.x"
  fi
}

# Обязательная переменная env-файла: непустое значение, иначе понятная ошибка (а не «set in .env» из compose посреди pull).
# require_env_var <ИМЯ> <подсказка-как-добавить>
require_env_var() {
  local name="$1" hint="$2" value
  value="$(env_get "$name" || true)"
  [[ -n "$value" ]] || die "в $RT_ENV_FILE нет $name (или значение пусто): $hint"
}

# compose <каталог-релиза> <аргументы...>; тег образов — из окружения (RT_IMAGE_TAG), профили — из RT_PROFILES.
compose() {
  local rel="$1"; shift
  local profiles=() p
  IFS=',' read -ra ps <<<"$(env_get RT_PROFILES)"
  for p in "${ps[@]:-}"; do [[ -n "$p" ]] && profiles+=(--profile "$p"); done
  docker compose -f "$rel/infra/compose/base.yml" -f "$rel/infra/compose/prod.yml" \
    --env-file "$RT_ENV_FILE" ${profiles[@]+"${profiles[@]}"} "$@"
}

# Поднимает стек релиза так, чтобы сбой Платформы (INF-P1-0) не ронял остальное. Caddy ждёт platform-* по service_started
# (base.yml), но если контейнер Платформы не стартует вовсе (битая команда/образ — ошибка exec), `up -d` падает до
# запуска Caddy и все четыре домена остаются без входа. Поэтому: сначала всё, кроме Платформы (--scale …=0 — Caddy
# стартует, upstream Платформы пока не резолвится -> 502 только на её домене), затем Платформа отдельно, и её сбой —
# предупреждение, а не отказ деплоя/отката; итог по Платформе даёт smoke (четвёртый домен). Релиз до Платформы
# (откат на старый тег) — обычный `up -d`.
up_stack() {
  local rel="$1" services
  services="$(compose "$rel" config --services)"
  if grep -qx platform-bff <<<"$services"; then
    compose "$rel" up -d --remove-orphans --scale platform-bff=0 --scale platform-web=0
    compose "$rel" up -d --no-deps platform-bff platform-web \
      || log "внимание: Платформа не поднялась (docker compose logs platform-bff); CRM, ERP и Cabinet подняты, её домен отдаёт 502"
  else
    compose "$rel" up -d --remove-orphans
  fi
}

# Ждёт, пока сервис compose станет healthy (до <секунд>); для сервисов без домена, которые smoke не видит (EDS: маршрута наружу нет).
# wait_healthy <каталог-релиза> <сервис> [секунд]
wait_healthy() {
  local rel="$1" service="$2" limit="${3:-120}" waited=0 state=""
  while (( waited < limit )); do
    state="$(compose "$rel" ps --format '{{.Health}}' "$service" 2>/dev/null | head -n1 || true)"
    [[ "$state" == healthy ]] && return 0
    sleep 3; waited=$((waited + 3))
  done
  return 1
}

release_dir() { echo "$RT_RELEASES/$1"; }

state_get() { cat "$RT_STATE/$1" 2>/dev/null || true; }

# Дата выкладки релиза (W-REL, версия «Платформа ГГГГ.ММ.ДД»): пишется в каталог релиза при первой выкладке и дальше не
# меняется — повтор деплоя и откат на этот релиз показывают ту же версию. release_date <каталог-релиза>
release_date() {
  local file="$1/.released_at"
  [[ -s "$file" ]] || date -u +%Y-%m-%d > "$file" 2>/dev/null || true
  cat "$file" 2>/dev/null || true
}
state_set() { mkdir -p "$RT_STATE"; printf '%s\n' "$2" > "$RT_STATE/$1"; }

# Удаляет образы rt-* всех тегов, кроме перечисленных (текущий и предыдущий), и каталоги релизов старше пяти.
cleanup_old() {
  local keep_a="$1" keep_b="${2:-}" img
  while read -r img; do
    [[ "$img" == *":$keep_a" || ( -n "$keep_b" && "$img" == *":$keep_b" ) ]] && continue
    docker rmi "$img" >/dev/null 2>&1 || true
  done < <(docker images --format '{{.Repository}}:{{.Tag}}' | grep -E '/rt-(crm-backend|crm-frontend|erp-backend|erp-frontend|cabinet|litellm|platform-bff|platform-web|eds):' || true)
  # shellcheck disable=SC2012
  ls -1t "$RT_RELEASES" 2>/dev/null | tail -n +6 | while read -r old; do
    [[ "$old" == "$keep_a" || "$old" == "$keep_b" ]] || rm -rf "${RT_RELEASES:?}/$old"
  done
}
