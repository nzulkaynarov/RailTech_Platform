# Architecture Decision Records

Формат — MADR, шаблон `0000-template.md`, процесс — CLAUDE.md §5 и скилл `.claude/skills/adr`.
Статусы: `proposed` → `accepted (дата)` / `rejected` / `superseded by NNNN`. `accepted` ставит человек.

| ADR | Решение | Статус | Фаза |
|---|---|---|---|
| [0001](0001-two-agents-code-decides.md) | Два агента, решения принимает код | accepted | 0 |
| [0002](0002-own-crm-on-refine.md) | Собственный CRM на Refine, а не готовая CRM как ядро | accepted | 0 |
| [0003](0003-client-bot-and-team-channel.md) | Один клиентский бот + канал уведомлений | accepted | 0 |
| 0004 | Выбор внешних моделей и размерности embedding | — (зарезервирован) | 1 |
| [0005](0005-jwt-casbin-keycloak-later.md) | JWT + Casbin на старте, Keycloak позже | accepted | 0 |
| [0006](0006-procrastinate-queue.md) | Procrastinate как очередь и планировщик | accepted | 0 |
| 0007 | Гибридный поиск RRF и пороги | — (зарезервирован) | 1 |
| 0008 | HMAC-контекст для MCP | — (зарезервирован) | 2 |
| [0009](0009-s3-storage-rustfs.md) | S3-хранилище: RustFS вместо MinIO | accepted | 0 |
| [0010](0010-psycopg3-single-driver.md) | psycopg 3 — единственный драйвер PostgreSQL | accepted | 0 |
