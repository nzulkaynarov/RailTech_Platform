#!/usr/bin/env bash
# Тест scripts/stand-ok.sh со стабом gh: правильный запрос, проверка sha, --revoke. Запуск: bash scripts/tests/stand-ok-test.sh
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"
cat > "$tmp/bin/gh" <<'STUB'
#!/usr/bin/env bash
echo "$*" >> "$STUB_LOG"
echo '"stub"'
STUB
chmod +x "$tmp/bin/gh"
export PATH="$tmp/bin:$PATH" STUB_LOG="$tmp/log" STAND_OK_REPO=o/r
sha=0123456789abcdef0123456789abcdef01234567
bash "$here/../stand-ok.sh" "$sha" >/dev/null
grep -q "repos/o/r/statuses/$sha" "$tmp/log" && grep -q "state=success" "$tmp/log" && grep -q "context=stand-ok" "$tmp/log" || { echo "FAIL: запрос на успех: $(cat "$tmp/log")"; exit 1; }
bash "$here/../stand-ok.sh" --revoke "$sha" >/dev/null
tail -n1 "$tmp/log" | grep -q "state=failure" || { echo "FAIL: --revoke"; exit 1; }
rc=0; bash "$here/../stand-ok.sh" "not-a-sha" >/dev/null 2>&1 || rc=$?; [ "$rc" -eq 2 ] || { echo "FAIL: мусорный sha, код $rc"; exit 1; }
rc=0; bash "$here/../stand-ok.sh" >/dev/null 2>&1 || rc=$?; [ "$rc" -eq 2 ] || { echo "FAIL: без аргументов, код $rc"; exit 1; }
echo "stand-ok-test: ok"
