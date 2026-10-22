# apps/platform — RailTech Platform, единый интерфейс сотрудников (`platform.railtech.uz`)

Статус: **фаза P0** (2026-10-22). ADR-0011 принят, ответы на [docs/history/platform/06-questions.md](../../history/platform/06-questions.md) — «да» по
всем рекомендациям. Идут контракты v0, каркас `web/` и `bff/`, инфраструктура (`docs/history/platform/05-plan.md`, P0).

Платформа — один фронтенд для всех сотрудников компании: шесть модулей (Dashboard, CRM, EDS, ERP, Chats, Admin)
в одном окне. Она не заводит своей базы данных: работает поверх действующих бэкендов CRM и ERP через их
OpenAPI, а связывает их тонкий слой BFF (backend-for-frontend). Клиент по-прежнему живёт в кабинете, Mini App
и Telegram-боте.

## Порядок чтения

| # | Документ | О чём |
|---|---|---|
| 0 | [docs/product/SPEC-v3.md](../../product/SPEC-v3.md) | **Спецификация владельца v3 — источник истины.** Словарь, процессы, роли, дизайн, модули, каналы, уведомления. При расхождении с остальными документами права спецификация |
| 1 | [docs/history/platform/01-transformation.md](../../history/platform/01-transformation.md) | Стратегия: как новый фронтенд встаёт рядом со старыми, заменяет их и как после этого упрощаются бэкенды |
| 2 | [docs/architecture/platform-bff.md](../../architecture/platform-bff.md) | SPA + BFF, вход и сессии, кто владеет новыми сущностями, события и реальное время, роли, развёртывание |
| 3 | [docs/architecture/platform-frontend.md](../../architecture/platform-frontend.md) | Стек, структура кода, каркас и компоненты, точные размеры и цвета из макета v3, маршруты, тесты |
| 4 | [docs/architecture/integration-map.md](../../architecture/integration-map.md) | Каждый экран и действие → эндпоинт BFF → операции CRM и ERP; маппинг стадий, статусов, ролей; чего в бэкендах не хватает |
| 5 | [docs/history/platform/05-plan.md](../../history/platform/05-plan.md) | Фазы, задачи с ID, зависимости, «готово, когда», гейты владельца |
| 6 | [docs/history/platform/06-questions.md](../../history/platform/06-questions.md) | Вопросы владельцу с рекомендациями |

Архитектурное решение уровня ансамбля — [docs/adr/0011-unified-platform-frontend.md](../../adr/0011-unified-platform-frontend.md).

## Дизайн

Макеты — дизайн-канвас «RailTech Platform — дизайн единого интерфейса», страница «v3 — итоговая»:
<https://claude.ai/code/artifact/d82c5f3c-cb33-4914-ae86-c3b85757bea6>. Девять экранов v3 и схема пути перечислены в
SPEC-v3, приложение А; точные размеры, цвета и состояния, снятые с макетов, — в [docs/architecture/platform-frontend.md](../../architecture/platform-frontend.md) §4.
Сами HTML-макеты в репозиторий не копируются: в них демонстрационные имена людей и организаций, а репозиторий
временно публичный.

## Будущая структура папки

```
apps/platform/
  docs/systems/platform/CONVENTIONS.md          конвенции для агентов
  README.md          этот файл
  docs/              документация трансформации
  web/               SPA (React 18, TypeScript, Ant Design 5 + Pro Components) — фаза P1
  bff/               BFF (Python 3.12, FastAPI) — фаза P1
```
