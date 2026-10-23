#!/usr/bin/env bash
# Проверка старта образов прода под эмуляцией CPU qemu64 (S0-7, ADR-0013 п. 8).
#
# Прод-VPS (Eskiz, KVM) отдают «QEMU Virtual CPU version 2.5+»: базовый x86-64 (v1), без SSE4.2/SSSE3/POPCNT/AVX
# (docs/runbooks/servers.md, «CPU прод-VPS»). Образ, собранный под x86-64-v2 (Wolfi, numpy 2.4+, ClickHouse), на нём падает.
# Раннеры GitHub и машины разработчиков такого CPU не имеют, поэтому здесь каждая команда проверки образа исполняется
# внутри контейнера через статический qemu-x86_64 в user-mode с моделью CPU qemu64:
#   docker run --init --platform linux/amd64 -v <qemu-x86_64-static>:/rt-qemu --entrypoint sh <образ> \
#     -c 'exec /rt-qemu -cpu qemu64 -L / "$(command -v <программа>)" <аргументы>'
# -L / — корень образа служит sysroot: эмулируется и сама программа, и её ld.so/libc/нативные модули из образа.
# --init обязателен: qemu при SIGILL гостя убивает себя тем же сигналом, а PID 1 контейнера сигналы без обработчика
# игнорирует — без --init проверка зависала бы вместо падения.
#
# Команды проверки каждого образа — общая таблица infra/deploy/cpu-baseline-rules.sh (её же использует деплой на сервере).
# Падение («Illegal instruction», «x86-64-v2», «X86_V2») — ненулевой код и имя образа в сообщении.
#
# Использование:
#   scripts/qemu_cpu_check.sh list [built|pulled|all]   имена образов (по умолчанию all)
#   scripts/qemu_cpu_check.sh params <имя>              контекст сборки образа для CI (key=value, для $GITHUB_OUTPUT)
#   scripts/qemu_cpu_check.sh ref <имя>                 ссылка на сторонний образ из infra/compose/base.yml (caddy, redis, rustfs)
#   scripts/qemu_cpu_check.sh build <имя>               собрать linux/amd64 образ rt-cpu-check/<имя>:amd64
#   scripts/qemu_cpu_check.sh check <имя> [образ]       проверить образ (по умолчанию собранный build / подтянутый pull)
#   scripts/qemu_cpu_check.sh run [имя…]                собрать, проверить и удалить образы по одному (без имён — все)
#   scripts/qemu_cpu_check.sh all [--skip-missing]      проверить все образы; --skip-missing — пропуск (не «ok») без образа
#   scripts/qemu_cpu_check.sh selftest                  механика ловит реальные проблемы (Wolfi, numpy 2.4) и пропускает здоровое
#   scripts/qemu_cpu_check.sh qemu-path                 путь к qemu-x86_64-static (при первом запуске извлекается из Docker)
# Переменные: RT_QEMU_X86_64 (свой статический qemu-x86_64), RT_CPU_CACHE (куда кэшировать qemu),
#             RT_CPU_PROBE_TIMEOUT (секунд на одну команду, по умолчанию 900).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=infra/deploy/cpu-baseline-rules.sh
source "$ROOT/infra/deploy/cpu-baseline-rules.sh"

QEMU_SRC_IMAGE="${RT_QEMU_SRC_IMAGE:-debian:bookworm-slim}"
PROBE_TIMEOUT="${RT_CPU_PROBE_TIMEOUT:-900}"
CHECK_REPO="rt-cpu-check"

say() { printf '▸ %s\n' "$*" >&2; }
fail() { printf '✘ %s\n' "$*" >&2; exit 1; }

# ─── Таблица сборки: имя -> «контекст|Dockerfile|target|область кэша». Те же контексты, что в .github/workflows/deploy.yml ─────
# (согласованность проверяет infra/deploy/tests/cpu-baseline-test.sh). Область кэша = scope buildx cache в deploy.yml.
build_spec() {
  case "$1" in
    rt-crm-backend) echo "apps/crm/backend||prod|crm-backend" ;;
    rt-crm-frontend) echo "apps/crm/frontend||prod|crm-frontend" ;;
    rt-erp-backend) echo "apps/erp/backend|||erp-backend" ;;
    rt-erp-frontend) echo "apps/erp/frontend|||erp-frontend" ;;
    rt-cabinet) echo "apps/cabinet|||cabinet" ;;
    rt-litellm) echo "infra/ai/litellm|||litellm" ;;
    rt-platform-bff) echo "apps/platform/bff||prod|platform-bff" ;;
    rt-platform-web) echo "apps/platform/web||prod|platform-web" ;;
    rt-db-postgres) echo "infra/db|Dockerfile.postgres||db-postgres" ;;
    rt-db-backup) echo "infra/db|Dockerfile.backup||db-backup" ;;
    *) return 1 ;;
  esac
}

# Сторонние образы прода (не собираются, подтягиваются): ссылка берётся из compose, чтобы версия не расходилась.
pulled_ref() {
  local name="$1" prefix
  case "$name" in
    caddy) prefix="caddy:" ;;
    redis) prefix="redis:" ;;
    rustfs) prefix="rustfs/rustfs:" ;;
    rc) prefix="rustfs/rc:" ;;
    *) return 1 ;;
  esac
  sed -n "s|^[[:space:]]*image:[[:space:]]*\(${prefix}[^[:space:]]*\)[[:space:]]*\$|\1|p" "$ROOT/infra/compose/base.yml" | head -n 1
}

list_names() {
  local kind="${1:-all}" n
  while read -r n; do
    case "$kind" in
      built) if build_spec "$n" >/dev/null 2>&1; then echo "$n"; fi ;;
      pulled) if pulled_ref "$n" >/dev/null 2>&1; then echo "$n"; fi ;;
      all) echo "$n" ;;
      *) fail "list: built | pulled | all" ;;
    esac
  done < <(cpu_baseline_names)
}

default_image() { echo "$CHECK_REPO/$1:amd64"; }

# alias_amd64 <внешний образ> <локальный тег>: linux/amd64-вариант под отдельным тегом. Не `docker pull --platform <образ>`:
# на Mac arm64 он перенёс бы тег, например caddy:2.11.7-alpine, на amd64 и испортил бы чужие стенды. Берём digest amd64-манифеста
# и тянем по нему — тег внешнего образа не трогается.
alias_amd64() {
  local ref="$1" tag="$2" digest repo
  # Репозиторий без тега и digest: «имя:тег@sha256:…» (закреплённый образ, например rustfs/rc) и «имя:тег».
  repo="${ref%@*}"; repo="${repo%:*}"
  digest="$(docker buildx imagetools inspect "$ref" --format '{{range .Manifest.Manifests}}{{if and (eq .Platform.OS "linux") (eq .Platform.Architecture "amd64")}}{{.Digest}}{{end}}{{end}}')"
  [[ "$digest" == sha256:* ]] || return 1
  docker pull -q "$repo@$digest" >/dev/null
  docker tag "$repo@$digest" "$tag"
}

# ─── qemu-x86_64 (статический) ─────────────────────────────────────────────────────────────────────────────────────────────
qemu_bin() {
  if [[ -n "${RT_QEMU_X86_64:-}" ]]; then
    [[ -x "$RT_QEMU_X86_64" ]] || fail "RT_QEMU_X86_64=$RT_QEMU_X86_64 не исполняемый файл"
    echo "$RT_QEMU_X86_64"
    return
  fi
  local dir="${RT_CPU_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/rt-platform}" bin tmp
  bin="$dir/qemu-x86_64-static"
  if [[ ! -x "$bin" ]]; then
    say "qemu-x86_64-static: извлекаю из пакета qemu-user-static ($QEMU_SRC_IMAGE), один раз → $bin"
    mkdir -p "$dir"
    local uid gid
    uid="$(id -u)"
    gid="$(id -g)"
    docker run --rm --platform linux/amd64 -v "$tmp:/out" "$QEMU_SRC_IMAGE" sh -c \
      "set -e
       apt-get update -qq >/dev/null
       apt-get install -y -qq --no-install-recommends qemu-user-static >/dev/null
       cp /usr/bin/qemu-x86_64-static /out/
       chmod 755 /out/qemu-x86_64-static
       chown $uid:$gid /out/qemu-x86_64-static 2>/dev/null || true" >&2 \
      || { rm -rf "$tmp"; fail "не удалось получить qemu-x86_64-static из $QEMU_SRC_IMAGE"; }
    chmod 755 "$tmp/qemu-x86_64-static" 2>/dev/null || true
    mv "$tmp/qemu-x86_64-static" "$bin"
    rmdir "$tmp"
  fi
  echo "$bin"
}

# ─── Запуск одной команды под qemu64 ───────────────────────────────────────────────────────────────────────────────────────
PROBE_OUT=""
# probe_one <образ> <программа> <аргументы...> — 0 если команда прошла под qemu64; вывод — в PROBE_OUT
probe_one() {
  local image="$1" entry="$2" qemu cname outf rc=0 ticks=0
  shift 2
  qemu="$(qemu_bin)"
  cname="rt-cpu-$$-$RANDOM"
  outf="$(mktemp)"
  docker run --rm --init --name "$cname" --platform linux/amd64 --network none --ulimit core=0 \
    -e LITELLM_LOCAL_MODEL_COST_MAP=True -v "$qemu:/rt-qemu:ro" --entrypoint sh "$image" -c \
    'p="$(command -v "$1")" || { echo "в образе нет программы $1" >&2; exit 127; }; shift; exec /rt-qemu -cpu qemu64 -L / "$p" "$@"' \
    _ "$entry" "$@" >"$outf" 2>&1 &
  local pid=$!
  # Таймаут — опросом в этом же shell, без фонового `sleep`: сирота-sleep держал бы stdout и вешал `| tail`, `$(...)`.
  while kill -0 "$pid" 2>/dev/null; do
    if [[ $ticks -ge $((PROBE_TIMEOUT * 5)) ]]; then
      echo "таймаут ${PROBE_TIMEOUT} с" >>"$outf"
      docker kill "$cname" >/dev/null 2>&1 || true
      break
    fi
    sleep 0.2
    ticks=$((ticks + 1))
  done
  wait "$pid" || rc=$?
  PROBE_OUT="$(cat "$outf")"
  rm -f "$outf"
  return "$rc"
}

# Причина отказа по выводу и коду выхода
reason_of() {
  local rc="$1" out="$2"
  if [[ "$rc" == 132 || "$out" == *"Illegal instruction"* ]]; then
    echo "illegal instruction (код, которого нет в базовом x86-64)"
  elif [[ "$out" == *"x86-64-v2"* || "$out" == *"X86_V2"* || "$out" == *"x86-64-v3"* ]]; then
    echo "образ требует x86-64-v2 или выше"
  elif [[ "$rc" == 127 ]]; then
    echo "программа не найдена в образе (правило устарело?)"
  elif [[ "$out" == *"таймаут"* ]]; then
    echo "таймаут эмуляции"
  else
    echo "команда завершилась с кодом $rc"
  fi
}

CHECK_FAILED=0
CUR_NAME="" CUR_IMAGE=""
# Обработчик правил: запускает команду и печатает результат
rule_probe() {
  local rc=0 reason
  probe_one "$CUR_IMAGE" "$@" || rc=$?
  if [[ $rc -eq 0 ]]; then
    printf '✔ cpu-qemu64: %-18s %s\n' "$CUR_NAME" "$*" >&2
  else
    CHECK_FAILED=1
    reason="$(reason_of "$rc" "$PROBE_OUT")"
    printf '✘ cpu-qemu64: %s (%s) — %s\n    команда: %s\n%s\n' "$CUR_NAME" "$CUR_IMAGE" "$reason" "$*" \
      "$(printf '%s' "$PROBE_OUT" | tail -n 6 | sed 's/^/    /')" >&2
    if [[ -n "${GITHUB_ACTIONS:-}" ]]; then
      printf '::error title=CPU qemu64: %s::%s — %s (команда: %s)\n' "$CUR_NAME" "$CUR_NAME" "$reason" "$*" >&2
    fi
  fi
  return 0
}

# image_arch <образ> -> «os/arch» или пусто, если образа нет
image_platform() { docker image inspect -f '{{.Os}}/{{.Architecture}}' "$1" 2>/dev/null || true; }

# check_image <имя> <образ> <skip_missing:0|1> — 0 ок, 1 падение, 2 пропуск (нет образа или не amd64)
check_image() {
  local name="$1" image="$2" skip="$3" plat
  cpu_baseline_names | grep -qx "$name" || fail "нет правила для образа '$name' (infra/deploy/cpu-baseline-rules.sh)"
  plat="$(image_platform "$image")"
  if [[ "$plat" != linux/amd64 ]] && ! build_spec "$name" >/dev/null 2>&1; then
    say "подтягиваю $(pulled_ref "$name") (linux/amd64) как $image"
    alias_amd64 "$(pulled_ref "$name")" "$image" || fail "не удалось подтянуть $(pulled_ref "$name")"
    plat="$(image_platform "$image")"
  fi
  if [[ -z "$plat" ]]; then
    [[ "$skip" == 1 ]] || fail "нет образа $image — сначала: scripts/qemu_cpu_check.sh build $name"
    say "пропуск $name: образа $image нет (собрать: scripts/qemu_cpu_check.sh build $name)"
    return 2
  fi
  if [[ "$plat" != linux/amd64 ]]; then
    [[ "$skip" == 1 ]] || fail "образ $image — $plat, нужен linux/amd64 (qemu64 эмулирует x86-64): scripts/qemu_cpu_check.sh build $name"
    say "пропуск $name: образ $image — $plat, проверка только для linux/amd64 (пересобрать: scripts/qemu_cpu_check.sh build $name)"
    return 2
  fi
  CUR_NAME="$name" CUR_IMAGE="$image" CHECK_FAILED=0
  cpu_baseline_rules "$name" rule_probe
  [[ $CHECK_FAILED -eq 0 ]]
}

cmd_build() {
  local name="${1:?build <имя>}" spec ctx file target args=()
  spec="$(build_spec "$name")" || fail "'$name' не собирается из репозитория (list built)"
  IFS='|' read -r ctx file target _ <<<"$spec"
  [[ -z "$file" ]] || args+=(-f "$ROOT/$ctx/$file")
  [[ -z "$target" ]] || args+=(--target "$target")
  say "сборка $name (linux/amd64, $ctx) → $CHECK_REPO/$name:amd64"
  docker build --platform linux/amd64 "${args[@]+"${args[@]}"}" -t "$CHECK_REPO/$name:amd64" "$ROOT/$ctx"
}

cmd_params() {
  local name="${1:?params <имя>}" spec ctx file target scope
  spec="$(build_spec "$name")" || fail "'$name' не собирается из репозитория (list built)"
  IFS='|' read -r ctx file target scope <<<"$spec"
  echo "context=$ctx"
  echo "file=${file:+$ctx/$file}"
  echo "target=$target"
  echo "cache_scope=$scope"
  echo "tag=$CHECK_REPO/$name:amd64"
}

cmd_all() {
  local skip=0 name rc failed=() skipped=() okn=0 image
  [[ "${1:-}" != --skip-missing ]] || skip=1
  if [[ $skip -eq 1 ]] && ! (qemu_bin >/dev/null 2>&1); then
    say "cpu-qemu64: ПРОПУЩЕНО целиком — нет qemu-x86_64-static и не удалось извлечь из Docker (нужна сеть и linux/amd64 в Docker); это не «ok». Задайте RT_QEMU_X86_64=<путь>"
    return 0
  fi
  while read -r name; do
    image="$(default_image "$name")"
    rc=0
    check_image "$name" "$image" "$skip" || rc=$?
    case "$rc" in
      0) okn=$((okn + 1)) ;;
      2) skipped+=("$name") ;;
      *) failed+=("$name") ;;
    esac
  done < <(list_names all)
  say "cpu-qemu64: проверено $okn, пропущено ${#skipped[@]}${skipped[*]:+ (${skipped[*]})}, упало ${#failed[@]}${failed[*]:+ (${failed[*]})}"
  [[ ${#failed[@]} -eq 0 ]] || exit 1
  [[ ${#skipped[@]} -eq 0 ]] || say "cpu-qemu64: пропущенное НЕ проверено — это не «ok»; соберите образы linux/amd64 (scripts/qemu_cpu_check.sh build <имя>)"
}

# run [имя…] — собрать (linux/amd64), проверить и удалить образ, по одному (диск и память Docker); без имён — все.
# RT_CPU_KEEP=1 оставляет образы. Падение любого образа — код 1 после прохода по всем.
cmd_run() {
  local names=("$@") name failed=() rc
  [[ ${#names[@]} -gt 0 ]] || while read -r name; do names+=("$name"); done < <(list_names all)
  for name in "${names[@]}"; do
    if build_spec "$name" >/dev/null 2>&1; then
      cmd_build "$name" >&2 || { failed+=("$name"); continue; }
    fi
    rc=0
    check_image "$name" "$(default_image "$name")" 0 || rc=$?
    [[ $rc -eq 0 ]] || failed+=("$name")
    [[ "${RT_CPU_KEEP:-}" == 1 ]] || docker image rm -f "$(default_image "$name")" >/dev/null 2>&1 || true
  done
  [[ ${#failed[@]} -eq 0 ]] || fail "cpu-qemu64: не прошли: ${failed[*]}"
  say "cpu-qemu64: все образы (${names[*]}) стартуют под qemu64"
}

# ─── Самопроверка механики: она обязана падать на заведомо плохом и проходить на заведомо хорошем ─────────────────────────────
selftest_image() { # <тег> <Dockerfile из stdin>
  docker build -q --platform linux/amd64 -t "$1" - >/dev/null
}

expect_fail() { # <описание> <образ> <шаблон причины> <программа> <аргументы...>
  local what="$1" image="$2" pattern="$3" rc=0
  shift 3
  probe_one "$image" "$@" || rc=$?
  if [[ $rc -eq 0 ]]; then
    printf '✘ selftest: %s — ожидалось падение под qemu64, а проверка прошла (механика не ловит проблему)\n' "$what" >&2
    return 1
  fi
  if ! printf '%s' "$PROBE_OUT" | grep -Eiq "$pattern" && [[ "$rc" != 132 ]]; then
    printf '✘ selftest: %s — упало, но не по причине CPU (код %s):\n%s\n' "$what" "$rc" "$(printf '%s' "$PROBE_OUT" | tail -n 6 | sed 's/^/    /')" >&2
    return 1
  fi
  printf '✔ selftest: %s — падает, как на прод-CPU (%s)\n' "$what" "$(reason_of "$rc" "$PROBE_OUT")" >&2
}

cmd_selftest() {
  local bad=0 ok_image="rt-cpu-selftest/numpy-ok:amd64" bad_image="rt-cpu-selftest/numpy-new:amd64" wolfi="rt-cpu-selftest/wolfi:amd64" rc=0
  qemu_bin >/dev/null

  selftest_image "$ok_image" <<'EOF'
FROM python:3.12-slim-bookworm
RUN pip install --no-cache-dir --disable-pip-version-check "numpy<2.4"
EOF
  selftest_image "$bad_image" <<'EOF'
FROM python:3.12-slim-bookworm
RUN pip install --no-cache-dir --disable-pip-version-check "numpy>=2.4"
EOF
  alias_amd64 cgr.dev/chainguard/wolfi-base:latest "$wolfi"

  # Здоровое проходит (контроль: иначе «падает всё» выглядело бы как успех отрицательных тестов).
  probe_one "$ok_image" python -c "$CPU_PY_NATIVE" || rc=$?
  if [[ $rc -ne 0 ]]; then
    printf '✘ selftest: numpy<2.4 должен проходить под qemu64, а упал (%s):\n%s\n' "$(reason_of "$rc" "$PROBE_OUT")" "$(printf '%s' "$PROBE_OUT" | tail -n 6 | sed 's/^/    /')" >&2
    bad=1
  else
    printf '✔ selftest: numpy<2.4 проходит под qemu64 (контроль)\n' >&2
  fi
  # numpy 2.4+ собран с базой x86-64-v2 — RuntimeError при import; Wolfi (официальный LiteLLM) — SIGILL в ld.so/libc.
  expect_fail "numpy 2.4+ (колёса под базу x86-64-v2)" "$bad_image" 'X86_V2|x86-64-v2|Illegal instruction' python -c "$CPU_PY_NATIVE" || bad=1
  expect_fail "Wolfi, база официального образа LiteLLM (glibc под x86-64-v2)" "$wolfi" 'x86-64-v2|Illegal instruction' /bin/busybox true || bad=1

  # Таймаут: зависшая команда прерывается, а после проверки не остаётся дочерних процессов (сирота `sleep` держал бы stdout
  # и вешал `make cpu-selftest | tail`).
  local t0=$SECONDS kids
  rc=0
  PROBE_TIMEOUT=2 probe_one "$ok_image" python -c "import time; time.sleep(60)" || rc=$?
  kids="$(pgrep -P $$ || true)"
  if [[ $rc -eq 0 || "$PROBE_OUT" != *"таймаут"* || $((SECONDS - t0)) -gt 20 || -n "$kids" ]]; then
    printf '✘ selftest: таймаут проверки не сработал или оставил процессы (rc=%s, %s с, дочерние: %s)\n' "$rc" "$((SECONDS - t0))" "${kids:-нет}" >&2
    bad=1
  else
    printf '✔ selftest: таймаут прерывает зависшую команду и не оставляет процессов\n' >&2
  fi

  docker image rm -f "$ok_image" "$bad_image" "$wolfi" >/dev/null 2>&1 || true
  [[ $bad -eq 0 ]] || fail "самопроверка механики qemu64 не пройдена"
  say "selftest: механика qemu64 ловит x86-64-v2 и не ругается на здоровый образ"
}

case "${1:-}" in
  list) list_names "${2:-all}" ;;
  params) shift; cmd_params "$@" ;;
  ref) pulled_ref "${2:?ref <имя>}" || fail "'$2' — не сторонний образ (list pulled)" ;;
  build) shift; cmd_build "$@" ;;
  check)
    name="${2:?check <имя> [образ]}"
    check_image "$name" "${3:-$(default_image "$name")}" 0 || exit 1
    ;;
  all) shift; cmd_all "$@" ;;
  run) shift; cmd_run "$@" ;;
  selftest) cmd_selftest ;;
  qemu-path) qemu_bin ;;
  -h | --help | help | "") sed -n '2,/^set -euo/p' "${BASH_SOURCE[0]}" | sed '$d' | sed 's/^# \{0,1\}//' ;;
  *) fail "неизвестная команда '$1' (scripts/qemu_cpu_check.sh --help)" ;;
esac
