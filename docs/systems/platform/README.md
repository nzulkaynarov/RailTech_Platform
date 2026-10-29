# Платформа — единый интерфейс сотрудников (`apps/platform`, `platform.railtech.uz`)
Статус: действует · Владелец: лид · Обновлено: 2026-10-29

Где Платформа сейчас и что дальше — `docs/HANDOFF.md` §1 и §3; что уже вышло для сотрудников — `docs/kb/help/changelog/`.

Платформа — один фронтенд для всех сотрудников компании: шесть модулей (Dashboard, CRM, EDS, ERP, Chats, Admin)
в одном окне. Она не заводит своей базы данных: работает поверх доменов CRM, ERP и EDS через их публичные API и
события `rt_bus`, а связывает их тонкий слой BFF (backend-for-frontend). Клиент по-прежнему живёт в кабинете, Mini App
и Telegram-боте.

## Порядок чтения

| # | Документ | О чём |
|---|---|---|
| 0 | [`docs/product/SPEC-v3.md`](../../product/SPEC-v3.md) | **Спецификация владельца v3 — источник истины.** Словарь, процессы, роли (§4 — с ADR-0012), дизайн, модули, каналы, уведомления |
| 1 | [`CONVENTIONS.md`](CONVENTIONS.md) | Правила кода Платформы, стек и команды |
| 2 | [`docs/architecture/platform-bff.md`](../../architecture/platform-bff.md) | SPA + BFF, вход и сессии, кто владеет сущностями, события и реальное время, роли, развёртывание |
| 3 | [`docs/architecture/platform-frontend.md`](../../architecture/platform-frontend.md) | Стек, структура кода, каркас и компоненты, точные размеры и цвета из макета v3, маршруты, тесты |
| 4 | [`docs/architecture/integration-map.md`](../../architecture/integration-map.md) | Экран и действие → эндпоинт BFF → операции доменов; маппинг стадий, статусов, ролей; разрывы |
| 5 | [стратегия 2026-10-23](../../strategy/2026-10-23-platform-architecture-strategy.md) §4, §7 | План этапов (заменил фазы P2–P6 и трансформацию T0–T5 — `docs/history/platform/`) |

Архитектурное решение уровня ансамбля — [docs/adr/0011-unified-platform-frontend.md](../../adr/0011-unified-platform-frontend.md).

## Дизайн

Макеты — дизайн-канвас «RailTech Platform — дизайн единого интерфейса», страница «v3 — итоговая»:
<https://claude.ai/code/artifact/d82c5f3c-cb33-4914-ae86-c3b85757bea6>. Девять экранов v3 и схема пути перечислены в
SPEC-v3, приложение А; точные размеры, цвета и состояния, снятые с макетов, — в [docs/architecture/platform-frontend.md](../../architecture/platform-frontend.md) §4.
Сами HTML-макеты в репозиторий не копируются: в них демонстрационные имена людей и организаций, а репозиторий
временно публичный.

## Структура папки

```
apps/platform/
  CLAUDE.md          указатель для агентов (правила — docs/systems/platform/CONVENTIONS.md)
  README.md          указатель (документация — docs/systems/platform/)
  web/               SPA (React 18, TypeScript, Ant Design 5 + Pro Components)
  bff/               BFF (Python 3.12, FastAPI)
```
