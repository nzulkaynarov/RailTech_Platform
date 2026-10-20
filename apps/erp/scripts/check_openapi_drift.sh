#!/usr/bin/env bash
# Дрейф схемы ERP (FIX-40): перегенерирует schema.json, типы фронтенда и erp-internal.yaml и падает, если они отличаются
# от того, что лежит в рабочем дереве. Сравнение до/после по содержимому, а не `git diff`: работает и с незакоммиченными
# правками. При дрейфе перегенерированные файлы остаются на месте — просмотрите diff и закоммитьте.
#
#   scripts/check_openapi_drift.sh          # из apps/erp; вызывается: make -C apps/erp openapi-check
set -euo pipefail

APP="$(cd "$(dirname "$0")/.." && pwd)"
FILES=(
  backend/schema.json
  frontend/src/api/schema.d.ts
  ../../packages/contracts/openapi/erp-internal.yaml
)
BEFORE="$(mktemp -d)"
trap 'rm -rf "$BEFORE"' EXIT

cd "$APP"
for i in "${!FILES[@]}"; do cp "${FILES[$i]}" "$BEFORE/$i"; done

make --no-print-directory openapi

drift=0
for i in "${!FILES[@]}"; do
  if ! diff -u "$BEFORE/$i" "${FILES[$i]}" >"$BEFORE/$i.diff"; then
    drift=1
    echo "✘ дрейф: ${FILES[$i]}" >&2
    sed -e "1s|.*|--- ${FILES[$i]} (в репозитории)|" -e "2s|.*|+++ ${FILES[$i]} (из кода)|" "$BEFORE/$i.diff" | head -n 60 >&2
  fi
done
if [ "$drift" -ne 0 ]; then
  echo "Схема ERP устарела относительно кода: make -C apps/erp openapi и закоммитьте schema.json, schema.d.ts, erp-internal.yaml." >&2
  exit 1
fi
echo "✔ схема ERP (schema.json, типы фронтенда, erp-internal.yaml) совпадает с кодом"
