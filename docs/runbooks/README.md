# docs/runbooks — эксплуатация ансамбля

Runbook'и уровня ансамбля (деплой и откат, бэкапы двух баз, стенд с тремя доменами).
- [`stand.md`](stand.md) — локальный стенд `make up`; [`servers.md`](servers.md) — серверы M5;
  [`wave1-agents.md`](wave1-agents.md) — волна 1 исправлений параллельными сессиями Claude Code (worktree, порядок слияния, промпты).
У каждого приложения свой комплект эксплуатационных регламентов:
- **CRM**: [`apps/crm/docs/runbooks/`](../../apps/crm/docs/runbooks/) (бот, эскалации, расходы ИИ, деплой, бэкапы)
- **ERP**: [`apps/erp/docs/runbooks/`](../../apps/erp/docs/runbooks/) (dev-стенд, миграции, Celery/AI воркеры, бэкап/восстановление базы и медиа)
