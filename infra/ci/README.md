# infra/ci

Workflow ансамбля — `.github/workflows/ci.yml` (GitHub читает только корневой `.github/`). Здесь — пояснения.

- **Матрица по путям** (`dorny/paths-filter`): `apps/crm/**` → job'ы CRM (lint → unit → integration с Postgres 17 и RustFS → build образов), `packages/**` → `make contracts` + чистый diff `generated/`, `infra/**` → `docker compose config` и `caddy validate`, `apps/erp/**` / `apps/cabinet/**` → `make check-erp|cabinet` (до M1/M2 — пропуск внутри цели). `legacy/b2b/**` не входит ни в один фильтр (ORCHESTRATOR §3.11).
- **gitleaks** — всегда, по истории ветки, с `.gitleaks.toml` (`legacy/` в allowlist).
- **`ci-ok`** — единственная обязательная проверка для защиты `main`: красная, если любой job упал или отменён; пропущенные (нет изменений) — зелёные.
- **Раннер**: переменная репозитория `CI_RUNNER` (Settings → Variables), например `self-hosted`; пусто — `ubuntu-latest` (DECISIONS 2026-10-13: self-hosted вне прода или минуты GitHub — решает владелец).
- Workflows внутри `apps/crm/.github/` не запускаются (не корень) — их шаги перенесены сюда с `working-directory: apps/crm`. E2E Playwright и `pip-audit`/`pnpm audit` CRM в ансамблевый CI пока не перенесены (отмечено в PROGRESS).
