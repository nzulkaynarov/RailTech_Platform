#!/usr/bin/env bash
# Локальный CI — те же задания, что `.github/workflows/ci.yml`, на этом компьютере (Docker Desktop).
# Гейт мержа, пока GitHub Actions недоступен (решение владельца 2026-10-13, docs/DECISIONS.md).
# Платных вызовов моделей нет: eval-gate сюда не входит (только `make eval*` с согласия владельца).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ALL=(lint integration audit build)
GITLEAKS_IMAGE=ghcr.io/gitleaks/gitleaks:v8.30.1
LOGS="$ROOT/.ci-local"

usage() {
  cat <<EOF
Локальный CI (как .github/workflows/ci.yml): lint+unit, integration, audit, build.

  scripts/ci_local.sh                 все задания
  scripts/ci_local.sh lint audit      только выбранные
  scripts/ci_local.sh --help

Задания:
  lint         make check (ruff, mypy, unit), OpenAPI без диффа,
               compose-файлы валидны, gitleaks
  integration  scripts/test_int_local.sh — одноразовые Postgres и RustFS
  audit        pip-audit (prod-зависимости backend)
  build        образ backend (prod) и backup с проверкой pg_dump 17

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

# Окружение задания audit — как у раннера CI (`env -i` отсекает токены и ключи оболочки); от машины зависят PATH и HOME (uv, кэши).
clean_env() {
  env -i PATH="$PATH" HOME="$HOME" "$@"
}

stage_lint() {
  local image want
  image=$(sed -n 's|^FROM ghcr.io/astral-sh/uv:\([0-9.]*\).*|\1|p' "$ROOT/backend/Dockerfile")
  want=$(sed -n 's/^ *UV_VERSION: *"\{0,1\}\([0-9.]*\)"\{0,1\}/\1/p' "$ROOT/.github/workflows/ci.yml" | head -1)
  [ "$image" = "$want" ] || { echo "uv: $want в ci.yml, $image в backend/Dockerfile"; return 1; }
  (cd "$ROOT" && make check)
  (cd "$ROOT/backend" && uv run ruff check --config pyproject.toml ../scripts \
    && uv run ruff format --config pyproject.toml --check ../scripts)
  (cd "$ROOT" && make openapi && git diff --exit-code -- ../../packages/contracts/openapi/crm.yaml) \
    || { echo "OpenAPI устарел — выполните make openapi и закоммитьте"; return 1; }
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

stage_audit() {
  (
    cd "$ROOT/backend"
    clean_env uv export --frozen --no-dev --no-emit-project --no-emit-local --format requirements-txt -o "$LOGS/requirements.txt"
    clean_env uvx pip-audit@2.10.1 -r "$LOGS/requirements.txt" --no-deps --disable-pip --progress-spinner off
  )
}

stage_build() {
  docker build -q --target prod -t railtech-backend:ci "$ROOT/backend" >/dev/null
  docker build -q --target backup -t railtech-backup:ci "$ROOT/backend" >/dev/null
  docker run --rm railtech-backup:ci /usr/lib/postgresql/17/bin/pg_dump --version \
    | grep -q "pg_dump (PostgreSQL) 17"
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
# Сборка образов делит память Docker Desktop со стендом: при нехватке Docker убивает
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
