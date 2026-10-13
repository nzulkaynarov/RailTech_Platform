#!/usr/bin/env bash
# Локальный CI — те же задания, что `.github/workflows/ci.yml`, на этом компьютере (Docker Desktop).
# Гейт мержа, пока GitHub Actions недоступен (решение владельца 2026-10-13, docs/DECISIONS.md).
# Платных вызовов моделей нет: eval-gate сюда не входит (только `make eval*` с согласия владельца).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ALL=(lint integration e2e audit build)
E2E_PG=rt-e2e-pg
E2E_PG_PORT="${E2E_PG_PORT:-55442}"
E2E_API_PORT="${E2E_API_PORT:-18000}"
E2E_WEB_PORT=4173
PASS=ci-only-password
PG_IMAGE=pgvector/pgvector:0.8.7-pg16
GITLEAKS_IMAGE=ghcr.io/gitleaks/gitleaks:v8.30.1
LOGS="$ROOT/.ci-local"

usage() {
  cat <<EOF
Локальный CI (как .github/workflows/ci.yml): lint+unit, integration, e2e, audit, build.

  scripts/ci_local.sh                 все задания
  scripts/ci_local.sh lint e2e        только выбранные
  scripts/ci_local.sh --help

Задания:
  lint         make check (ruff, mypy, eslint, prettier, tsc, unit), OpenAPI без диффа,
               compose-файлы валидны, gitleaks
  integration  scripts/test_int_local.sh — одноразовые Postgres и RustFS
  e2e          одноразовый Postgres :$E2E_PG_PORT, миграции, seed-demo, API :$E2E_API_PORT,
               сборка фронта и preview :$E2E_WEB_PORT, Playwright (chromium + mobile)
  audit        pip-audit (prod-зависимости backend), pnpm audit --prod --audit-level high
  build        образы backend/frontend (prod) и backup с проверкой pg_dump 16

Стенд и его БД не используются; ключи и токен из .env в тесты не попадают.
Логи — .ci-local/. Итог — таблица и код выхода 1 при любом сбое.
Что дальше: всё ✔ — можно мержить PR; ✘ — смотрите лог задания в .ci-local/.
Сборка упала с «cannot allocate memory» или стенд остановлен Docker по памяти (итог предупредит) —
стенду и сборке не хватает памяти Docker Desktop: увеличьте её в Settings → Resources (10–12 ГБ)
или запускайте при остановленном стенде (make down), затем make up.
EOF
}

case "${1:-}" in -h | --help) usage; exit 0 ;; esac
STAGES=("$@")
[ ${#STAGES[@]} -eq 0 ] && STAGES=("${ALL[@]}")
for s in "${STAGES[@]}"; do
  [[ " ${ALL[*]} " == *" $s "* ]] || { echo "Неизвестное задание: $s"; usage; exit 2; }
done
command -v docker >/dev/null && docker info >/dev/null 2>&1 \
  || { echo "Docker не запущен: open -a Docker, затем повторите."; exit 1; }
mkdir -p "$LOGS"

# Окружение без ключей стенда. Настройки читают ещё и ../.env (pydantic env_file), поэтому каждый
# секрет задан явно: пустой или одноразовый, как в CI (`export JWT_SECRET=$(openssl rand -hex 32)`).
# LiteLLM — на заведомо пустой порт: ни одного вызова модели (платного) из тестов.
JWT_ONCE=$(openssl rand -hex 32)
CTX_ONCE=$(openssl rand -hex 32)
clean_env() {
  env -i PATH="$PATH" HOME="$HOME" APP_ENV=test LOG_FORMAT=console \
    JWT_SECRET="$JWT_ONCE" AGENT_CONTEXT_KEY="$CTX_ONCE" SECRETS_KEY= \
    TELEGRAM_BOT_TOKEN= TELEGRAM_WEBHOOK_SECRET= TELEGRAM_MODE=disabled TELEGRAM_DRY_RUN=true \
    LITELLM_BASE_URL=http://127.0.0.1:9 LITELLM_API_KEY= LITELLM_MASTER_KEY=sk-test \
    ANTHROPIC_API_KEY= GEMINI_API_KEY= DOCLING_API_KEY= S3_ACCESS_KEY= S3_SECRET_KEY= \
    LANGFUSE_PUBLIC_KEY= LANGFUSE_SECRET_KEY= "$@"
}

stage_lint() {
  local image want
  image=$(sed -n 's|^FROM ghcr.io/astral-sh/uv:\([0-9.]*\).*|\1|p' "$ROOT/backend/Dockerfile")
  want=$(sed -n 's/^ *UV_VERSION: *"\{0,1\}\([0-9.]*\)"\{0,1\}/\1/p' "$ROOT/.github/workflows/ci.yml" | head -1)
  [ "$image" = "$want" ] || { echo "uv: $want в ci.yml, $image в backend/Dockerfile"; return 1; }
  (cd "$ROOT" && make check)
  (cd "$ROOT/backend" && uv run ruff check --config pyproject.toml ../scripts \
    && uv run ruff format --config pyproject.toml --check ../scripts)
  (cd "$ROOT" && make openapi && git diff --exit-code -- docs/api frontend/src/api) \
    || { echo "OpenAPI или клиент orval устарели — выполните make openapi и закоммитьте"; return 1; }
  local envfile
  envfile=$(mktemp)
  sed 's/CHANGE_ME/ci/; s/^IMAGE_TAG=$/IMAGE_TAG=ci/' "$ROOT/.env.example" >"$envfile"
  for override in dev prod; do
    docker compose -f "$ROOT/infra/docker-compose.yml" -f "$ROOT/infra/docker-compose.$override.yml" \
      --env-file "$envfile" --profile observability --profile backup config -q
  done
  rm -f "$envfile"
  # История текущей ветки, как в CI (checkout PR), а не все ветки клона: чужие ветки
  # (другие сессии) проверяются в своих PR.
  docker run --rm -v "$ROOT:/repo" -w /repo "$GITLEAKS_IMAGE" git --redact --log-opts=HEAD .
}

stage_integration() {
  local status=0
  "$ROOT/scripts/test_int_local.sh" || status=$?
  "$ROOT/scripts/test_int_local.sh" --down
  return $status
}

# По портам, а не по PID обёрток: `uv run`/`pnpm` запускают сервер дочерним процессом,
# и он переживал остановку обёртки (порт оставался занят до следующего прогона).
stop_port() {
  local pids
  pids=$(lsof -t -iTCP:"$1" -sTCP:LISTEN 2>/dev/null || true)
  [ -z "$pids" ] || kill $pids 2>/dev/null || true
}

e2e_cleanup() {
  stop_port "$E2E_API_PORT"
  stop_port "$E2E_WEB_PORT"
  docker rm -f "$E2E_PG" >/dev/null 2>&1 || true
}

stage_e2e() {
  for port in "$E2E_PG_PORT" "$E2E_API_PORT" "$E2E_WEB_PORT"; do
    ! lsof -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1 \
      || { echo "Порт $port занят: lsof -nP -iTCP:$port -sTCP:LISTEN"; return 1; }
  done
  # EXIT, а не RETURN: при сбое `set -e` завершает подоболочку задания, и RETURN не срабатывает.
  trap e2e_cleanup EXIT
  docker run -d --name "$E2E_PG" -p "127.0.0.1:${E2E_PG_PORT}:5432" -e POSTGRES_DB=railtech_e2e \
    -e POSTGRES_USER=railtech -e POSTGRES_PASSWORD="$PASS" "$PG_IMAGE" >/dev/null
  for _ in $(seq 1 30); do
    docker exec "$E2E_PG" pg_isready -U railtech -d railtech_e2e >/dev/null 2>&1 && break
    sleep 1
  done
  local db=(POSTGRES_HOST=127.0.0.1 POSTGRES_PORT="$E2E_PG_PORT" POSTGRES_DB=railtech_e2e
    POSTGRES_USER=railtech POSTGRES_PASSWORD="$PASS")
  local who=(E2E_MANAGER_EMAIL=manager@demo.local E2E_MANAGER_PASSWORD=ci-e2e-demo-42
    E2E_ADMIN_EMAIL=admin@demo.local E2E_ADMIN_PASSWORD=ci-e2e-boss-42)
  (
    cd "$ROOT/backend"
    clean_env "${db[@]}" uv run alembic upgrade head
    clean_env "${db[@]}" uv run python -m app seed-demo --manager-password ci-e2e-demo-42
    clean_env "${db[@]}" uv run python -m app create-admin --email admin@demo.local \
      --password ci-e2e-boss-42
  )
  (cd "$ROOT/backend" && clean_env "${db[@]}" uv run python -m app api --port "$E2E_API_PORT") \
    >"$LOGS/e2e-api.log" 2>&1 &
  for _ in $(seq 1 60); do
    curl -fsS "http://127.0.0.1:${E2E_API_PORT}/health" >/dev/null 2>&1 && break
    sleep 1
  done
  (cd "$ROOT/frontend" && pnpm build >"$LOGS/e2e-build.log" 2>&1)
  (cd "$ROOT/frontend" && VITE_API_PROXY_TARGET="http://127.0.0.1:${E2E_API_PORT}" \
    pnpm preview --port "$E2E_WEB_PORT" --strictPort) >"$LOGS/e2e-preview.log" 2>&1 &
  for _ in $(seq 1 30); do
    curl -fsS "http://127.0.0.1:${E2E_WEB_PORT}/" >/dev/null 2>&1 && break
    sleep 1
  done
  # Как в CI: свой Chromium Playwright (скачивается один раз, дальше — из кэша).
  (cd "$ROOT/frontend" && pnpm exec playwright install chromium)
  (cd "$ROOT/frontend" && env "${who[@]}" BASE_URL="http://localhost:${E2E_WEB_PORT}" pnpm e2e)
}

stage_audit() {
  (
    cd "$ROOT/backend"
    uv export --frozen --no-dev --no-emit-project --format requirements-txt -o "$LOGS/requirements.txt"
    uvx pip-audit@2.10.1 -r "$LOGS/requirements.txt" --no-deps --disable-pip --progress-spinner off
  )
  (cd "$ROOT/frontend" && pnpm audit --prod --audit-level high)
}

stage_build() {
  docker build -q --target prod -t railtech-backend:ci "$ROOT/backend" >/dev/null
  docker build -q --target prod -t railtech-frontend:ci "$ROOT/frontend" >/dev/null
  docker build -q --target backup -t railtech-backup:ci "$ROOT/backend" >/dev/null
  docker run --rm railtech-backup:ci /usr/lib/postgresql/16/bin/pg_dump --version \
    | grep -q "pg_dump (PostgreSQL) 16"
  docker run --rm railtech-backup:ci /app/ops/backup.sh --help >/dev/null
  docker run --rm railtech-backup:ci python -m app s3-mirror --help >/dev/null
}

RUN_STARTED=$(date -u +%Y-%m-%dT%H:%M:%S)
declare -a RESULT=()
failed=0
for s in "${STAGES[@]}"; do
  echo "━━ $s ━━ (лог: .ci-local/$s.log)"
  start=$(date +%s)
  # Не под `if`: там bash отключает `set -e` внутри задания, и шаги после сбоя шли бы дальше.
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
# Сборка образов и e2e делят память Docker Desktop со стендом: при нехватке Docker убивает
# контейнеры стенда (OOM, код 137). Сообщаем прямо, чтобы стенд не остался наполовину лежать.
killed=$(docker ps -a --filter "label=com.docker.compose.project=railtech" --filter status=exited \
  --format '{{.Names}}' | while read -r name; do
  [ "$(docker inspect -f '{{.State.OOMKilled}}' "$name")" = true ] \
    && [ "$(docker inspect -f '{{.State.FinishedAt}}' "$name")" \> "$RUN_STARTED" ] && echo "$name"
  true # без находок цикл вернул бы 1, и с pipefail скрипт вышел бы до итога
done)
if [ -n "$killed" ]; then
  echo "⚠ Стенд: Docker остановил по нехватке памяти — $(echo $killed | tr '\n' ' ')"
  echo "  Поднять обратно: make up. Чтобы не повторялось — Docker Desktop → Settings → Resources,"
  echo "  память 10–12 ГБ, или запускайте scripts/ci_local.sh при остановленном стенде (make down)."
fi
[ $failed -eq 0 ] && echo "Локальный CI зелёный — можно мержить." || echo "Есть сбои — смотрите логи выше."
exit $failed
