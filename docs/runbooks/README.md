# docs/runbooks — эксплуатация и волны агентов
Статус: действует · Владелец: лид · Обновлено: 2026-10-23

**Ансамбль**
- [`stand.md`](stand.md) — локальный стенд `make up`; [`servers.md`](servers.md) — серверы VPS1/VPS2; [`deploy.md`](deploy.md) — деплой и откат прода;
- [`webhooks.md`](webhooks.md) — вебхуки ERP → CRM: журнал, ручной повтор, сбои приёма, ротация секрета;
- [`crm-erp-pairing.md`](crm-erp-pairing.md) — сопряжение CRM ↔ ERP; [`log-secrets.md`](log-secrets.md) — что не попадает в логи.

- [`backup-pitr.md`](backup-pitr.md) — WAL-архив PostgreSQL (WAL-G), восстановление на момент времени, ежемесячная проверка;
  [`request-id.md`](request-id.md) — найти запрос по `X-Request-ID` в журналах Caddy, CRM и ERP.

**Системы**
- **CRM**: [`crm/`](crm/README.md) — бот, эскалации, расходы ИИ, деплой, бэкапы, eval-gate, ротация ключей;
- **ERP**: [`erp/`](erp/README.md) — dev-стенд, миграции, Celery/AI-воркеры, бэкап и восстановление базы и медиа.

**Волны агентов** (промпт лида, раунды, задачи с «готово, когда»; преамбула исполнителя — `docs/ORCHESTRATOR.md` §4.2)
- действующие: [`wave9-roles.md`](wave9-roles.md) (роли как данные), [`wave10-stage0.md`](wave10-stage0.md) (этап 0), `wave11-bus-v1.md` (шина v1);
- закрытые волны 1–8 — [`../history/runbooks/`](../history/runbooks/).

**Отчёты прогонов глазами** — [`m1_qa_02_report.md`](m1_qa_02_report.md), [`m2_qa_01_report.md`](m2_qa_01_report.md),
[`m2_qa_02_report.md`](m2_qa_02_report.md), [`plt_p1_gate_report.md`](plt_p1_gate_report.md); снимки — `qa/`.
