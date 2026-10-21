#!/usr/bin/env bash
# Общие функции скриптов деплоя (source, не запускать). Раскладка на VPS 1 (docs/runbooks/deploy.md):
#   /opt/rt/.env.prod            переменные прода (chmod 600), только на сервере
#   /opt/rt/releases/<тег>/      infra/ и apps/crm/infra/casbin выбранной версии (кладёт deploy.yml)
#   /opt/rt/state/               current_tag, previous_tag, predeploy/ (дампы перед миграциями)
# shellcheck shell=bash

RT_ROOT="${RT_ROOT:-/opt/rt}"
RT_ENV_FILE="${RT_ENV_FILE:-$RT_ROOT/.env.prod}"
RT_RELEASES="${RT_RELEASES:-$RT_ROOT/releases}"
RT_STATE="${RT_STATE:-$RT_ROOT/state}"

log() { printf '▸ %s\n' "$*"; }
die() { printf '✘ %s\n' "$*" >&2; exit 1; }

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

release_dir() { echo "$RT_RELEASES/$1"; }

state_get() { cat "$RT_STATE/$1" 2>/dev/null || true; }
state_set() { mkdir -p "$RT_STATE"; printf '%s\n' "$2" > "$RT_STATE/$1"; }

# Удаляет образы rt-* всех тегов, кроме перечисленных (текущий и предыдущий), и каталоги релизов старше пяти.
cleanup_old() {
  local keep_a="$1" keep_b="${2:-}" img
  while read -r img; do
    [[ "$img" == *":$keep_a" || ( -n "$keep_b" && "$img" == *":$keep_b" ) ]] && continue
    docker rmi "$img" >/dev/null 2>&1 || true
  done < <(docker images --format '{{.Repository}}:{{.Tag}}' | grep -E '/rt-(crm-backend|crm-frontend|erp-backend|erp-frontend|cabinet|litellm|platform-bff|platform-web):' || true)
  # shellcheck disable=SC2012
  ls -1t "$RT_RELEASES" 2>/dev/null | tail -n +6 | while read -r old; do
    [[ "$old" == "$keep_a" || "$old" == "$keep_b" ]] || rm -rf "${RT_RELEASES:?}/$old"
  done
}
