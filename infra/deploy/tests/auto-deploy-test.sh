#!/usr/bin/env bash
# Тест auto-deploy.sh (ВЫКЛ-3): таблица случаев со стабами API, GHCR, часов, активности и deploy.sh. Запуск: bash этот-файл
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
script="$here/../auto-deploy.sh"
root_tmp="$(mktemp -d)"; trap 'rm -rf "$root_tmp"' EXIT
fails=0
A=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa   # выложен
B=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb   # новый зелёный
C=cccccccccccccccccccccccccccccccccccccccc   # новейший, красный
NIGHT=$(date -u -d '2026-11-27 20:00' +%s)    # 01:00 Ташкент
DAY=$(date -u -d '2026-11-28 07:00' +%s)      # 12:00 Ташкент

new_case() { # <имя>: чистое состояние; current_tag = A
  T="$root_tmp/$1"; rm -rf "$T"; mkdir -p "$T/state"
  export RT_ROOT="$T" RT_STATE="$T/state" RT_RELEASES="$T/releases" RT_MAINTENANCE_DIR="$T/maint"
  echo "$A" > "$T/state/current_tag"
  CASE="$1"
  unset FX_API_FAIL FX_ACTIVITY_RC; export FX_COMMITS="$C $B $A" FX_GREEN="$B $A" FX_STAND="$B $A" FX_COMPARE=ahead FX_IMAGES=0 FX_ACTIVITY=0 FX_DEPLOY=ok
  : > "$T/calls"
}
tick() { # <epoch>: один запуск auto-deploy.sh с подменёнными сетью и действиями
  (
    export AD_NOW="$1" AUTO_DEPLOY_ENV=/nonexistent
    # shellcheck source=infra/deploy/auto-deploy.sh
    source "$script"
    api_get() {
      [[ -z "${FX_API_FAIL:-}" ]] || return 1
      case "$1" in
        commits\?*) printf '['; local f=1 c; for c in $FX_COMMITS; do [[ $f == 1 ]] || printf ','; f=0; printf '{"sha":"%s"}' "$c"; done; printf ']' ;;
        commits/*/check-runs*) local c="${1#commits/}"; c="${c%%/*}"
          if [[ " $FX_GREEN " == *" $c "* ]]; then echo '{"check_runs":[{"status":"completed","conclusion":"success","started_at":"2026-11-27T10:00:00Z"}]}'
          else echo '{"check_runs":[{"status":"completed","conclusion":"failure","started_at":"2026-11-27T10:00:00Z"}]}'; fi ;;
        commits/*/statuses*) local c="${1#commits/}"; c="${c%%/*}"
          if [[ " $FX_STAND " == *" $c "* ]]; then echo '[{"context":"ci","state":"success","created_at":"2026-11-27T09:00:00Z"},{"context":"stand-ok","state":"success","created_at":"2026-11-27T10:00:00Z"}]'
          else echo '[{"context":"ci","state":"success","created_at":"2026-11-27T09:00:00Z"}]'; fi ;;
        compare/*) printf '{"status":"%s"}' "$FX_COMPARE" ;;
        *) return 1 ;;
      esac
    }
    ghcr_images_complete() { echo "ghcr $1" >> "$T/calls"; return "$FX_IMAGES"; }
    fetch_release() { REL="$RT_RELEASES/$1"; mkdir -p "$REL"; echo "fetch $1" >> "$T/calls"; }
    activity_count() { echo "$FX_ACTIVITY"; return "${FX_ACTIVITY_RC:-0}"; }
    banner_set() { MAINTENANCE_NOW="@$AD_NOW" MAINTENANCE_DIR="$RT_MAINTENANCE_DIR" bash "$here/../../../scripts/maintenance-notice.sh" set "$1" 20 planned >/dev/null; }
    run_deploy() {
      echo "deploy $1" >> "$T/calls"
      case "$FX_DEPLOY" in
        ok) echo "$A" > "$RT_STATE/previous_tag"; echo "$1" > "$RT_STATE/current_tag"; return 0 ;;
        smoke-fail) echo "$A" > "$RT_STATE/previous_tag"; echo "$1" > "$RT_STATE/current_tag"; return 1 ;;
        pre-fail) return 1 ;;
      esac
    }
    run_rollback() { echo "rollback" >> "$T/calls"; cp "$RT_STATE/previous_tag" "$RT_STATE/current_tag"; [[ "${FX_ROLLBACK_FAIL:-}" != 1 ]]; }
    main
  )
}
last() { tail -n1 "$T/state/auto-deploy.log"; }
field() { python3 -I -c 'import sys,json; print(json.loads(sys.argv[1])[sys.argv[2]])' "$(last)" "$1"; }
check() { # <описание> <ожидание-decision> <ожидание-result>
  local d r; d="$(field decision)"; r="$(field result)"
  if [[ "$d" != "$2" || "$r" != "$3" ]]; then echo "FAIL [$CASE] $1: decision=$d result=$r, ожидали $2/$3"; fails=$((fails + 1)); fi
}
expect_calls() { # <описание> <ожидаемые строки через ;>
  local got want; got="$(paste -sd';' "$T/calls")"; want="$2"
  if [[ "$got" != "$want" ]]; then echo "FAIL [$CASE] $1: вызовы '$got', ожидали '$want'"; fails=$((fails + 1)); fi
}
assert() { # <описание> <условие-команда...>
  local what="$1"; shift
  "$@" || { echo "FAIL [$CASE] $what"; fails=$((fails + 1)); }
}

new_case nothing-new; FX_COMMITS="$A"; tick "$NIGHT"
check "нет нового коммита" up-to-date idle; expect_calls "ничего не делаем" ""

new_case newest-red; FX_COMMITS="$C $A"; FX_GREEN="$A"; tick "$NIGHT"
check "новейший красный, зелёный - выложенный" up-to-date idle

new_case night-new; tick "$NIGHT"
check "новый зелёный ночью" deploy-now ok; expect_calls "образы, релиз, deploy" "ghcr $B;fetch $B;deploy $B"
assert "current_tag обновлён" test "$(cat "$T/state/current_tag")" = "$B"
assert "баннер снят" test ! -e "$T/maint/maintenance.json"
assert "status.json есть" test -s "$T/state/auto-deploy.status.json"
assert "в журнале sha и duration" bash -c "grep -q '\"sha\":\"$B\"' '$T/state/auto-deploy.log' && grep -q duration_s '$T/state/auto-deploy.log'"
assert "красный C не выбран" bash -c "! grep -q $C '$T/calls'"

new_case day-idle; tick "$DAY"
check "днём никого нет" deploy-now ok

new_case day-active; FX_ACTIVITY=7
tick "$DAY";           check "днём активность: баннер" banner banner-12:15; expect_calls "deploy не идёт" "ghcr $B"
assert "баннер записан" test -s "$T/maint/maintenance.json"
tick $((DAY + 600)); check "баннер ещё впереди" wait-banner idle
tick $((DAY + 1200)); check "время баннера пришло" deploy-due ok
assert "баннер снят после выкладки" test ! -e "$T/maint/maintenance.json"

new_case day-activity-unknown; FX_ACTIVITY=0; FX_ACTIVITY_RC=1; tick "$DAY"
check "активность не прочитана" activity-unknown idle; expect_calls "без выкладки" "ghcr $B"

new_case images-incomplete; FX_IMAGES=1; tick "$NIGHT"
check "образы не готовы" wait-images idle; expect_calls "без выкладки" "ghcr $B"

new_case no-stand-ok; FX_STAND="$A"; tick "$NIGHT"
check "зелёный CI, но нет stand-ok" wait-stand "ждёт проверки на стенде"; expect_calls "ничего не выкладываем и образы не смотрим" ""
assert "status.json говорит про стенд" grep -q "ждёт проверки на стенде" "$T/state/auto-deploy.status.json"
assert "в журнале sha, ждущий стенда" grep -q "\"sha\":\"$B\"" "$T/state/auto-deploy.log"
FX_STAND="$B $A"; tick "$((NIGHT + 600))"
check "stand-ok поставлен - выкладываем" deploy-now ok

new_case newest-lacks-stand; FX_COMMITS="$C $B $A"; FX_GREEN="$C $B $A"; FX_STAND="$B $A"; tick "$NIGHT"
check "новейший без stand-ok пропускается, берётся новейший с обоими" deploy-now ok; expect_calls "выложен B" "ghcr $B;fetch $B;deploy $B"

new_case stand-ok-without-ci; FX_GREEN="$A"; FX_STAND="$B $A"; tick "$NIGHT"
check "stand-ok без зелёного CI не годится" up-to-date idle

new_case stand-revoked
out="$(bash -c 'source "$1"; echo "[{\"context\":\"stand-ok\",\"state\":\"success\",\"created_at\":\"2026-11-27T10:00:00Z\"},{\"context\":\"stand-ok\",\"state\":\"failure\",\"created_at\":\"2026-11-27T11:00:00Z\"}]" | stand_ok' _ "$script")"
assert "снятый stand-ok (failure позже success) не годится" test "$out" = false

new_case ghcr-down; FX_IMAGES=2; tick "$NIGHT"
check "GHCR недоступен" ghcr-unavailable idle

new_case failed-tag; echo "$B" > "$T/state/failed_tags"; tick "$NIGHT"
check "sha в failed_tags" skip-failed idle; expect_calls "без выкладки" ""

new_case older; FX_COMPARE=behind; tick "$NIGHT"
check "кандидат старше выложенного" skip-older idle
new_case diverged; FX_COMPARE=diverged; tick "$NIGHT"
check "расходящийся" skip-diverged idle

new_case api-down; FX_API_FAIL=1; tick "$NIGHT"
check "API недоступен" api-unavailable idle; expect_calls "ничего не делаем" ""
assert "отступление записано" test -s "$T/state/auto-deploy.backoff"
tick $((NIGHT + 60)); check "внутри отступления тик пустой" api-backoff idle
unset FX_API_FAIL
tick $((NIGHT + 7200)); check "после отступления API вернулся" deploy-now ok
assert "отступление снято" test ! -e "$T/state/auto-deploy.backoff"

new_case smoke-fail; FX_DEPLOY=smoke-fail; tick "$NIGHT"
check "smoke упал" deploy-now rolled-back; expect_calls "откат после переключения" "ghcr $B;fetch $B;deploy $B;rollback"
assert "sha в failed_tags" grep -qxF "$B" "$T/state/failed_tags"
assert "current_tag - прежний" test "$(cat "$T/state/current_tag")" = "$A"
tick $((NIGHT + 600)); check "откаченный sha больше не берётся" skip-failed idle

new_case pre-switch-fail; FX_DEPLOY=pre-fail
tick "$NIGHT";          check "сбой до переключения, 1" deploy-now failed-before-switch
tick $((NIGHT + 600)); check "сбой до переключения, 2" deploy-now failed-before-switch
tick $((NIGHT + 1200)); check "сбой до переключения, 3" deploy-now gave-up
assert "после трёх попыток sha в failed_tags" grep -qxF "$B" "$T/state/failed_tags"
assert "откат не вызывался" bash -c "! grep -q rollback '$T/calls'"

new_case locked; ( exec 8>"$T/state/deploy.lock"; flock -n 8; tick "$NIGHT" )
check "замок занят" locked idle; expect_calls "без выкладки" ""

new_case paused; touch "$T/state/auto-deploy.paused"; tick "$NIGHT"
check "пауза" paused idle; expect_calls "без выкладки" ""
assert "status.json говорит paused" grep -q '"paused":true' "$T/state/auto-deploy.status.json"

new_case first-deploy; rm -f "$T/state/current_tag"; tick "$NIGHT"
check "первая выкладка без current_tag" deploy-now ok

new_case stale-banner; FX_COMMITS="$A"; mkdir -p "$T/maint"
printf '{"starts_at":"2026-11-28T09:00:00+05:00","minutes":20,"kind":"planned"}\n' > "$T/maint/maintenance.json"; tick "$DAY"
check "нечего выкладывать, старый баннер" up-to-date idle
assert "старый баннер снят" test ! -e "$T/maint/maintenance.json"

# журнал: каждая строка - JSON с нужными полями; ротация
new_case journal; tick "$NIGHT"
python3 -I - "$T/state/auto-deploy.log" <<'PY' || { echo "FAIL [journal] строка журнала не JSON"; fails=$((fails + 1)); }
import json, sys
for line in open(sys.argv[1]):
    d = json.loads(line)
    assert set(d) == {"ts", "sha", "decision", "result", "duration_s"}, d
PY
head -c 600000 /dev/zero | tr '\0' 'x' > "$T/state/auto-deploy.log"; FX_COMMITS="$A"; tick "$NIGHT"
assert "журнал ротирован" test -f "$T/state/auto-deploy.log.1"

# реальный api_get: ETag-кэш (304 отдаёт тело из кэша) и отказ при 403
new_case etag
stub="$T/bin"; mkdir -p "$stub"
cat > "$stub/curl" <<'STUB'
#!/usr/bin/env bash
# стаб curl для api_get: запоминает, был ли If-None-Match, и отвечает по $STUB_MODE
hdr=""; out=""; while [ $# -gt 0 ]; do case "$1" in -D) hdr="$2"; shift ;; -o) out="$2"; shift ;; -H) case "$2" in If-None-Match*) echo "$2" >> "$STUB_LOG" ;; esac; shift ;; esac; shift; done
case "$STUB_MODE" in
  200) printf 'HTTP/2 200\r\netag: "abc"\r\n\r\n' > "$hdr"; echo '[{"sha":"x1"}]' > "$out"; printf 200 ;;
  304) printf 'HTTP/2 304\r\n\r\n' > "$hdr"; : > "$out"; printf 304 ;;
  403) printf 'HTTP/2 403\r\n\r\n' > "$hdr"; : > "$out"; printf 403 ;;
esac
STUB
chmod +x "$stub/curl"
(
  export PATH="$stub:$PATH" STUB_LOG="$T/ifnone" AD_NOW=$NIGHT
  # shellcheck source=infra/deploy/auto-deploy.sh
  source "$script"
  STUB_MODE=200 api_get "commits?sha=main" | grep -q x1 || { echo "FAIL [etag] 200"; exit 1; }
  STUB_MODE=304 api_get "commits?sha=main" | grep -q x1 || { echo "FAIL [etag] 304 не отдал кэш"; exit 1; }
  grep -q '"abc"' "$STUB_LOG" || { echo "FAIL [etag] If-None-Match не отправлен"; exit 1; }
  if STUB_MODE=403 api_get "commits?sha=other" >/dev/null 2>&1; then echo "FAIL [etag] 403 должен быть ошибкой"; exit 1; fi
) || fails=$((fails + 1))

if [[ "$fails" -ne 0 ]]; then echo "auto-deploy-test: провалов $fails"; exit 1; fi
echo "auto-deploy-test: ok"
