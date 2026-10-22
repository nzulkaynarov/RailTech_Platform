# 0010. psycopg 3 — единственный драйвер PostgreSQL

- Статус: accepted (2026-10-08, решение владельца продукта в обсуждении Фазы 0)
- Дата: 2026-10-08
- Связано: SPEC §2 (SQLAlchemy 2 async, Procrastinate, LangGraph PostgresSaver); ADR-0006

## Контекст и проблема

SPEC выбирает SQLAlchemy 2 (async), Procrastinate и LangGraph `PostgresSaver`, но не фиксирует драйвер. Procrastinate 3 и `PostgresSaver` работают на psycopg 3; для SQLAlchemy async популярен и asyncpg.

## Драйверы решения

- Один драйвер — одна модель ошибок, один набор настроек TLS/таймаутов, меньше зависимостей.
- Совместимость с Procrastinate (`PsycopgConnector`) и LangGraph.

## Рассмотренные варианты

1. psycopg 3 для всего (`postgresql+psycopg://` в SQLAlchemy).
2. asyncpg для SQLAlchemy + psycopg 3 для Procrastinate/LangGraph.

## Решение

Вариант 1: `psycopg[binary,pool]`. DSN строится в `app/config.py` из `POSTGRES_*` в двух формах: SQLAlchemy (`postgresql+psycopg://`) и libpq (`postgresql://`) для Procrastinate.

### Последствия

- Хорошо: одна зависимость, единообразная диагностика.
- Плохо: asyncpg в среднем быстрее на микробенчмарках — для нагрузки проекта (десятки диалогов) несущественно.

### Как проверяем

Integration-тесты на реальном Postgres; нагрузочный smoke Фазы 8 (p95 ≤ 6 с).
