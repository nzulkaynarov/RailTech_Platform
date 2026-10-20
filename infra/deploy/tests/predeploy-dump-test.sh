#!/usr/bin/env bash
# Тест гейта: фейковый docker, у которого pg_dump пишет непустой файл и возвращает 1, — гейт обязан упасть,
# каталог дампа — удалиться; при успешном pg_dump и читаемом pg_restore — пройти.  Запуск: bash этот-файл
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
printf 'DB_INTERNAL_IP=10.0.0.2\nDB_CRM_PASSWORD=x\nDB_ERP_PASSWORD=x\n' > "$tmp/env"; chmod 600 "$tmp/env"

# Фейковый docker: ищет в аргументах pg_dump / pg_restore, ведёт себя по FAKE_MODE.
cat > "$tmp/docker" <<'FAKE'
#!/usr/bin/env bash
args="$*"
if [[ "$args" == *pg_dump* ]]; then
  out="$(printf '%s\n' "$@" | grep -m1 ':/out$' | cut -d: -f1)"
  db="$(printf '%s\n' "$@" | sed -n 's#^/out/\(.*\)\.dump$#\1#p')"
  echo "PGDMP-truncated" > "$out/$db.dump"
  [[ "$FAKE_MODE" == pgdump_fails ]] && exit 1
fi
exit 0
FAKE
chmod +x "$tmp/docker"

run() { RT_ENV_FILE="$tmp/env" RT_STATE="$tmp/state" PG_DOCKER="$tmp/docker" FAKE_MODE="$1" bash "$here/../predeploy-dump.sh" t1 >"$tmp/log" 2>&1; }

if run pgdump_fails; then echo "FAIL: гейт пропустил упавший pg_dump"; exit 1; fi
[[ -z "$(find "$tmp/state/predeploy" -name '*.dump' 2>/dev/null)" ]] || { echo "FAIL: частичный дамп остался"; exit 1; }
run ok || { echo "FAIL: гейт не прошёл на исправном pg_dump"; cat "$tmp/log"; exit 1; }
echo "predeploy-dump-test: ok"
