# docs/runbooks — эксплуатация и волны агентов
Статус: действует · Владелец: лид · Обновлено: 2026-10-23

**Ансамбль**
- [`stand.md`](stand.md) — локальный стенд `make up`; [`servers.md`](servers.md) — серверы VPS1/VPS2; [`deploy.md`](deploy.md) — деплой и откат прода;
- [`webhooks.md`](webhooks.md) — вебхуки ERP → CRM (устарел, заменены шиной rt_bus) и ротация секрета сопряжения;
- [`crm-erp-pairing.md`](crm-erp-pairing.md) — сопряжение CRM ↔ ERP; [`log-secrets.md`](log-secrets.md) — что не попадает в логи.

- [`backup-pitr.md`](backup-pitr.md) — WAL-архив PostgreSQL (WAL-G), восстановление на момент времени, ежемесячная проверка;
  [`request-id.md`](request-id.md) — найти запрос по `X-Request-ID` в журналах Caddy, CRM и ERP;
  [`rt-bus-erp.md`](rt-bus-erp.md) — шина rt_bus в ERP: журнал, DLQ, повтор, метрики, неверный endpoint (B3);
  [`rt-bus-crm.md`](rt-bus-crm.md) — шина rt_bus в CRM: DLQ, повтор, метрики, события ERP не обработаны (B4).

**Системы**
- **CRM**: [`crm/`](crm/README.md) — бот, эскалации, расходы ИИ, деплой, бэкапы, eval-gate, ротация ключей;
- **ERP**: [`erp/`](erp/README.md) — dev-стенд, миграции, Celery/AI-воркеры, бэкап и восстановление базы и медиа.

**Волны агентов** (промпт лида, раунды, задачи с «готово, когда»; преамбула исполнителя — `docs/ORCHESTRATOR.md` §4.2)
- действующие: [`wave9-roles.md`](wave9-roles.md) (роли как данные), [`wave10-stage0.md`](wave10-stage0.md) (этап 0), [`wave11-bus-v1.md`](wave11-bus-v1.md) (шина v1), [`wave11b-tails.md`](wave11b-tails.md) (хвосты и гейт этапа B), [`wave12-eds-c1.md`](wave12-eds-c1.md) (сервис EDS), [`wave11c-bus-fixes.md`](wave11c-bus-fixes.md) (дефекты шины после гейта B);
- закрытые волны 1–8 — [`../history/runbooks/`](../history/runbooks/).

**Отчёты прогонов глазами** — [`m1_qa_02_report.md`](m1_qa_02_report.md), [`m2_qa_01_report.md`](m2_qa_01_report.md),
[`m2_qa_02_report.md`](m2_qa_02_report.md), [`plt_p1_gate_report.md`](plt_p1_gate_report.md);
[`c1_eds_gate_report.md`](c1_eds_gate_report.md) (гейт этапа C1, сервис EDS; скрипты и выводы — `qa/c1-eds/`); снимки — `qa/`.
