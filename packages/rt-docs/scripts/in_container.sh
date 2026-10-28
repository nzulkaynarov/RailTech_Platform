#!/usr/bin/env bash
# Выполнить команду в одноразовом контейнере тестов rt-docs (docker/test.Dockerfile): pango, harfbuzz и та же версия
# WeasyPrint, что в CI. Пакет и контракт documents монтируются только для чтения, сеть выключена (--network none):
# рендер не может сходить наружу даже при ошибке fetcher'а. Контейнер удаляется после команды (--rm).
# Образ: RT_DOCS_TEST_IMAGE или rt-docs-test:<хеш Dockerfile, pyproject.toml, uv.lock>; нет — собирается.
# RT_DOCS_TEST_PLATFORM (например, linux/amd64) — платформа образа и контейнера (проверка как в CI на Mac arm64).
set -euo pipefail

PKG="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="$(cd "$PKG/../.." && pwd)"

command -v docker >/dev/null && docker info >/dev/null 2>&1 \
  || { echo "Docker не запущен — нужен для тестов рендера rt-docs (pango, harfbuzz в контейнере)"; exit 1; }

hash_inputs() { cat "$PKG/docker/test.Dockerfile" "$PKG/pyproject.toml" "$PKG/uv.lock" | git hash-object --stdin | cut -c1-12; }
IMAGE="${RT_DOCS_TEST_IMAGE:-rt-docs-test:$(hash_inputs)}"
platform_args=()
[ -n "${RT_DOCS_TEST_PLATFORM:-}" ] && platform_args=(--platform "$RT_DOCS_TEST_PLATFORM")

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "rt-docs: сборка образа тестов $IMAGE"
  docker build ${platform_args[@]+"${platform_args[@]}"} -q -f "$PKG/docker/test.Dockerfile" -t "$IMAGE" "$PKG" >/dev/null
fi

exec docker run --rm --network none ${platform_args[@]+"${platform_args[@]}"} \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$PKG:/repo/packages/rt-docs:ro" \
  -v "$ROOT/packages/contracts/documents:/repo/packages/contracts/documents:ro" \
  -w /repo/packages/rt-docs \
  "$IMAGE" "$@"
