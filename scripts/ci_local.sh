#!/usr/bin/env bash
# Локальный CI ансамбля — те же задания, что .github/workflows/ci.yml, на этом компьютере (Docker Desktop).
# Гейт мержа, пока GitHub Actions недоступен (биллинг аккаунта; DECISIONS 2026-10-13). Запуск: make ci-local.
# Платных вызовов моделей нет. legacy/b2b не проверяется (ORCHESTRATOR §3.11).
set -euo pipefail

# `make ci-local args="--quick"` отдаёт переменную args вложенным make (MAKEFLAGS и окружение), и цели вроде
# erp test-backend (args="<pytest-аргументы>") получают чужой --quick. Задания видят чистое окружение make.
unset MAKEFLAGS MFLAGS MAKELEVEL args

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ALL=(gitleaks crm contracts tokens infra erp cabinet platform crm-integration crm-build crm-e2e crm-audit platform-e2e)
GITLEAKS_IMAGE=ghcr.io/gitleaks/gitleaks:v8.30.1
CADDY_IMAGE=caddy:2.11.7-alpine
LOGS="$ROOT/.ci-local"

usage() {
  cat <<EOF
Локальный CI ансамбля (как .github/workflows/ci.yml).

  scripts/ci_local.sh                      все задания, кроме crm-e2e, crm-audit и platform-e2e
  scripts/ci_local.sh --full               всё, включая crm-e2e и platform-e2e (Playwright) и crm-audit
  scripts/ci_local.sh crm contracts        только выбранные
  scripts/ci_local.sh --quick              без crm-integration и crm-build (быстрый гейт)

Задания:
  gitleaks          секреты в истории текущей ветки (.gitleaks.toml, legacy/ в allowlist)
  crm               make check-crm (ruff, mypy, eslint, prettier, tsc, unit) + OpenAPI CRM без диффа
  contracts         make contracts + чистый diff packages/contracts/generated
  tokens            make -C packages/ui-tokens check
  infra             docker compose config (dev + observability) и caddy validate
  erp, cabinet      make check-erp | make check-cabinet (до M1/M2 — пропуск внутри цели)
  platform          make check-platform (ruff, mypy, pytest bff; eslint, tsc, vitest web; клиент orval и токены свежие)
  crm-integration   apps/crm/scripts/test_int_local.sh — одноразовые Postgres 17 и RustFS
  crm-build         образы CRM backend/frontend (prod) и backup с проверкой pg_dump 17
  crm-e2e           apps/crm/scripts/ci_local.sh e2e — одноразовый Postgres, API, preview, Playwright
  crm-audit         apps/crm/scripts/ci_local.sh audit — pip-audit и pnpm audit
  platform-e2e      make -C apps/platform e2e — Playwright + axe на MSW (BFF и стенд не нужны); chromium
                    ставится при первом запуске (pnpm exec playwright install chromium)

Стенд ансамбля и его БД не используются. Логи — .ci-local/<задание>.log. Код выхода 1 при любом сбое.
Нехватка памяти Docker (OOM, код 137) — запускайте при остановленном стенде (make down) или
увеличьте память Docker Desktop (Settings → Resources, 10–12 ГБ).
EOF
}

STAGES=()
for a in "$@"; do
  case "$a" in
    -h | --help) usage; exit 0 ;;
    --quick) STAGES=(gitleaks crm contracts tokens infra erp cabinet platform) ;;
    --full) STAGES=("${ALL[@]}") ;;
    *) STAGES+=("$a") ;;
  esac
done
[ ${#STAGES[@]} -eq 0 ] && STAGES=(gitleaks crm contracts tokens infra erp cabinet platform crm-integration crm-build)
for s in "${STAGES[@]}"; do
  [[ " ${ALL[*]} " == *" $s "* ]] || { echo "Неизвестное задание: $s"; usage; exit 2; }
done
command -v docker >/dev/null && docker info >/dev/null 2>&1 \
  || { echo "Docker не запущен: open -a Docker, затем повторите."; exit 1; }
mkdir -p "$LOGS"

stage_gitleaks() {
  docker run --rm -v "$ROOT:/repo" -w /repo "$GITLEAKS_IMAGE" \
    git --redact --config .gitleaks.toml --log-opts=HEAD .
}

stage_crm() {
  (cd "$ROOT" && make check-crm)
  (cd "$ROOT/apps/crm/backend" && uv run ruff check --config pyproject.toml ../scripts \
    && uv run ruff format --config pyproject.toml --check ../scripts)
  (cd "$ROOT/apps/crm" && make openapi && git diff --exit-code -- docs/api frontend/src/api) \
    || { echo "OpenAPI CRM или клиент orval устарели — make -C apps/crm openapi и закоммитьте"; return 1; }
}

stage_contracts() {
  (cd "$ROOT" && make contracts && git diff --exit-code -- packages/contracts/generated) \
    || { echo "packages/contracts/generated устарел — make contracts и закоммитьте"; return 1; }
}

stage_tokens() { (cd "$ROOT" && make -C packages/ui-tokens check); }

stage_infra() {
  local envfile
  envfile=$(mktemp)
  sed 's/CHANGE_ME/ci-only-value/' "$ROOT/.env.example" >"$envfile"
  docker compose -f "$ROOT/infra/compose/base.yml" -f "$ROOT/infra/compose/dev.yml" \
    --env-file "$envfile" --profile observability config -q
  rm -f "$envfile"
  docker run --rm -v "$ROOT/infra/caddy/Caddyfile.dev:/etc/caddy/Caddyfile:ro" "$CADDY_IMAGE" \
    caddy validate --config /etc/caddy/Caddyfile
  # Прод-конфиги (FIX-54, G-12; M5-INF-01c) — те же шаги, что в ci.yml (job infra): CHANGE_ME → заглушка, секретов нет.
  local prod_env
  prod_env=$(mktemp)
  sed 's/CHANGE_ME/ci-only-value/' "$ROOT/infra/.env.prod.example" >"$prod_env"
  RT_IMAGE_TAG=ci-only docker compose -f "$ROOT/infra/compose/base.yml" -f "$ROOT/infra/compose/prod.yml" \
    --env-file "$prod_env" --profile observability --profile kb-ingest config -q
  RT_IMAGE_TAG=ci-only docker compose -f "$ROOT/infra/compose/db.yml" --env-file "$prod_env" config -q
  rm -f "$prod_env"
  docker run --rm \
    -e ACME_EMAIL=ci@example.com -e CRM_DOMAIN=crm.example.org -e ERP_DOMAIN=erp.example.org -e CABINET_DOMAIN=cabinet.example.org \
    -v "$ROOT/infra/caddy/Caddyfile.prod:/etc/caddy/Caddyfile:ro" "$CADDY_IMAGE" \
    caddy validate --config /etc/caddy/Caddyfile
}

stage_erp() {
  (cd "$ROOT" && make check-erp)
  # Дрейф схемы ERP (FIX-40): schema.json, типы фронтенда и erp-internal.yaml совпадают с выгрузкой из кода.
  (cd "$ROOT" && make -C apps/erp openapi-check) \
    || { echo "Схема ERP устарела — make -C apps/erp openapi и закоммитьте schema.json, schema.d.ts, erp-internal.yaml"; return 1; }
}
stage_cabinet() { (cd "$ROOT" && make check-cabinet); }
stage_platform() { (cd "$ROOT" && make check-platform); }

stage_crm-integration() {
  local status=0
  "$ROOT/apps/crm/scripts/test_int_local.sh" || status=$?
  "$ROOT/apps/crm/scripts/test_int_local.sh" --down
  return $status
}

stage_crm-build() {
  docker build -q --target prod -t rt-platform-crm-backend:ci "$ROOT/apps/crm/backend" >/dev/null
  docker build -q --target prod -t rt-platform-crm-frontend:ci "$ROOT/apps/crm/frontend" >/dev/null
  docker build -q --target backup -t rt-platform-crm-backup:ci "$ROOT/apps/crm/backend" >/dev/null
  docker run --rm rt-platform-crm-backup:ci /usr/lib/postgresql/17/bin/pg_dump --version \
    | grep -q "pg_dump (PostgreSQL) 17"
  docker run --rm rt-platform-crm-backup:ci /app/ops/backup.sh --help >/dev/null
}

stage_crm-e2e() { "$ROOT/apps/crm/scripts/ci_local.sh" e2e; }
stage_crm-audit() { "$ROOT/apps/crm/scripts/ci_local.sh" audit; }

# Как job platform-e2e в ci.yml: браузер Playwright ставится (быстро, если уже есть), vite --mode mock поднимает сам playwright.config.ts.
stage_platform-e2e() {
  (cd "$ROOT/apps/platform/web" && pnpm exec playwright install chromium)
  (cd "$ROOT" && make -C apps/platform e2e)
}

declare -a RESULT=()
failed=0
for s in "${STAGES[@]}"; do
  echo "━━ $s ━━ (лог: .ci-local/$s.log)"
  start=$(date +%s)
  set +e
  (
    set -euo pipefail
    "stage_$s"
  ) >"$LOGS/$s.log" 2>&1
  rc=$?
  set -e
  if [ $rc -eq 0 ]; then
    RESULT+=("✔ $s  $(($(date +%s) - start)) с")
  else
    RESULT+=("✘ $s  $(($(date +%s) - start)) с — tail -50 .ci-local/$s.log")
    failed=1
  fi
  tail -3 "$LOGS/$s.log"
done
echo
printf '%s\n' "${RESULT[@]}"
[ $failed -eq 0 ] && echo "Локальный CI зелёный — можно мержить." || echo "Есть сбои — смотрите логи выше."
exit $failed
