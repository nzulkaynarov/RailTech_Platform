#!/usr/bin/env bash
# Автовыкладка VPS 1 по таймеру сервера (ВЫКЛ-3, DECISIONS 2026-11-28). Запуск: systemd-таймер раз в 10 минут от пользователя deploy
# (infra/deploy/systemd/, установка - docs/runbooks/deploy.md). Расписание GitHub опаздывает на 6-9 часов, поэтому часы - серверные.
# За один запуск (тик):
#   1. замок state/deploy.lock (тот же берёт ручной deploy.yml: гонки нет); занят - тик пустой;
#   2. state/auto-deploy.paused - пауза, ничего не делаем;
#   3. новейший коммит main с зелёной «CI ok» И статусом коммита `stand-ok` = success (его ставит архитектор через scripts/stand-ok.sh после
#      приёмки ровно этого sha на тестовом стенде; «на прод ничего не идёт, пока не проверено на стенде»; нет статуса - тик пишет
#      «ждёт проверки на стенде» и ничего не делает). GitHub API без токена, ETag-кэш, отступление при сбоях;
#   4. пропуск: равен current_tag, в failed_tags, старше выложенного или расходится с ним;
#   5. образы sha целиком в GHCR (все образы из AUTO_DEPLOY_IMAGES; их собирает .github/workflows/images.yml) - иначе ждём;
#   6. часы: ночное окно 00:45-05:30 Ташкента - выкладка; днём - daytime-decision.sh (30 минут тишины в Платформе, иначе баннер за 15 минут);
#   7. релиз (infra/ этого sha) скачивается тарболом GitHub, проверяется, что это коммит main; deploy.sh (дамп, миграции, up, smoke);
#      сбой после переключения - rollback.sh и sha в failed_tags; три сбоя до переключения - sha в failed_tags; баннер снимается всегда.
# Журнал: state/auto-deploy.log (одна JSON-строка на тик: ts, sha, decision, result, duration_s), состояние: state/auto-deploy.status.json.
# Токен не нужен, пока репозиторий и пакеты публичные; для приватного - файл $AUTO_DEPLOY_ENV (GITHUB_TOKEN, GHCR_USER, GHCR_TOKEN), chmod 600.
# Файл читается как source и содержит только присваивания. Скрипт можно подключить через source (тесты переопределяют сетевые функции).
# shellcheck shell=bash
set -uo pipefail

AD_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=infra/deploy/lib.sh
source "$AD_HERE/lib.sh"

AD_REPO="${AUTO_DEPLOY_REPO:-nzulkaynarov/RailTech_Platform}"
AD_IMAGES="${AUTO_DEPLOY_IMAGES:-rt-crm-backend rt-erp-backend rt-cabinet rt-litellm rt-platform-bff rt-platform-web rt-eds}"
AD_ENV="${AUTO_DEPLOY_ENV:-$RT_ROOT/auto-deploy.env}"
AD_CACHE="${AUTO_DEPLOY_CACHE:-$RT_STATE/auto-deploy.cache}"
AD_LOG="$RT_STATE/auto-deploy.log"
AD_MAX_ATTEMPTS="${AUTO_DEPLOY_MAX_ATTEMPTS:-3}"
AD_SCAN_LIMIT=8   # сколько коммитов без кэша проверять за тик (лимит API без токена - 60 запросов в час)

AD_SHA="-"; AD_DECISION="-"; AD_RESULT="-"; AD_T0=0; CAND=""; REL=""

now_epoch() { echo "${AD_NOW:-$(date +%s)}"; }

# ---------- журнал и статус ----------
rotate_log() {
  local size
  size="$(stat -c %s "$AD_LOG" 2>/dev/null || echo 0)"
  [[ "$size" -lt 524288 ]] && return 0
  rm -f "$AD_LOG.3"; [[ -f "$AD_LOG.2" ]] && mv -f "$AD_LOG.2" "$AD_LOG.3"
  [[ -f "$AD_LOG.1" ]] && mv -f "$AD_LOG.1" "$AD_LOG.2"
  mv -f "$AD_LOG" "$AD_LOG.1"
}

journal() {
  local now ts
  now="$(now_epoch)"; ts="$(date -u -d "@$now" +%Y-%m-%dT%H:%M:%SZ)"
  mkdir -p "$RT_STATE"; rotate_log
  printf '{"ts":"%s","sha":"%s","decision":"%s","result":"%s","duration_s":%s}\n' \
    "$ts" "$AD_SHA" "$AD_DECISION" "$AD_RESULT" "$((now - AD_T0))" >> "$AD_LOG"
  local paused=false tmp="$RT_STATE/.auto-deploy.status.$$"
  [[ -e "$RT_STATE/auto-deploy.paused" ]] && paused=true
  printf '{"ts":"%s","paused":%s,"current_tag":"%s","previous_tag":"%s","last_sha":"%s","last_decision":"%s","last_result":"%s","last_deploy_ts":"%s"}\n' \
    "$ts" "$paused" "$(state_get current_tag | tr -d '[:space:]')" "$(state_get previous_tag | tr -d '[:space:]')" \
    "$AD_SHA" "$AD_DECISION" "$AD_RESULT" "$(state_get auto-deploy.last_deploy | tr -d '[:space:]')" > "$tmp" && mv -f "$tmp" "$RT_STATE/auto-deploy.status.json"
}

# ---------- сеть (тесты переопределяют) ----------
# GitHub API: api_get <путь-внутри-репозитория> - тело в stdout, код 0 при успехе. Условные запросы (ETag) не тратят лимит.
api_get() {
  local path="$1" key body etagf hdr code etag authf=""
  key="$(printf '%s' "$path" | sha256sum | cut -c1-24)"
  mkdir -p "$AD_CACHE"
  body="$AD_CACHE/$key.body"; etagf="$AD_CACHE/$key.etag"; hdr="$(mktemp)"
  local args=(-sS --max-time 30 -D "$hdr" -o "$body.new" -w '%{http_code}' -H 'Accept: application/vnd.github+json' -H 'X-GitHub-Api-Version: 2022-11-28')
  if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    authf="$(mktemp)"; chmod 600 "$authf"; printf 'Authorization: Bearer %s\n' "$GITHUB_TOKEN" > "$authf"; args+=(-H "@$authf")
  fi
  [[ -s "$etagf" && -s "$body" ]] && args+=(-H "If-None-Match: $(cat "$etagf")")
  code="$(curl "${args[@]}" "https://api.github.com/repos/$AD_REPO/$path" 2>/dev/null)" || code=000
  etag="$(grep -i '^etag:' "$hdr" | head -n1 | sed 's/^[^:]*: *//' | tr -d '\r')"
  rm -f "$hdr" ${authf:+"$authf"}
  case "$code" in
    200) mv -f "$body.new" "$body"; if [[ -n "$etag" ]]; then printf '%s' "$etag" > "$etagf"; else rm -f "$etagf"; fi; cat "$body" ;;
    304) rm -f "$body.new"; cat "$body" ;;
    *) rm -f "$body.new"; echo "api $path: HTTP $code" >&2; return 1 ;;
  esac
}

# Все образы sha на месте в GHCR (HEAD манифеста каждого; анонимно, для приватных - GHCR_USER и GHCR_TOKEN).
ghcr_images_complete() {
  local sha="$1" owner img scopes=() tok code auth=()
  owner="$(tr '[:upper:]' '[:lower:]' <<<"${AD_REPO%%/*}")"
  for img in $AD_IMAGES; do scopes+=(--data-urlencode "scope=repository:$owner/$img:pull"); done
  [[ -n "${GHCR_USER:-}" && -n "${GHCR_TOKEN:-}" ]] && auth=(-u "$GHCR_USER:$GHCR_TOKEN")
  tok="$(curl -sS --max-time 20 -G "${auth[@]}" --data-urlencode "service=ghcr.io" "${scopes[@]}" https://ghcr.io/token 2>/dev/null \
    | python3 -I -c 'import sys,json; print(json.load(sys.stdin).get("token",""))' 2>/dev/null)" || tok=""
  [[ -n "$tok" ]] || { echo "ghcr: нет токена доступа" >&2; return 2; }
  for img in $AD_IMAGES; do
    code="$(curl -sS -I --max-time 20 -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $tok" \
      -H 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json, application/vnd.docker.distribution.manifest.list.v2+json' \
      "https://ghcr.io/v2/$owner/$img/manifests/$sha" 2>/dev/null)" || code=000
    case "$code" in
      200) ;;
      404) echo "ghcr: нет образа $img:$sha" >&2; return 1 ;;
      *) echo "ghcr: $img:$sha - HTTP $code" >&2; return 2 ;;
    esac
  done
  return 0
}

# Кладёт infra/ этого sha в $RT_RELEASES/<sha>; печатает ничего, путь - в REL. Тарбол GitHub: sha обязан быть в имени каталога.
fetch_release() {
  local sha="$1" work src top
  REL="$RT_RELEASES/$sha"
  [[ -f "$REL/infra/deploy/deploy.sh" ]] && return 0
  mkdir -p "$RT_RELEASES"
  work="$(mktemp -d "$RT_RELEASES/.fetch.XXXXXX")" || return 1
  src="$work/src.tgz"
  local args=(-fsSL --max-time 600 -o "$src")
  local authf=""
  if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    authf="$(mktemp)"; chmod 600 "$authf"; printf 'Authorization: Bearer %s\n' "$GITHUB_TOKEN" > "$authf"; args+=(-H "@$authf")
  fi
  curl "${args[@]}" "https://api.github.com/repos/$AD_REPO/tarball/$sha" 2>/dev/null; local rc=$?
  [[ -z "$authf" ]] || rm -f "$authf"
  if [[ $rc -ne 0 ]]; then rm -rf "$work"; echo "tarball $sha: curl $rc" >&2; return 1; fi
  top="$(tar -tzf "$src" 2>/dev/null | head -n1 | cut -d/ -f1)"
  if [[ -z "$top" || "$top" != *"-${sha:0:7}" ]]; then rm -rf "$work"; echo "tarball $sha: каталог '$top' не соответствует коммиту" >&2; return 1; fi
  mkdir -p "$work/x"
  tar -xzf "$src" -C "$work/x" --strip-components=1 --wildcards \
    "$top/infra/*" "$top/apps/crm/infra/casbin/*" "$top/packages/contracts/mcp-tools.json" "$top/scripts/maintenance-notice.sh" 2>/dev/null
  if [[ ! -f "$work/x/infra/deploy/deploy.sh" ]]; then rm -rf "$work"; echo "tarball $sha: нет infra/deploy/deploy.sh" >&2; return 1; fi
  rm -rf "$REL"; mv "$work/x" "$REL"; rm -rf "$work"
  return 0
}

# ---------- действия на сервере (тесты переопределяют) ----------
activity_count() { bash "$AD_HERE/activity-check.sh"; }
run_deploy() { bash "$REL/infra/deploy/deploy.sh" "$1" >"$RT_STATE/auto-deploy.deploy.log" 2>&1; }
run_rollback() { bash "$REL/infra/deploy/rollback.sh" >>"$RT_STATE/auto-deploy.deploy.log" 2>&1; }
notice_script() { echo "${AD_NOTICE_SCRIPT:-$AD_HERE/../../scripts/maintenance-notice.sh}"; }
banner_set() { MAINTENANCE_DIR="$RT_MAINTENANCE_DIR" bash "$(notice_script)" set "$1" 20 planned >/dev/null; }
banner_clear() { rm -f "$RT_MAINTENANCE_DIR/maintenance.json" 2>/dev/null || true; }

# ---------- разбор данных ----------
# stdout: sha коммитов main, новые сверху
commit_shas() { python3 -I -c 'import sys,json
for c in json.load(sys.stdin): print(c["sha"])' 2>/dev/null; }
# stdin: check-runs «CI ok»; печатает true, если самый свежий прогон completed/success
ci_green() { python3 -I -c 'import sys,json
r=sorted(json.load(sys.stdin).get("check_runs",[]),key=lambda x:x.get("started_at") or "")
print("true" if r and r[-1].get("status")=="completed" and r[-1].get("conclusion")=="success" else "false")' 2>/dev/null || echo false; }
compare_status() { python3 -I -c 'import sys,json; print(json.load(sys.stdin).get("status",""))' 2>/dev/null; }
# stdin: statuses коммита (новые сверху); true, если у самого свежего статуса контекста stand-ok состояние success
stand_ok() { python3 -I -c 'import sys,json
r=[x for x in json.load(sys.stdin) if x.get("context")=="stand-ok"]
r.sort(key=lambda x:x.get("created_at") or "")
print("true" if r and r[-1].get("state")=="success" else "false")' 2>/dev/null || echo false; }
# stdin: maintenance.json; печатает «начало_epoch конец_epoch» или «- -»
banner_window() { python3 -I -c 'import sys,json,datetime
try:
    d=json.load(sys.stdin); s=int(datetime.datetime.fromisoformat(d["starts_at"]).timestamp()); m=int(d.get("minutes",20))
    print(s, s+m*60)
except Exception:
    print("- -")'; }

backoff_active() {
  local f="$RT_STATE/auto-deploy.backoff" n until
  [[ -f "$f" ]] || return 1
  read -r n until < "$f" || return 1
  [[ "${until:-0}" -gt "$(now_epoch)" ]]
}
backoff_fail() {
  local f="$RT_STATE/auto-deploy.backoff" n=0 until delay
  [[ -f "$f" ]] && read -r n until < "$f"
  n=$(( ${n:-0} + 1 )); delay=$(( 300 * (1 << (n > 4 ? 4 : n)) )); [[ $delay -gt 3600 ]] && delay=3600
  printf '%s %s\n' "$n" "$(( $(now_epoch) + delay ))" > "$f"
}

# Кандидат: новейший коммит main с зелёной «CI ok» и статусом stand-ok; дойдя до current_tag, возвращает его (новее годного нет). 0 - есть CAND
# (пусто - нет годного), 1 - сбой API. WAIT_STAND - новейший коммит с зелёной «CI ok», но без stand-ok (ждёт проверки на стенде).
find_candidate() {
  local cur="$1" list c json checked=0
  CAND=""; WAIT_STAND=""
  list="$(api_get "commits?sha=main&per_page=30" | commit_shas)" && [[ -n "$list" ]] || return 1
  for c in $list; do
    if [[ "$c" == "$cur" ]]; then CAND="$cur"; return 0; fi
    if [[ ! -f "$AD_CACHE/green.$c" ]]; then
      (( checked >= AD_SCAN_LIMIT )) && break
      checked=$((checked + 1))
      json="$(api_get "commits/$c/check-runs?check_name=CI%20ok&filter=latest&per_page=100")" || return 1
      if [[ "$(ci_green <<<"$json")" == true ]]; then mkdir -p "$AD_CACHE"; : > "$AD_CACHE/green.$c"; else continue; fi
    fi
    if [[ ! -f "$AD_CACHE/stand.$c" ]]; then
      json="$(api_get "commits/$c/statuses?per_page=100")" || return 1
      if [[ "$(stand_ok <<<"$json")" == true ]]; then mkdir -p "$AD_CACHE"; : > "$AD_CACHE/stand.$c"
      else [[ -n "$WAIT_STAND" ]] || WAIT_STAND="$c"; continue; fi
    fi
    CAND="$c"; return 0
  done
  return 0
}

attempts_get() {
  local s="" n=0
  [[ -f "$RT_STATE/auto-deploy.attempts" ]] && read -r s n < "$RT_STATE/auto-deploy.attempts"
  if [[ "$s" == "$1" ]]; then echo "${n:-0}"; else echo 0; fi
}
attempts_set() { printf '%s %s\n' "$1" "$2" > "$RT_STATE/auto-deploy.attempts"; }

# ---------- один тик ----------
run_tick() {
  local cur cand st phase now activity=0 banner=- banner_end=- bw decision at
  now="$(now_epoch)"
  if [[ -e "$RT_STATE/auto-deploy.paused" ]]; then AD_DECISION=paused; AD_RESULT=idle; return 0; fi
  if backoff_active; then AD_DECISION="api-backoff"; AD_RESULT=idle; return 0; fi
  cur="$(state_get current_tag | tr -d '[:space:]')"
  if ! find_candidate "$cur"; then backoff_fail; AD_DECISION="api-unavailable"; AD_RESULT=idle; return 0; fi
  rm -f "$RT_STATE/auto-deploy.backoff"
  cand="$CAND"
  if [[ -n "$WAIT_STAND" && ( -z "$cand" || "$cand" == "$cur" ) ]]; then
    # есть более новый зелёный sha, но архитектор ещё не принял его на стенде: на прод ничего не идёт
    AD_SHA="$WAIT_STAND"; AD_DECISION="wait-stand"; AD_RESULT="ждёт проверки на стенде"; return 0
  fi
  if [[ -z "$cand" ]]; then AD_DECISION="no-green-main"; AD_RESULT=idle; return 0; fi
  AD_SHA="$cand"
  if [[ "$cand" == "$cur" ]]; then
    AD_DECISION="up-to-date"; AD_RESULT=idle
    # выкладывать нечего, а баннер давно отыграл (откат, ручная выкладка) - не оставляем висеть
    if [[ -f "$RT_MAINTENANCE_DIR/maintenance.json" ]]; then
      bw="$(banner_window < "$RT_MAINTENANCE_DIR/maintenance.json")"; read -r banner banner_end <<<"$bw"
      [[ "$banner" == - || "$now" -gt "$banner_end" ]] && banner_clear
    fi
    return 0
  fi
  if grep -qxF "$cand" "$RT_STATE/failed_tags" 2>/dev/null; then AD_DECISION="skip-failed"; AD_RESULT=idle; return 0; fi
  if [[ -n "$cur" ]]; then
    st="$(api_get "compare/$cur...$cand?per_page=1" | compare_status)" || { backoff_fail; AD_DECISION="api-unavailable"; AD_RESULT=idle; return 0; }
    case "$st" in
      ahead) ;;
      behind|identical) AD_DECISION="skip-older"; AD_RESULT=idle; return 0 ;;
      *) AD_DECISION="skip-diverged"; AD_RESULT=idle; return 0 ;;
    esac
  fi
  ghcr_images_complete "$cand"; case $? in
    0) ;;
    1) AD_DECISION="wait-images"; AD_RESULT=idle; return 0 ;;
    *) AD_DECISION="ghcr-unavailable"; AD_RESULT=idle; return 0 ;;
  esac

  phase="$(bash "$AD_HERE/clock-decision.sh" phase "$now")"
  # Баннер учитывается в любой фазе (ночью выкладка не ждёт тишины, но уважает уже стоящее предупреждение); активность - только днём.
  if [[ -f "$RT_MAINTENANCE_DIR/maintenance.json" ]]; then
    bw="$(banner_window < "$RT_MAINTENANCE_DIR/maintenance.json")"; read -r banner banner_end <<<"$bw"
  fi
  if [[ "$phase" == day ]] && { [[ "$banner" == - ]] || [[ "$now" -gt "$banner_end" ]]; }; then
    activity="$(activity_count)" || { AD_DECISION="activity-unknown"; AD_RESULT=idle; return 0; }
  fi
  decision="$(bash "$AD_HERE/daytime-decision.sh" deploy 0 "$activity" "$banner" "$now" "$banner_end")" \
    || { AD_DECISION="decision-error"; AD_RESULT=error; return 0; }
  case "$decision" in
    banner)
      at="$(TZ=Asia/Tashkent date -d "@$((now + 900))" +%H:%M)"
      if banner_set "$at"; then AD_DECISION=banner; AD_RESULT="banner-$at"; else AD_DECISION="banner-failed"; AD_RESULT=error; fi
      return 0 ;;
    wait) AD_DECISION="wait-banner"; AD_RESULT=idle; return 0 ;;
    deploy-now|deploy-due) AD_DECISION="$decision" ;;
    *) AD_DECISION="$decision"; AD_RESULT=idle; return 0 ;;
  esac
  do_deploy "$cand"
}

do_deploy() {
  local sha="$1" after prev n
  if ! fetch_release "$sha"; then
    n=$(( $(attempts_get "$sha") + 1 )); attempts_set "$sha" "$n"
    AD_RESULT="fetch-failed"
    [[ $n -ge $AD_MAX_ATTEMPTS ]] && { mark_failed_tag "$sha"; AD_RESULT="gave-up"; }
    banner_clear; return 0
  fi
  if [[ -n "${GHCR_USER:-}" && -n "${GHCR_TOKEN:-}" ]]; then
    printf '%s' "$GHCR_TOKEN" | docker login ghcr.io -u "$GHCR_USER" --password-stdin >/dev/null 2>&1 || log "docker login ghcr.io не удался"
  fi
  if run_deploy "$sha"; then
    AD_RESULT=ok; rm -f "$RT_STATE/auto-deploy.attempts"
    date -u -d "@$(now_epoch)" +%Y-%m-%dT%H:%M:%SZ > "$RT_STATE/auto-deploy.last_deploy"
  else
    after="$(state_get current_tag | tr -d '[:space:]')"; prev="$(state_get previous_tag | tr -d '[:space:]')"
    if [[ "$after" == "$sha" && -n "$prev" && "$prev" != "$sha" ]]; then
      mark_failed_tag "$sha"
      if run_rollback; then AD_RESULT="rolled-back"; else AD_RESULT="rollback-failed"; fi
      date -u -d "@$(now_epoch)" +%Y-%m-%dT%H:%M:%SZ > "$RT_STATE/auto-deploy.last_deploy"
    else
      n=$(( $(attempts_get "$sha") + 1 )); attempts_set "$sha" "$n"
      AD_RESULT="failed-before-switch"
      [[ $n -ge $AD_MAX_ATTEMPTS ]] && { mark_failed_tag "$sha"; AD_RESULT="gave-up"; }
    fi
  fi
  [[ -n "${GHCR_USER:-}" ]] && docker logout ghcr.io >/dev/null 2>&1
  banner_clear
  return 0
}

main() {
  AD_T0="$(now_epoch)"
  mkdir -p "$RT_STATE"
  # shellcheck disable=SC1090
  [[ -f "$AD_ENV" ]] && source "$AD_ENV"
  exec 9>"$RT_STATE/deploy.lock"
  if ! flock -n 9; then AD_DECISION=locked; AD_RESULT=idle; journal; return 0; fi
  run_tick || AD_RESULT=error
  journal
  flock -u 9
  return 0
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then main "$@"; fi
