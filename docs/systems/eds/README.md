# EDS (электронный документооборот) — `apps/eds`, заготовка
Статус: действует (заготовка) · Владелец: архитектор · Обновлено: 2026-10-23

**Сервис создаётся на этапе C1** (стратегия 2026-10-23 §7); до этого кода нет, и `apps/eds` в репозитории не появляется.
Границы домена — [ADR-0015](../../adr/0015-eds-service-and-domain-boundaries.md); стек — [ADR-0013](../../adr/0013-stack-and-standards.md)
(FastAPI + SQLAlchemy 2 + Alembic + Procrastinate, своя база `eds`); интеграции — только через шину `rt_bus`
([ADR-0014](../../adr/0014-integration-bus-rt-bus.md)).

## Что будет в домене

| Владеет данными | Публикует события | Подписывается на |
|---|---|---|
| входящие и исходящие письма с регистрацией, резолюции, служебные записки, заявления, отчёты; **общий движок маршрутов согласования** (КП, договор, служебка); реестр и архив документов (метаданные, версии, сканы, журнал «кто и когда») | `letter.*`, `resolution.*`, `memo.*`, `approval.requested/decided`, `document.registered/archived` | CRM: `request.created`; ERP: `quote.ready_for_approval`, документы ERP для реестра |

Источник — стратегия §3.3. Сущности `Letter`, `Resolution`, `ServiceMemo` (SPEC-v3 §10.4, прежде планировались в ERP — ADR-0011 §4)
создаются здесь; разрывы ERP-01, ERP-05, ERP-08 карты интеграции переходят в EDS ([`integration-map.md`](../../architecture/integration-map.md) §7).

## Когда сервис появится

Задача C1 (runbook волны) создаёт: `apps/eds` (каркас, база, Docker, CI), контракты `packages/contracts/openapi/eds.yaml` и
схемы событий, `docs/systems/eds/CONVENTIONS.md` и `apps/eds/CLAUDE.md`/`README.md`-указатели; этот файл становится README
системы с командами запуска.
