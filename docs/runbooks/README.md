# docs/runbooks — эксплуатация ансамбля

Runbook'и уровня ансамбля (деплой и откат, бэкапы двух баз, стенд с тремя доменами).

- [`stand.md`](stand.md) — локальный стенд `make up`; [`servers.md`](servers.md) — серверы M5; [`deploy.md`](deploy.md) — деплой и откат прода (M5-INF-01);
  [`webhooks.md`](webhooks.md) — вебхуки ERP → CRM: журнал, ручной повтор, сбои приёма (FIX-33);
  [`docs/history/runbooks/wave1-agents.md`](../history/runbooks/wave1-agents.md) — волна 1 исправлений параллельными сессиями Claude Code (worktree, порядок слияния, промпты);
  [`docs/history/runbooks/wave2-agents.md`](../history/runbooks/wave2-agents.md), [`docs/history/runbooks/wave2b-m5-agents.md`](../history/runbooks/wave2b-m5-agents.md), [`docs/history/runbooks/wave3-4-agents.md`](../history/runbooks/wave3-4-agents.md) — волны 2–4;
  [`docs/history/runbooks/wave5-agents.md`](../history/runbooks/wave5-agents.md) — волна 5: прогоны глазами M1/M2 на стенде, документы, правила процесса (FIX-50…54).
У каждого приложения свой комплект эксплуатационных регламентов:
- **CRM**: [`docs/runbooks/crm/`](crm/) (бот, эскалации, расходы ИИ, деплой, бэкапы)
- **ERP**: [`docs/runbooks/erp/`](erp/) (dev-стенд, миграции, Celery/AI воркеры, бэкап/восстановление базы и медиа)
