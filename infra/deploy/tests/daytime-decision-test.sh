#!/usr/bin/env bash
# Тест daytime-decision.sh и activity-check.sh --stdin (ВЫКЛ-2). Запуск: bash этот-файл
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
dec="$here/../daytime-decision.sh"; act="$here/../activity-check.sh"

expect() { # <ожидание> <описание> <аргументы decision...>
  local want="$1" what="$2" got; shift 2
  got="$(bash "$dec" "$@")" || { echo "FAIL: $what: код выхода ≠ 0"; exit 1; }
  [ "$got" = "$want" ] || { echo "FAIL: $what: ожидали $want, получили $got"; exit 1; }
}
now=1000000
expect deploy-now "никого нет"                         deploy 0 0 - $now
expect banner     "есть активность, баннера нет"       deploy 0 5 - $now
expect wait       "баннер через 15 минут"              deploy 0 5 $((now + 900)) $now
expect wait       "баннер ещё не наступил, тишина"     deploy 0 0 $((now + 900)) $now
expect deploy-due "баннер наступил, люди работают"     deploy 0 9 $now $now
expect deploy-due "баннер в пределах допуска 3 минуты" deploy 0 9 $((now + 150)) $now
expect wait       "баннер дальше допуска"              deploy 0 9 $((now + 181)) $now
# окно баннера (по умолчанию 20 минут от starts_at) прошло - баннера для людей нет, активность проверяется заново
expect banner     "окно баннера прошло, люди работают" deploy 0 9 $((now - 4000)) $now
expect deploy-now "окно баннера прошло, тишина"        deploy 0 0 $((now - 4000)) $now
expect deploy-due "баннер в конце своего окна"         deploy 0 9 $((now - 1200)) $now
expect banner     "баннер на секунду позже окна"       deploy 0 9 $((now - 1201)) $now
expect deploy-due "окно задано явно (5 минут), идёт"   deploy 0 9 $((now - 200)) $now $((now - 200 + 300))
expect banner     "окно задано явно (5 минут), прошло" deploy 0 9 $((now - 400)) $now $((now - 400 + 300))
# ночью (activity=0, её не читают) баннер передаётся как есть: тик 00:45-00:59 при баннере на 00:55/01:00 не выкладывает раньше объявленного
expect wait       "ночь: баннер на будущее время, активности не читали" deploy 0 0 $((now + 600)) $now $((now + 600 + 1200))
expect wait       "ночь: баннер на 14 минут вперёд"                     deploy 0 0 $((now + 840)) $now $((now + 840 + 1200))
expect deploy-due "ночь: время баннера наступило"                       deploy 0 0 $now $now $((now + 1200))
expect deploy-now "ночь: баннер давно отыграл"                          deploy 0 0 $((now - 4000)) $now $((now - 4000 + 1200))
# gate передаёт в решение реальный баннер в любой фазе (не подменяет его на «-» ночью)
wf="$here/../../../.github/workflows/deploy.yml"
grep -q 'daytime-decision.sh "\$should" "\$failed" "\$activity" "\$banner" "\$now" "\$banner_end"' "$wf" \
  || { echo "FAIL: gate должен передавать в daytime-decision.sh реальные \$banner и \$banner_end"; exit 1; }
! grep -q 'dbanner' "$wf" || { echo "FAIL: ночью баннер не подменяется (dbanner)"; exit 1; }
expect skip       "sha уже выложен"                    skip-same 0 0 - $now
expect skip       "sha старше выложенного"             skip-older 0 0 - $now
expect skip       "расходящиеся ветки"                 skip-diverged 0 0 - $now
expect skip       "sha откачен автооткатом"            deploy 1 0 - $now
expect skip       "откачен, даже когда баннер пришёл"  deploy 1 3 $now $now

# откат: failed_tags (lib.sh mark_failed_tag), без дублей и с проверкой имени тега
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
( RT_STATE="$tmp/state"; source "$here/../lib.sh"
  mark_failed_tag abc123; mark_failed_tag abc123; mark_failed_tag "bad tag;rm"; mark_failed_tag def456 )
[ "$(cat "$tmp/state/failed_tags")" = "$(printf 'abc123\ndef456')" ] || { echo "FAIL: mark_failed_tag записал не то: $(cat "$tmp/state/failed_tags")"; exit 1; }
grep -q '^mark_failed_tag "\$cur"' "$here/../rollback.sh" || { echo "FAIL: rollback.sh не помечает откаченный тег (mark_failed_tag)"; exit 1; }
rc=0; bash "$dec" deploy 0 x - $now >/dev/null 2>&1 || rc=$?
[ "$rc" -eq 2 ] || { echo "FAIL: мусорное число активности должно давать код 2 (rc=$rc)"; exit 1; }
rc=0; bash "$dec" deploy 0 0 >/dev/null 2>&1 || rc=$?
[ "$rc" -eq 2 ] || { echo "FAIL: мало аргументов - код 2 (rc=$rc)"; exit 1; }

# activity-check: считаем успешные запросы, кроме health, bus и ошибок
log='INFO:     127.0.0.1:1 - "GET /api/v1/health HTTP/1.1" 200 OK
INFO:     172.18.0.9:2 - "POST /bus/v1/events HTTP/1.1" 200 OK
INFO:     172.18.0.9:3 - "GET /api/v1/me HTTP/1.1" 200 OK
INFO:     172.18.0.9:4 - "GET /api/v1/deals?limit=50 HTTP/1.1" 304 Not Modified
INFO:     172.18.0.9:5 - "POST /api/v1/auth/login HTTP/1.1" 401 Unauthorized
INFO:     172.18.0.9:6 - "GET /mcp/x HTTP/1.1" 404 Not Found
INFO:     172.18.0.9:7 - "GET /api/v1/x HTTP/1.1" 500 Internal Server Error
INFO:     Application startup complete.'
got="$(printf '%s\n' "$log" | bash "$act" --stdin)"
[ "$got" = 2 ] || { echo "FAIL: activity-check: ожидали 2, получили $got"; exit 1; }
got="$(printf '' | bash "$act" --stdin)"
[ "$got" = 0 ] || { echo "FAIL: activity-check: пустой журнал - 0, получили $got"; exit 1; }
echo "daytime-decision-test: ok"
