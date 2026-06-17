#!/usr/bin/env bash
# Run Playwright E2E inside the official browser image against the LOCAL docker
# stack, with no Node on the host.
#
# Why socat: the SPA is a prod build with VITE_API_URL=http://localhost:8000
# baked in. Inside the Playwright container `localhost` is the container itself,
# so the browser's API calls would miss the host backend. We forward
# localhost:8000 and localhost:5173 inside the container to host.docker.internal,
# so both the baked API URL and the base URL resolve to the host stack.
#
# Usage: e2e/run-in-docker.sh <playwright args...>
#   e2e/run-in-docker.sh _probe.spec.ts --workers=1
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"   # frontend/
PW_VERSION="${PW_VERSION:-v1.48.0-jammy}"

docker run --rm \
  -v "$HERE":/work -w /work \
  --add-host host.docker.internal:host-gateway \
  -e E2E_BASE_URL="http://localhost:5173" \
  "mcr.microsoft.com/playwright:${PW_VERSION}" \
  bash -c '
    set -e
    if ! command -v socat >/dev/null 2>&1; then
      apt-get update -qq && apt-get install -y -qq socat >/dev/null
    fi
    socat TCP-LISTEN:8000,fork,reuseaddr TCP:host.docker.internal:8000 &
    socat TCP-LISTEN:5173,fork,reuseaddr TCP:host.docker.internal:5173 &
    sleep 2
    npx playwright test '"$*"'
  '
