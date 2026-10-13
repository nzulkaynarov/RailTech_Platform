# packages/contracts — контракт CRM ↔ ERP ↔ Cabinet

Источник истины шва (ORCHESTRATOR §3.3: контракт раньше кода). Заполняется задачей **M0-INF-02** из `docs/CONTRACTS.md`:

- `openapi/erp-internal.yaml`, `openapi/erp-portal.yaml`, `openapi/erp-integration.yaml`
- `events.schema.json` — события ERP → CRM (`docs/CONTRACTS.md` §3)
- `mcp-tools.json` — инструменты `erp-mcp` (`docs/CONTRACTS.md` §5)
- `sso-token.md` — SSO-токен сотрудника (`docs/CONTRACTS.md` §6)
- `Makefile` с целью `check`: валидация и генерация клиентов (orval для CRM, openapi-typescript для ERP/Cabinet); вызывается из корня `make contracts`.
