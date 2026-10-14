# CLAUDE.md — корень монорепозитория RailTech Platform (GitHub `RailTech_Platform`, кодовое имя `rt_platform`)

Три системы одной компании: **CRM** (фронт-офис, лиды, бот), **ERP** (бэк-офис: заявки, КП, договоры,
снабжение, склад, финансы), **Cabinet** (кабинет клиента, фронтенд над API ERP). Связь CRM ↔ ERP —
только API и события. Общих таблиц нет.

**Первым читай `ORCHESTRATOR.md`**, затем `docs/HANDOFF.md` — там цель, инварианты, роли агентов, текущая веха и протокол.
Затем — `CLAUDE.md` того приложения, в котором работаешь: конвенции кода живут у приложений, не здесь.

```
apps/crm/        FastAPI · SQLAlchemy · Alembic · Procrastinate · aiogram · LangGraph · Refine/AntD   → apps/crm/CLAUDE.md
apps/erp/        Django · DRF · Celery · Channels · shadcn/Tailwind                                      → apps/erp/CLAUDE.md
apps/cabinet/    React · shadcn · без бэкенда; ходит в apps/erp /api/portal/*                          → apps/cabinet/CLAUDE.md
legacy/b2b/      старая B2B, только чтение; удаляется после вехи M2                                      → не редактировать
packages/contracts/   OpenAPI ERP (internal, portal, integration), схемы событий, схемы MCP-инструментов
packages/ui-tokens/   общие токены дизайна для AntD и shadcn
infra/           compose (base/dev/prod), caddy (3 домена), ai (LiteLLM, Langfuse), db (2 базы, бэкапы), ci
docs/            HANDOFF (где мы и что дальше), BUSINESS, ARCHITECTURE, CONTRACTS, MIGRATION-MAP, DECISIONS, QUESTIONS, OWNER-CHECKLIST, PROGRESS.md, adr/, runbooks/, history/
```

Правила уровня ансамбля (подробно — ORCHESTRATOR.md §3):
1. Одна система — один главный пользователь. Не добавляй в систему чужого пользователя.
2. Никаких общих таблиц между `crm` и `erp`. Только API, события, внешние идентификаторы.
3. Контракт (`packages/contracts`) меняется раньше кода и в том же PR с обеих сторон.
4. Код решает, модель предлагает. Идентификаторы компании/клиента никогда не приходят от модели.
5. Секретов в репозитории нет. Все модели — через LiteLLM по алиасам.
6. DoD любой задачи с UI — сценарий, пройденный глазами (скриншот), не «тесты зелёные».
7. Отклонение от ARCHITECTURE/CONTRACTS — только через ADR и решение владельца, не молча.

Команды: `make check` (все приложения), `make check-crm|erp|cabinet`, `make up` (весь ансамбль
локально на трёх доменах `*.localhost`), `make contracts` (валидация и генерация клиентов).
