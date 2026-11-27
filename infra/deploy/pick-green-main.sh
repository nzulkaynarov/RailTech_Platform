#!/usr/bin/env bash
# Новейший коммит origin/main с зелёной «CI ok» (ночная выкладка и баннер выбирают кандидата одним правилом).
# Зелёная = самый свежий check-run «CI ok» на коммите (filter=latest, по started_at) completed/success. Нет проверки, идёт или красная -
# смотрим предыдущий коммит (первые родители, не более 40). Печатает sha в stdout; нет зелёного - код 1.
# Нужны: клон с origin/main и историей, gh с GH_TOKEN, GITHUB_REPOSITORY. Шаг «Зелёный «CI ok» на этом sha» в deploy.yml проверяет тем же правилом.
set -euo pipefail
for c in $(git rev-list --first-parent --max-count=40 origin/main); do
  ok="$(gh api -X GET "repos/$GITHUB_REPOSITORY/commits/$c/check-runs" -f check_name='CI ok' -f filter=latest -f per_page=100 \
    --jq '[.check_runs[]] | sort_by(.started_at) | last | (.status == "completed" and .conclusion == "success")' 2>/dev/null || echo false)"
  if [ "$ok" = "true" ]; then echo "$c"; exit 0; fi
  echo "«CI ok» на $c не зелёная - смотрим предыдущий коммит main" >&2
done
echo "в последних 40 коммитах main нет зелёной «CI ok»" >&2
exit 1
