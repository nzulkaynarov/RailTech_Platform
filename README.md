# RailTech Platform

Бизнес-платформа полного цикла одной компании в одном монорепозитории: домены CRM, EDS и ERP за шиной `rt_bus`,
Платформа — единый интерфейс сотрудников, Cabinet — кабинет клиента.

- Карта документации («тема → единственный документ») — [`docs/README.md`](docs/README.md)
- Процесс и правила агентов — [`docs/ORCHESTRATOR.md`](docs/ORCHESTRATOR.md); где мы — [`docs/HANDOFF.md`](docs/HANDOFF.md)
- Стратегия и план — [`docs/strategy/2026-10-23-platform-architecture-strategy.md`](docs/strategy/2026-10-23-platform-architecture-strategy.md)
- Системы — [`docs/systems/`](docs/systems/); карта монорепо и правило среды — [`CLAUDE.md`](CLAUDE.md)

Команды: `make check`, `make contracts`, `make up`, `make ci-local`, `make hooks` (`make help` — все цели).
Происхождение: `apps/crm` — бывший `crm-rt-ai` (тег `crm-standalone-final`); ERP выделена из `RailTech_SaaS_B2B` (тег `b2b-final`).
