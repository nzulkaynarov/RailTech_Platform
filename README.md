# RailTech Platform

Бизнес-платформа полного цикла одной компании — три системы в одном монорепозитории:

| Система | Для кого | Домен | Код |
|---|---|---|---|
| **CRM** | фронт-офис: лиды, Telegram-бот, база знаний, квалификация | `crm.railtech.uz` | `apps/crm` |
| **ERP** | бэк-офис: заявки, КП, договоры, снабжение, склад, финансы | `erp.railtech.uz` | `apps/erp` (с M1) |
| **Cabinet** | клиент: запросы, КП, документы, статусы; без бэкенда, над `/api/portal/*` ERP | `cabinet.railtech.uz` | `apps/cabinet` (с M2) |

Связь CRM ↔ ERP — только API и события, общих таблиц нет. Подробно — `CLAUDE.md` (карта репозитория)
и **`ORCHESTRATOR.md`** (цель, инварианты, вехи, протокол работы агентов — читать первым).

## Документация

- `docs/README.md` — состав пакета документов ансамбля
- `docs/BUSINESS.md` · `docs/ARCHITECTURE.md` · `docs/CONTRACTS.md` · `docs/MIGRATION-MAP.md`
- `docs/DECISIONS.md` · `docs/QUESTIONS.md` · `docs/OWNER-CHECKLIST.md` · `docs/PROGRESS.md`
- `docs/adr/` — архитектурные решения ансамбля; `docs/history/` — документы обсуждения, из которых собран пакет

## Команды

```
make check            # проверки всех приложений (make check-crm | check-erp | check-cabinet)
make contracts        # валидация packages/contracts и генерация клиентов (с M0-INF-02)
make up               # весь ансамбль локально на crm/erp/cabinet.localhost (с M0-INF-03)
make hooks            # pre-commit корня: gitleaks и быстрые проверки
make ci-local         # локальный CI — гейт мержа, пока GitHub Actions недоступен (args="--quick" без integration и build)
```

До появления стенда ансамбля CRM поднимается отдельно: `make -C apps/crm up` (см. `apps/crm/README.md`).

## Происхождение кода

- `apps/crm` — бывший репозиторий `crm-rt-ai`, перенесён с полной историей (тег `crm-standalone-final`).
- `legacy/b2b` — бывший репозиторий `RailTech_SaaS_B2B`, только чтение; источник кода для ERP и Cabinet,
  удаляется после вехи M2, остаётся тег `b2b-final`.
