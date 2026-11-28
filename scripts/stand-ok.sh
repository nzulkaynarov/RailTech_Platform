#!/usr/bin/env bash
# Отметка «проверено на тестовом стенде»: статус коммита `stand-ok` = success на ровно этом sha (ВЫКЛ-3, решение владельца 2026-11-28:
# на прод ничего не идёт, пока не проверено на стенде). Ставит архитектор после приёмки sha на стенде; серверный таймер автовыкладки
# (infra/deploy/auto-deploy.sh) берёт только sha с зелёной «CI ok» И этим статусом. Нужен gh с правом записи статусов коммитов.
#   scripts/stand-ok.sh <полный sha | HEAD-ref>   поставить stand-ok
#   scripts/stand-ok.sh --revoke <sha>             снять (состояние failure: «на стенде не принят»)
# Репозиторий - STAND_OK_REPO (по умолчанию из `gh repo view`).
set -euo pipefail
state=success
if [[ "${1:-}" == "--revoke" ]]; then state=failure; shift; fi
[[ $# -eq 1 ]] || { echo "usage: stand-ok.sh [--revoke] <sha>" >&2; exit 2; }
ref="$1"
sha="$ref"
if ! [[ "$sha" =~ ^[0-9a-f]{40}$ ]]; then
  sha="$(git rev-parse --verify -q "${ref}^{commit}")" || { echo "stand-ok: '$ref' не коммит и не полный sha" >&2; exit 2; }
fi
repo="${STAND_OK_REPO:-$(gh repo view --json nameWithOwner --jq .nameWithOwner)}"
desc="принято на тестовом стенде"; [[ "$state" == success ]] || desc="на стенде не принято"
gh api -X POST "repos/$repo/statuses/$sha" -f state="$state" -f context=stand-ok -f description="$desc" --jq '"stand-ok: \(.state) на '"$sha"'"'
