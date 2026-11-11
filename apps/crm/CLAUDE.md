# CLAUDE.md — `apps/crm` (указатель)

RailTech CRM — домен фронт-офиса: лиды, клиенты и контакты, переписка, база знаний, Telegram-бот, консоль администратора; до этапа F — вход и роли (идентичность v1). Своего фронтенда нет (удалён 2026-11-11): интерфейс сотрудников — Платформа.

**Прочитай:** `docs/systems/crm/CONVENTIONS.md` (правила кода; в коде ссылки `CONVENTIONS.md §N` ведут туда) и
`docs/ORCHESTRATOR.md` (процесс, инварианты, протокол сессии); правило среды, тестов и CI — `CLAUDE.md` корня.
Запуск и устройство — `docs/systems/crm/README.md`. SPEC — `docs/systems/crm/SPEC.md`, ADR — `docs/adr/crm/` (ADR CRM-NNNN), runbook'и — `docs/runbooks/crm/`. Промпты агентов (`backend/prompts/`), шаблоны писем и навыки `.claude/skills/` живут здесь — их читает код.

Документация — только в `docs/` (ORCHESTRATOR §3 п. 17): здесь новых `.md` не заводить.

Главные команды:

- `make install` — зависимости (в новом worktree — первым шагом)
- `make check` (= `make check-crm` из корня) — ruff, mypy, unit
- `cd backend && uv run pytest tests/<файл>.py -x -q` — один тест; `scripts/test_int_local.sh` — integration
- `make openapi` — экспорт OpenAPI в `packages/contracts/openapi/crm.yaml`
- `make migration m="..."` — миграция Alembic
