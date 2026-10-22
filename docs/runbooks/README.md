# docs/runbooks — эксплуатация ансамбля

Runbook'и уровня ансамбля (деплой и откат, бэкапы двух баз, стенд с тремя доменами).

- [`stand.md`](stand.md) — локальный стенд `make up`; [`servers.md`](servers.md) — серверы M5; [`deploy.md`](deploy.md) — деплой и откат прода (M5-INF-01);
  [`request-id.md`](request-id.md) — найти запрос по `X-Request-ID` в журналах Caddy, CRM и ERP (S0-6);
  [`webhooks.md`](webhooks.md) — вебхуки ERP → CRM: журнал, ручной повтор, сбои приёма (FIX-33);
  [`wave1-agents.md`](wave1-agents.md) — волна 1 исправлений параллельными сессиями Claude Code (worktree, порядок слияния, промпты);
  [`wave2-agents.md`](wave2-agents.md), [`wave2b-m5-agents.md`](wave2b-m5-agents.md), [`wave3-4-agents.md`](wave3-4-agents.md) — волны 2–4;
  [`wave5-agents.md`](wave5-agents.md) — волна 5: прогоны глазами M1/M2 на стенде, документы, правила процесса (FIX-50…54).
У каждого приложения свой комплект эксплуатационных регламентов:
- **CRM**: [`apps/crm/docs/runbooks/`](../../apps/crm/docs/runbooks/) (бот, эскалации, расходы ИИ, деплой, бэкапы)
- **ERP**: [`apps/erp/docs/runbooks/`](../../apps/erp/docs/runbooks/) (dev-стенд, миграции, Celery/AI воркеры, бэкап/восстановление базы и медиа)
