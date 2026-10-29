#!/usr/bin/env bash
# docker compose стенда гейта C1: проект rt-c1, .env в корне worktree (HTTP_PORT=8092, свои DEV-порты, PLATFORM_SSO_ENABLED=true).
ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$ROOT" || exit 1
exec docker compose -p rt-c1 -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env "$@"
