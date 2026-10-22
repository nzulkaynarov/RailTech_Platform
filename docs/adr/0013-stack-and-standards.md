# 0013. Стек и стандарты ансамбля

- Статус: accepted (владелец, 2026-10-23: стратегия утверждена) · Дата: 2026-10-23
- Основание: `docs/strategy/2026-10-23-platform-architecture-strategy.md` §3.5

## Контекст
В ансамбле два бэкенд-стека (FastAPI в CRM и BFF, Django в ERP), две очереди (Procrastinate, Celery), три фронтенд-стека
(Refine/AntD, shadcn ERP, shadcn Cabinet, AntD Платформы). Добавляются EDS и сервисы платформы. Без правила каждый новый
сервис выбирал бы своё.

## Решение
1. Новый серверный код (EDS, сервисы идентичности и уведомлений, коннекторы, BFF) — Python 3.12, FastAPI, SQLAlchemy 2, Alembic,
   Procrastinate (очередь в PostgreSQL), httpx, pydantic v2, structlog; uv, ruff, mypy strict, pytest. Третьего бэкенд-стека нет.
2. ERP остаётся на Django + DRF + Celery; новый код ERP — сервисный слой и события `rt_bus` (ADR-0014).
3. Фронтенды: сотрудники — Платформа (React 18, TypeScript, Vite, Ant Design 5 + Pro Components); клиент — Cabinet (shadcn) с
   общими токенами (ADR-0018). Фронтенды CRM и ERP удаляются (стратегия §7).
4. PostgreSQL 17, своя база на сервис; общих таблиц нет (ADR-0002 в силе).
5. Redis — только кэш и сессии; брокер ERP — отдельный экземпляр с записью на диск.
6. Файлы — S3 (RustFS), бакет и ключ на сервис, копия вне площадки.
7. ИИ — LiteLLM по алиасам (ADR-0005 в силе).
8. Образы — Debian/Alpine; не UBI9/Wolfi, пока VM видит CPU `qemu64`; старт каждого образа проверяется под `qemu64` в CI.

## Последствия
Шаблон нового сервиса `apps/<сервис>` по образцу `apps/platform/bff`; CLAUDE.md сервиса — с теми же командами.
Переход ERP с Celery — решение этапа G.
