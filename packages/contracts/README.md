# packages/contracts — контракт CRM ↔ ERP ↔ Cabinet

Источник истины шва ансамбля (ORCHESTRATOR §3.3: **контракт раньше кода**). Объяснение — `docs/CONTRACTS.md`;
здесь — машиночитаемые файлы и генерация клиентов. Версия 0 (M0-INF-02).

| Файл | Что описывает | Кто реализует / потребляет |
|---|---|---|
| `openapi/erp-integration.yaml` | Integration API `/api/integration/v1/*` (CRM → ERP): handoff, контакты, сделки, документы, каталог, провижининг, здоровье, расходы ИИ | ERP `integration` (M3-ERP-01); CRM коннектор и `services/handoff` (M3-CRM-02/03) |
| `openapi/erp-portal.yaml` | Portal API `/api/portal/v1/*` (Cabinet → ERP): вход Telegram/magic-link, запросы, КП, договоры, счета, акты, поставки, документы, каталог, компания | ERP `portal` (M2-ERP-01…03); Cabinet (M2-CAB-01) |
| `openapi/erp-internal.yaml` | Internal API `/api/v1/*` — только часть, входящая в контракт: SSO-обмен, `/me`, `/health`, `/ready`. Остальное экспортируется из ERP на M1-ERP-10 | ERP `accounts` (M3-ERP-04) |
| `events.schema.json` | События ERP → CRM (вебхук, HMAC, идемпотентность по `X-Event-Id`) + `examples/events/*.json` | ERP (M3-ERP-02); CRM приёмник (M3-CRM-04) |
| `mcp-tools.json` | Инструменты `erp-mcp` для агента CRM с контекстом `X-Agent-Context`; схема — `mcp-tools.schema.json` (запрещает идентификаторы клиента в аргументах) | ERP (M3-ERP-03); бот CRM (M3-CRM-07) |
| `sso-token.md` | SSO-токен сотрудника: claims, передача, проверка, отзыв | ERP (M3-ERP-04); CRM (M3-CRM-06) |

## Команды

```
make contracts                 # из корня: lint + generate + typecheck (ниже)
make -C packages/contracts lint       # redocly (OpenAPI), ajv (события, erp-mcp)
make -C packages/contracts generate   # openapi-typescript → generated/*.d.ts; orval → generated/crm/ (fetch-клиент Integration API)
make -C packages/contracts typecheck  # tsc по сгенерированному
```

`generated/` коммитится. CI (M0-INF-04) запускает `make contracts` и падает, если `git diff` в `generated/` не пуст:
контракт и сгенерированное расходятся → PR не принимается.

## Правила изменения

1. Меняется файл здесь → в том же PR пересобирается `generated/` и обновляются обе стороны (ERP и CRM/Cabinet) в одной вехе.
2. Несовместимое изменение API — новый префикс версии (`v2`) и период совместимости в одну веху; события — поле `version` в теле.
3. Конфликт двух агентов на одном файле контракта решает оркестратор; контракт не правят вдвоём.
4. Потребители: Cabinet и ERP SPA — `openapi-typescript` по этим файлам; CRM frontend — `generated/crm/`; CRM backend (Python) — клиент по `erp-integration.yaml` появится в `apps/crm` на M3-CRM-02.
