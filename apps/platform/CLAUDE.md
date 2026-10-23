# CLAUDE.md — `apps/platform` (указатель)

Платформа — единый интерфейс всех сотрудников: SPA `web/` (React 18 · AntD 5) и BFF `bff/` (FastAPI) без своей базы, поверх публичных API доменов.

**Прочитай:** `docs/systems/platform/CONVENTIONS.md` (правила кода; в коде ссылки `CONVENTIONS.md §N` ведут туда) и
`docs/ORCHESTRATOR.md` (процесс, инварианты, протокол сессии); правило среды, тестов и CI — `CLAUDE.md` корня.
Запуск и устройство — `docs/systems/platform/README.md`. Спецификация — `docs/product/SPEC-v3.md`; архитектура — `docs/architecture/platform-bff.md`, `platform-frontend.md`, `integration-map.md`.

Документация — только в `docs/` (ORCHESTRATOR §3 п. 17): здесь новых `.md` не заводить.

Главные команды:

- `make -C apps/platform install` — зависимости bff и web
- `make check-platform` из корня — ruff, mypy, pytest, eslint, tsc, vitest, свежесть orval и токенов
- `cd apps/platform/bff && uv run pytest tests/<файл>.py -x -q`; `cd apps/platform/web && pnpm test -- <шаблон>`
- `make -C apps/platform gen-api` / `rbac` — клиент из `platform-bff.yaml`, RBAC из `platform-rbac.yaml`
- `make -C apps/platform e2e` — Playwright + axe на MSW
