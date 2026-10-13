#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# ci_local.sh — зеркало ВСЕХ джоб .github/workflows/ci.yml на машине разработчика.
#
# Зачем: GitHub-hosted раннеры лежат по биллингу (решение владельца 2026-08-17 —
# не оплачивать), поэтому PR мержатся по протоколу «те же 11 гейтов теми же
# командами локально» (Docs/dev/ops/merge-without-ci.md). Скрипт делает этот
# протокол воспроизводимым: один вызов, честные коды выхода, таблица для тела PR.
#
# Принципы (уроки 14-08 и 17-08):
#   * «цель отработала» ≠ «цель проверила»: каждый шаг возвращает код выхода
#     САМОЙ проверки, ничего не глотается через `|| true`;
#   * deps-lock: «файлы не изменились» при УПАВШЕМ pip-compile — ложный OK (файлы
#     просто не переписаны). Поэтому проверяем и код выхода контейнера, и mtime
#     обоих локов ПОСЛЕ компиляции;
#   * бэкенд-тесты идут в контейнере из СВЕЖЕГО образа (docker-build раньше
#     backend-test), иначе проверяется вчерашний набор зависимостей;
#   * шаги не прерывают друг друга — прогон идёт до конца, итог красный, если
#     красен хоть один. Так за один заход видно ВСЁ, что чинить.
#
# Использование:
#   make ci-local                     # всё
#   SKIP=deps-lock,docker-build make ci-local     # пропустить дорогие сетевые шаги
#   ONLY=api-contract,frontend-lint make ci-local # только перечисленные
#   REPORT=path.md                    # куда положить таблицу (по умолчанию .ci-local/report.md)
#
# Имена шагов == имена джоб в ci.yml (+ i18n-check — локальный бонус, в CI его нет:
# там свежесть .po ловит только компиляция каталога).
# ------------------------------------------------------------------------------
set -u
cd "$(dirname "$0")/.."
ROOT="$PWD"

SKIP="${SKIP:-}"
ONLY="${ONLY:-}"
REPORT="${REPORT:-.ci-local/report.md}"
LOGDIR=".ci-local/logs"
mkdir -p "$LOGDIR"
STARTED_AT="$(date +%s)"

declare -a NAMES=() STATUSES=() DURATIONS=() NOTES=()
FAILED=0

is_selected() {
  local name="$1"
  if [ -n "$ONLY" ]; then
    case ",$ONLY," in *",$name,"*) return 0 ;; *) return 1 ;; esac
  fi
  case ",$SKIP," in *",$name,"*) return 1 ;; esac
  return 0
}

# run_step <name> <note-on-success> <command...>
run_step() {
  local name="$1" note="$2"; shift 2
  if ! is_selected "$name"; then
    NAMES+=("$name"); STATUSES+=("⏭ skipped"); DURATIONS+=("—"); NOTES+=("пропущен по SKIP/ONLY")
    printf '\n\033[33m── %s: skipped\033[0m\n' "$name"
    return 0
  fi
  printf '\n\033[36m── %s\033[0m\n' "$name"
  local log="$LOGDIR/$name.log" t0 t1 rc
  t0=$(date +%s)
  ( "$@" ) >"$log" 2>&1
  rc=$?
  t1=$(date +%s)
  local dur="$(( (t1 - t0) / 60 ))м $(( (t1 - t0) % 60 ))с"
  if [ $rc -eq 0 ]; then
    NAMES+=("$name"); STATUSES+=("✅"); DURATIONS+=("$dur"); NOTES+=("$note")
    printf '\033[32m   ok (%s)\033[0m\n' "$dur"
  else
    FAILED=1
    NAMES+=("$name"); STATUSES+=("❌"); DURATIONS+=("$dur"); NOTES+=("exit $rc — см. $log")
    printf '\033[31m   FAIL exit %s (%s) — %s\033[0m\n' "$rc" "$dur" "$log"
    tail -25 "$log" | sed 's/^/   │ /'
  fi
}

# ---- шаги --------------------------------------------------------------------

step_i18n_symmetry() { python3 scripts/check_i18n_symmetry.py; }

step_backend_lint() { make lint-backend; }

# docker-build ДО backend-test: тесты должны идти в контейнере из свежего образа.
step_docker_build() {
  docker compose build backend frontend
  docker compose up -d --no-deps backend celery-worker celery-worker-ai celery-beat frontend
  # дождаться, пока backend снова healthy — иначе первый exec упадёт на «container restarting»
  for _ in $(seq 1 30); do
    if [ "$(docker inspect -f '{{.State.Health.Status}}' railtech_backend 2>/dev/null)" = "healthy" ]; then return 0; fi
    sleep 3
  done
  echo "backend не стал healthy за 90 с после пересборки"; return 1
}

step_migration_check() {
  docker compose exec -T backend python manage.py makemigrations --check --dry-run
}

step_backend_test() {
  docker compose exec -T backend python manage.py compilemessages >/dev/null
  # Как в ci.yml: чистая БД + миграции (--create-db), покрытие ≥ 70, locmem-почта.
  docker compose exec -T -e EMAIL_BACKEND=django.core.mail.backends.locmem.EmailBackend backend \
    pytest --create-db --cov=. --cov-report=term --cov-fail-under=70 -q -p no:cacheprovider
}

# Сравниваем НЕ с git-индексом, а со снимком файлов ДО регенерации: иначе корректные, но ещё
# не закоммиченные schema.json/schema.d.ts всегда давали «дрейф» (в CI сравнение с коммитом —
# то же самое по смыслу: «регенерация ничего не меняет»). Регенерированные файлы остаются
# в дереве — при красном шаге их просто нужно закоммитить.
_snapshot_differs() {
  local snap_dir="$1"; shift
  local f changed=0
  for f in "$@"; do
    if ! cmp -s "$f" "$snap_dir/$(echo "$f" | tr '/' '_')"; then echo "   изменился: $f"; changed=1; fi
  done
  return $changed
}
_snapshot_take() {
  local snap_dir="$1"; shift
  mkdir -p "$snap_dir"
  local f; for f in "$@"; do cp "$f" "$snap_dir/$(echo "$f" | tr '/' '_')"; done
}

step_api_contract() {
  local files=(backend/schema.json frontend/src/api/schema.d.ts) snap=".ci-local/snap-api"
  _snapshot_take "$snap" "${files[@]}"
  docker compose exec -T backend python manage.py spectacular --format openapi-json --file schema.json >/dev/null 2>&1
  (cd frontend && npm run gen:api-types >/dev/null)
  if ! _snapshot_differs "$snap" "${files[@]}"; then
    echo "OpenAPI schema / schema.d.ts устарели — регенерированные файлы лежат в дереве, закоммить их"; return 1
  fi
}

step_frontend_lint() { (cd frontend && npm run lint && npm run lint:tsc); }
step_frontend_test() { (cd frontend && npx vitest run); }
step_frontend_build() { (cd frontend && npm run build); }

step_security() { make security; }

step_i18n_check() { make i18n-check; }

# deps-lock: linux py3.12 + gcc + libpq-dev + pip-tools==7.5.3, обе компиляции как в джобе.
# Проверка тройная: код выхода контейнера, mtime обоих локов ПОСЛЕ старта шага, сравнение со снимком.
step_deps_lock() {
  local t_start; t_start=$(date +%s)
  local files=(backend/requirements.txt backend/requirements-dev.txt) snap=".ci-local/snap-deps"
  _snapshot_take "$snap" "${files[@]}"
  docker run --rm -v "$ROOT/backend:/w" -w /w python:3.12 bash -c '
    set -e
    export PIP_DEFAULT_TIMEOUT=60 PIP_RETRIES=8 PIP_DISABLE_PIP_VERSION_CHECK=1
    apt-get update -qq >/dev/null
    apt-get install -y -qq gcc libpq-dev >/dev/null 2>&1
    pip install -q "pip-tools==7.5.3"
    pip-compile --quiet --generate-hashes --no-strip-extras --output-file=requirements.txt requirements.in
    pip-compile --quiet --generate-hashes --no-strip-extras -c requirements.txt --output-file=requirements-dev.txt requirements-dev.in
  ' || { echo "pip-compile упал (обычно сеть Docker VM — перезапустить Docker Desktop и повторить: SKIP всего кроме deps-lock)"; return 1; }
  local f m
  for f in backend/requirements.txt backend/requirements-dev.txt; do
    m=$(stat -f %m "$f" 2>/dev/null || stat -c %Y "$f")
    if [ "$m" -lt "$t_start" ]; then
      echo "$f НЕ переписан компиляцией (mtime старее старта шага) — результат недостоверен"; return 1
    fi
  done
  if ! _snapshot_differs "$snap" "${files[@]}"; then
    echo "requirements*.txt разошлись с requirements*.in — перекомпилированные локи лежат в дереве, закоммить их"; return 1
  fi
}

# ---- порядок = зависимости ---------------------------------------------------
run_step i18n-symmetry   "ru/en ключи симметричны"                          step_i18n_symmetry
run_step backend-lint    "flake8 · black · isort (пины CI, из корня)"        step_backend_lint
run_step docker-build    "backend + frontend образы, контейнеры пересозданы" step_docker_build
run_step migration-check "makemigrations --check"                            step_migration_check
run_step backend-test    "pytest --create-db, покрытие ≥ 70 %"               step_backend_test
run_step api-contract    "spectacular + gen:api-types, дрейфа нет"           step_api_contract
run_step frontend-lint   "eslint · tsc -b"                                   step_frontend_lint
run_step frontend-test   "vitest"                                            step_frontend_test
run_step frontend-build  "vite build"                                        step_frontend_build
run_step security        "pip-audit · npm audit --omit=dev"                  step_security
run_step deps-lock       "pip-compile 7.5.3 в python:3.12, локи переписаны, дрейфа нет" step_deps_lock
run_step i18n-check      "каталог .po свеж (локальный бонус, в CI нет)"      step_i18n_check

# ---- отчёт -------------------------------------------------------------------
HEAD_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "?")
TOTAL=$(( $(date +%s) - STARTED_AT ))
mkdir -p "$(dirname "$REPORT")"
{
  echo "## Прогон гейтов локально — зеркало \`ci.yml\` (\`make ci-local\`)"
  echo
  echo "Коммит \`$HEAD_SHA\`, $(date '+%Y-%m-%d %H:%M'), всего $(( TOTAL / 60 ))м $(( TOTAL % 60 ))с. CI GitHub-hosted не стартует (биллинг), протокол — \`Docs/dev/ops/merge-without-ci.md\`."
  echo
  echo "| Джоба CI | Результат | Время | Примечание |"
  echo "|---|---|---|---|"
  for i in "${!NAMES[@]}"; do
    echo "| ${NAMES[$i]} | ${STATUSES[$i]} | ${DURATIONS[$i]} | ${NOTES[$i]} |"
  done
} > "$REPORT"

echo
cat "$REPORT"
echo
if [ $FAILED -ne 0 ]; then
  printf '\033[31mИТОГ: КРАСНЫЙ — есть упавшие гейты, мержить нельзя.\033[0m\n'; exit 1
fi
printf '\033[32mИТОГ: ЗЕЛЁНЫЙ — таблица выше готова для вставки в тело PR (%s).\033[0m\n' "$REPORT"
