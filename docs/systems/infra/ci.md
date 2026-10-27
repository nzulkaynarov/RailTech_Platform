# CI ансамбля — пояснения к `.github/workflows/ci.yml`
Статус: действует · Владелец: лид · Обновлено: 2026-10-23

Workflow ансамбля — `.github/workflows/ci.yml` (GitHub читает только корневой `.github/`). Здесь — пояснения.

- **Ссылки на документацию** — `scripts/check-doc-links.sh` в задании gitleaks (DOCS-1): битые ссылки и пути вне `docs/` роняют CI.

- **Матрица по путям** (`dorny/paths-filter`): `apps/crm/**` → job'ы CRM (lint → unit → integration с Postgres 17 и RustFS → build образов), `packages/**` → `make contracts` + чистый diff `generated/`, `infra/**` → `docker compose config` и `caddy validate`, `apps/erp/**` / `apps/cabinet/**` → `make check-erp|cabinet` (до M1/M2 — пропуск внутри цели), `apps/eds/**` → job `eds` (`make check-eds`: ruff, mypy, pytest на service-контейнере PostgreSQL 17; локально — `scripts/ci_local.sh eds`). `legacy/b2b/**` не входит ни в один фильтр (ORCHESTRATOR §3.11).
- **gitleaks** — всегда, по истории ветки, с `.gitleaks.toml` (`legacy/` в allowlist).
- **`ci-ok`** — единственная обязательная проверка для защиты `main`: красная, если любой job упал или отменён; пропущенные (нет изменений) — зелёные.
- **Раннер**: переменная репозитория `CI_RUNNER` (Settings → Variables), например `self-hosted`; пусто — `ubuntu-latest` (DECISIONS 2026-10-13: self-hosted вне прода или минуты GitHub — решает владелец).
- Workflows внутри `apps/crm/.github/` не запускаются (не корень) — их шаги перенесены сюда с `working-directory: apps/crm`. E2E Playwright (`crm-e2e`) и аудит зависимостей (`crm-audit`) CRM перенесены. Локальный эквивалент — `make ci-local` (`scripts/ci_local.sh`, `--full` включает e2e и аудит); он — гейт мержа, пока Actions заблокирован биллингом (QUESTIONS Q-10).
- **CI → деплой** (W14-S4): `.github/workflows/deploy.yml` стартует по `workflow_run` после успешного workflow «CI» на push в `main` (schedule, ручной запуск CI и красный CI не деплоят), на том же sha ещё раз проверяет зелёную проверку «CI ok» (`checks: read`) и входит ли sha в `main`, собирает образы параллельно и ждёт одобрения владельца в environment `production`. Порядок и режимы (в том числе `build` — сборка без выкладки) — `docs/runbooks/deploy.md` §2.
