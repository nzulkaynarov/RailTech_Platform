# PROGRESS — состояние работ по вехам

Обновляется в конце каждой сессии агента (ORCHESTRATOR §4, §7). Веха закрыта только после отметки
владельца в столбце «Гейт».

## Вехи

| Веха | Содержание | Статус | Гейт владельца |
|---|---|---|---|
| M0 | Скелет ансамбля: монорепозиторий, контракт v0, compose, CI, ADR, токены дизайна | **в работе** (2 / 6 задач) | — |
| M1 | ERP выделена из B2B | не начата | — |
| M2 | Cabinet | не начата | — |
| M3 | Связка CRM ↔ ERP | не начата (M3-CRM-01/02/05/08 можно начинать параллельно с M1) | — |
| M4 | Снабжение и склад | не начата | — |
| M5 | Прод и пилот | не начата | — |

## M0 — задачи

| ID | Задача | Статус | Ветка / PR | Что осталось |
|---|---|---|---|---|
| M0-INF-01 | Монорепозиторий с историей, тег `b2b-final`, корневые Makefile / .editorconfig / .gitignore / pre-commit с gitleaks | **готово** 2026-10-13 | `m0/infra-01-monorepo` | PR в `main`; владелец включает защиту `main` после M0-INF-04 |
| M0-INF-02 | `packages/contracts`: OpenAPI ERP v0, события, MCP, SSO; `make contracts` | **готово** 2026-10-13 | `m0/infra-02-contracts` | PR; проверка diff `generated/` в CI — M0-INF-04 |
| M0-INF-03 | `infra/compose`: Postgres (2 базы), Redis, LiteLLM, Langfuse, RustFS, Caddy на `*.localhost`; `make up` | не начата (зависит от M0-INF-01) | — | — |
| M0-INF-04 | CI: один workflow, матрица по путям, `legacy/b2b` исключён | не начата (зависит от M0-INF-01) | — | workflows из `apps/crm/.github/` на уровне корня не запускаются — перенести в `.github/` корня с фильтрами по путям |
| M0-DOC-01 | ADR 0001–0007 proposed, `apps/erp/CLAUDE.md` и `apps/cabinet/CLAUDE.md` заготовки | частично: ADR и PROGRESS на месте; заготовки CLAUDE.md ERP/Cabinet — нет | — | заготовки CLAUDE.md; владелец проставляет accepted |
| M0-INF-05 | `packages/ui-tokens` | не начата | — | — |

## Журнал сессий

| Дата | Роль | Задача | Статус | Что сделано | Что осталось / нужно владельцу |
|---|---|---|---|---|---|
| 2026-10-13 | Infra | M0-INF-01 | готово | Репозиторий `RailTech_Platform` (владелец) стал монорепозиторием. `crm-rt-ai` → `apps/crm` (273 коммита) и `RailTech_SaaS_B2B` → `legacy/b2b` (1327 коммитов) перенесены с полной историей: пути переписаны `git filter-repo --to-subdirectory-filter`, истории вмержены (`--allow-unrelated-histories`), поэтому `git log`, `git blame` и `--follow` работают по новым путям без ключей. Теги `b2b-final` и `crm-standalone-final`. Вложенные `.git` и старые папки удалены — репозиторий один. Пакет запуска разложен: `CLAUDE.md`, `ORCHESTRATOR.md` в корне; остальное в `docs/` (`docs/history/` — документы обсуждения, только контекст). Созданы корневые `Makefile` (`check`, `check-crm|erp|cabinet`, `contracts`, `up`), `.editorconfig`, `.gitignore`, `.pre-commit-config.yaml` (gitleaks, ruff/prettier/eslint для CRM, `legacy/` исключён), `.gitleaks.toml`; заглушки `apps/erp`, `apps/cabinet`, `packages/*`, `infra/*`, `docs/runbooks`. | Владельцу: открыть PR `m0/infra-01-monorepo` → `main`; защита `main` — после M0-INF-04. Решить CI (минуты GitHub или self-hosted runner, OWNER-CHECKLIST). Имя репозитория `RailTech_Platform` зафиксировано в DECISIONS как факт. |
| 2026-10-13 | Infra | M0-INF-02 | готово | `packages/contracts`: три OpenAPI 3.1 (`erp-integration`, `erp-portal`, `erp-internal` v0 — только SSO/health), `events.schema.json` (19 событий, payload по `if/then`, 5 примеров), `mcp-tools.json` + схема (аргументы с id клиента запрещены), `sso-token.md`. Генерация: `openapi-typescript` → `generated/*.d.ts`, `orval` (fetch) → `generated/crm/`; `tsc` по сгенерированному; redocly + ajv в `make contracts`. Генерация детерминирована (проверено повторным прогоном). Зависимости — pnpm 11 с lockfile, build-скрипты разрешены явно в `pnpm-workspace.yaml`. | Владельцу: PR `m0/infra-02-contracts` (база — ветка M0-INF-01, вливать после неё). Решения по форме: стадии сделки и статусы — стабильные коды (`request…won/lost`), статусы поставки `assembling/in_transit/ready_to_ship/shipped/delivered`; подпись договора клиентом — подтверждением (E-IMZO отложен). |
