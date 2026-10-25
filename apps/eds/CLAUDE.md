# CLAUDE.md — `apps/eds` (указатель)

EDS — отдельный сервис электронного документооборота (ADR-0015): FastAPI · SQLAlchemy 2 (async, psycopg 3) · Alembic · Procrastinate, своя база `eds`,
интеграции только через шину `rt_bus`. Внешнего маршрута нет: сотрудники — через BFF Платформы, системы — по шине.

**Прочитай:** `docs/systems/eds/CONVENTIONS.md` (правила кода; в коде ссылки `CONVENTIONS.md §N` ведут туда) и `docs/ORCHESTRATOR.md` (процесс, инварианты);
правило среды, тестов и CI — `CLAUDE.md` корня. Запуск и устройство — `docs/systems/eds/README.md`. План волны — `docs/runbooks/wave12-eds-c1.md`.
Контракт — `packages/contracts/openapi/eds.yaml` и `packages/contracts/events/eds/` (контракт раньше кода, в том же PR).

Документация — только в `docs/` (ORCHESTRATOR §3 п. 17): здесь новых `.md` не заводить.

Главные команды:

- `make -C apps/eds install` — зависимости (`uv sync --frozen`)
- `make check-eds` из корня — ruff, mypy `--strict`, pytest на одноразовом PostgreSQL (Docker)
- `make -C apps/eds test-unit` — тесты без базы
- `cd apps/eds && ./scripts/with_pg.sh uv run pytest tests/<файл>.py -x -q` — один тест
- `make -C apps/eds migration m="…"` — миграция Alembic (одна голова, обратимая)
- `scripts/ci_local.sh eds` — как CI; `make cpu-check args="rt-eds"` — образ под CPU `qemu64`
