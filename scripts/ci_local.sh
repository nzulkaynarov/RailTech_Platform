#!/usr/bin/env bash
# Локальный CI ансамбля — те же задания, что .github/workflows/ci.yml, на этом компьютере (Docker Desktop).
# Гейт мержа, пока GitHub Actions недоступен (биллинг аккаунта; DECISIONS 2026-10-13). Запуск: make ci-local.
# Платных вызовов моделей нет. legacy/b2b не проверяется (ORCHESTRATOR §3.11).
set -euo pipefail

# `make ci-local args="--quick"` отдаёт переменную args вложенным make (MAKEFLAGS и окружение), и цели вроде
# erp test-backend (args="<pytest-аргументы>") получают чужой --quick. Задания видят чистое окружение make.
unset MAKEFLAGS MFLAGS MAKELEVEL args

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ALL=(gitleaks crm contracts tokens infra erp cabinet platform rt-bus crm-integration crm-build crm-e2e crm-audit platform-e2e cpu-baseline)
GITLEAKS_IMAGE=ghcr.io/gitleaks/gitleaks:v8.30.1
CADDY_IMAGE=caddy:2.11.7-alpine
LOGS="$ROOT/.ci-local"

usage() {
  cat <<EOF
Локальный CI ансамбля (как .github/workflows/ci.yml).

  scripts/ci_local.sh                      все задания, кроме crm-e2e, crm-audit, platform-e2e и cpu-baseline
  scripts/ci_local.sh --full               всё, включая crm-e2e и platform-e2e (Playwright), crm-audit и cpu-baseline
  scripts/ci_local.sh crm contracts        только выбранные
  scripts/ci_local.sh --quick              без crm-integration и crm-build (быстрый гейт)

Задания:
  gitleaks          секреты в истории текущей ветки (.gitleaks.toml, legacy/ в allowlist)
  crm               make check-crm (ruff, mypy, eslint, prettier, tsc, unit) + OpenAPI CRM (packages/contracts/openapi/crm.yaml) без диффа
  contracts         make contracts (в т. ч. совместимость событий и oasdiff по OpenAPI с origin/main) + чистый packages/contracts/generated
  tokens            make -C packages/ui-tokens check
  infra             docker compose config (dev + observability) и caddy validate
  erp, cabinet      make check-erp | make check-cabinet (до M1/M2 — пропуск внутри цели)
  platform          make check-platform (ruff, mypy, pytest bff; eslint, tsc, vitest web; клиент orval и токены свежие)
  rt-bus            make check-rt-bus — библиотека шины: ruff, mypy, миграция Django, pytest на одноразовом postgres:17
  crm-integration   apps/crm/scripts/test_int_local.sh — одноразовые Postgres 17 и RustFS
  crm-build         образы CRM backend/frontend (prod) и backup с проверкой pg_dump 17
  crm-e2e           apps/crm/scripts/ci_local.sh e2e — одноразовый Postgres, API, preview, Playwright
  crm-audit         apps/crm/scripts/ci_local.sh audit — pip-audit и pnpm audit
  platform-e2e      make -C apps/platform e2e — Playwright + axe на MSW (BFF и стенд не нужны); chromium
                    ставится при первом запуске (pnpm exec playwright install chromium)
  cpu-baseline      как cpu-common и cpu-image в ci.yml (S0-7): самопроверка механики + сборка каждого образа прода linux/amd64
                    и его старт под эмуляцией CPU qemu64 (scripts/qemu_cpu_check.sh); на Mac arm64 долго, образы по одному

Стенд ансамбля и его БД не используются. Логи — .ci-local/<задание>.log. Код выхода 1 при любом сбое.
Нехватка памяти Docker (OOM, код 137) — запускайте при остановленном стенде (make down) или
увеличьте память Docker Desktop (Settings → Resources, 10–12 ГБ).
EOF
}

STAGES=()
for a in "$@"; do
  case "$a" in
    -h | --help) usage; exit 0 ;;
    --quick) STAGES=(gitleaks crm contracts tokens infra erp cabinet platform rt-bus) ;;
    --full) STAGES=("${ALL[@]}") ;;
    *) STAGES+=("$a") ;;
  esac
done
[ ${#STAGES[@]} -eq 0 ] && STAGES=(gitleaks crm contracts tokens infra erp cabinet platform rt-bus crm-integration crm-build)
# platform-e2e всегда после platform: check-platform пересоздаёт src/shared/api/generated (orval), и vite e2e на лету
# перезапускается/теряет модули (ERR_CONNECTION_REFUSED). Стадии идут строго по одной; порядок фиксируем явно.
if [[ " ${STAGES[*]} " == *" platform-e2e "* ]]; then
  _rest=()
  for s in "${STAGES[@]}"; do [ "$s" = platform-e2e ] || _rest+=("$s"); done
  STAGES=(${_rest[@]+"${_rest[@]}"} platform-e2e) # bash 3.2 (macOS): пустой массив под set -u
fi
for s in "${STAGES[@]}"; do
  [[ " ${ALL[*]} " == *" $s "* ]] || { echo "Неизвестное задание: $s"; usage; exit 2; }
done
command -v docker >/dev/null && docker info >/dev/null 2>&1 \
  || { echo "Docker не запущен: open -a Docker, затем повторите."; exit 1; }
mkdir -p "$LOGS"

stage_gitleaks() {
  # В git worktree `.git` — файл со ссылкой на общий каталог за пределами $ROOT; без него в контейнере git не видит историю
  # и gitleaks сканирует 0 коммитов. Общий каталог монтируется по тому же абсолютному пути (в основном checkout — ничего лишнего).
  local common mounts=(-v "$ROOT:/repo") out
  common="$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir)"
  [ "$common" = "$ROOT/.git" ] || mounts+=(-v "$common:$common:ro")
  out="$(docker run --rm "${mounts[@]}" -w /repo "$GITLEAKS_IMAGE" \
    git --redact --config .gitleaks.toml --log-opts=HEAD . 2>&1)" || { printf '%s\n' "$out"; return 1; }
  printf '%s\n' "$out"
  # 0 просканированных коммитов — не «чисто», а сломанный доступ к истории
  if printf '%s' "$out" | grep -Eq '(^|[^0-9])0 commits scanned'; then
    echo "gitleaks просканировал 0 коммитов — история недоступна в контейнере"
    return 1
  fi
}

stage_crm() {
  (cd "$ROOT" && make check-crm)
  (cd "$ROOT/apps/crm/backend" && uv run ruff check --config pyproject.toml ../scripts \
    && uv run ruff format --config pyproject.toml --check ../scripts)
  (cd "$ROOT/apps/crm" && make openapi && git diff --exit-code -- ../../packages/contracts/openapi/crm.yaml frontend/src/api) \
    || { echo "OpenAPI CRM или клиент orval устарели — make -C apps/crm openapi и закоммитьте"; return 1; }
}

stage_contracts() {
  # Совместимость схем событий (L8) и OpenAPI (oasdiff, ADR-0016) — против свежей origin/main, как в CI; без сети — с последней
  # скачанной. oasdiff — закреплённый образ в одноразовом контейнере (нужен Docker; образ тянется при первом запуске).
  (cd "$ROOT" && git fetch --no-tags --quiet origin main) \
    || echo "contracts: git fetch origin main не удался — сравнение с локальной origin/main"
  (cd "$ROOT" && CONTRACTS_BASE_REF="${CONTRACTS_BASE_REF:-origin/main}" make contracts \
    && git diff --exit-code -- packages/contracts/generated \
    && [ -z "$(git status --porcelain --untracked-files=all -- packages/contracts/generated)" ]) \
    || { echo "make contracts упал или packages/contracts/generated устарел — make contracts и закоммитьте"; return 1; }
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
    -e ACME_EMAIL=ci@example.com -e CRM_DOMAIN=crm.example.org -e ERP_DOMAIN=erp.example.org -e CABINET_DOMAIN=cabinet.example.org -e PLATFORM_DOMAIN=platform.example.org \
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
# Как job rt-bus в ci.yml; PostgreSQL — одноразовый контейнер packages/rt-bus/scripts/with_pg.sh (стенд не трогается).
stage_rt-bus() { (cd "$ROOT" && make -C packages/rt-bus install && make check-rt-bus); }

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
# Порт — E2E_PORT (по умолчанию 4173); если другой worktree уже занял порт, прогон падает, а не идёт в чужой сервер.
stage_platform-e2e() {
  (cd "$ROOT/apps/platform/web" && pnpm exec playwright install chromium)
  (cd "$ROOT" && make -C apps/platform e2e)
}

# S0-7: образы прода стартуют под эмуляцией CPU qemu64 (прод-VPS без x86-64-v2). Образы собираются и удаляются по одному.
stage_cpu-baseline() {
  "$ROOT/scripts/qemu_cpu_check.sh" selftest
  "$ROOT/scripts/qemu_cpu_check.sh" run
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
