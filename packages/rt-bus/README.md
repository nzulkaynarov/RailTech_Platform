# rt-bus

Библиотека шины событий `rt_bus` (ADR-0014): outbox, inbox, ретранслятор, подписанная доставка, DLQ, предохранитель.
Адаптеры: SQLAlchemy async (CRM), Django (ERP), без БД (BFF).

API и подключение — [docs/architecture/rt-bus.md](../../docs/architecture/rt-bus.md).

```bash
make install     # uv sync --frozen
make test-unit   # тесты без базы
make check       # ruff, mypy --strict, миграция Django, тесты на PostgreSQL (RT_BUS_TEST_DATABASE_URL или postgres:17 в Docker)
```
