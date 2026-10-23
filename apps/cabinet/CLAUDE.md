# CLAUDE.md — `apps/cabinet` (указатель)

Cabinet — кабинет клиента (веб и Telegram Mini App) без своего бэкенда: только портальный API ERP `/api/portal/v1/*`.

**Прочитай:** `docs/systems/cabinet/CONVENTIONS.md` (правила кода; в коде ссылки `CONVENTIONS.md §N` ведут туда) и
`docs/ORCHESTRATOR.md` (процесс, инварианты, протокол сессии); правило среды, тестов и CI — `CLAUDE.md` корня.
Запуск и устройство — `docs/systems/cabinet/README.md`. Контракт портала — `packages/contracts/openapi/erp-portal.yaml`, объяснение — `docs/architecture/CONTRACTS.md` §4.

Документация — только в `docs/` (ORCHESTRATOR §3 п. 17): здесь новых `.md` не заводить.

Главные команды:

- `make -C apps/cabinet install` — npm ci
- `make check-cabinet` из корня — eslint, tsc, i18n, токены, типы API, vitest + axe
- `cd apps/cabinet && npm run test -- <шаблон>` — один тест
- `make -C apps/cabinet dev` — dev с моком портального API; `gen-api-types` — типы из контракта
