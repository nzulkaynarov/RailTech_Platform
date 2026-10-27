#!/usr/bin/env bash
# Тест should-deploy.sh на временном git-репозитории: новее, старше, равен, расходящиеся ветки, пустой/мусорный current.
# Запуск: bash этот-файл
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
script="$here/../should-deploy.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

git init -q "$tmp/repo"
cd "$tmp/repo"
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.org GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.org
commit() { git commit -q --allow-empty -m "$1"; git rev-parse HEAD; }
c1="$(commit c1)"
c2="$(commit c2)"
c3="$(commit c3)"               # линия main: c1 -> c2 -> c3
git checkout -q -b side "$c1"
s1="$(commit side1)"            # расходящаяся ветка от c1

expect() {   # expect <ожидание> <тег> <current> <описание>
  local want="$1" got
  got="$(bash "$script" "$2" "$3")" || { echo "FAIL: $4: код выхода ≠ 0"; exit 1; }
  [ "$got" = "$want" ] || { echo "FAIL: $4: ожидали $want, получили $got"; exit 1; }
}

expect deploy        "$c3" "$c2" "тег новее current"
expect deploy        "$c3" "$c1" "тег новее current через один коммит"
expect skip-older    "$c2" "$c3" "тег старше current (инцидент 2026-10-28)"
expect skip-older    "$c1" "$c3" "тег намного старше current"
expect skip-same     "$c3" "$c3" "тег равен current"
expect skip-same     "$c3" "${c3:0:12}" "current — сокращённый sha того же коммита"
expect skip-diverged "$s1" "$c3" "расходящиеся ветки (тег в side)"
expect skip-diverged "$c3" "$s1" "расходящиеся ветки (current в side)"
expect deploy        "$c3" ""    "current пуст (первая выкладка)"
expect skip-diverged "$c3" "0123456789abcdef0123456789abcdef01234567" "current — коммита нет в клоне"
expect skip-diverged "$c3" "--help" "current — не sha (не должен стать опцией git)"
expect skip-diverged "$c3" "main"   "current — имя ref, а не sha"

# ошибки вызова
rc=0; bash "$script" "$c3" >/dev/null 2>&1 || rc=$?
[ "$rc" -eq 2 ] || { echo "FAIL: один аргумент должен давать код 2 (rc=$rc)"; exit 1; }
rc=0; bash "$script" "not-a-commit" "$c3" >/dev/null 2>&1 || rc=$?
[ "$rc" -eq 2 ] || { echo "FAIL: тег не коммит должен давать код 2 (rc=$rc)"; exit 1; }

echo "should-deploy-test: ok"
