# Architecture Decision Records

Формат — MADR, шаблон `0000-template.md`, процесс — CLAUDE.md §5 и скилл `.claude/skills/adr`.
Статусы: `proposed` → `accepted (дата)` / `rejected` / `superseded by NNNN`. `accepted` ставит человек.

| ADR | Решение | Статус | Фаза |
|---|---|---|---|
| [0001](0001-two-agents-code-decides.md) | Два агента, решения принимает код | accepted | 0 |
| [0002](0002-own-crm-on-refine.md) | Собственный CRM на Refine, а не готовая CRM как ядро | accepted | 0 |
| [0003](0003-client-bot-and-team-channel.md) | Один клиентский бот + канал уведомлений | accepted | 0 |
| [0004](0004-models-and-embeddings.md) | Внешние модели и размерность embedding | accepted | 1 |
| [0005](0005-jwt-casbin-keycloak-later.md) | JWT + Casbin на старте, Keycloak позже | accepted | 0 |
| [0006](0006-procrastinate-queue.md) | Procrastinate как очередь и планировщик | accepted | 0 |
| [0007](0007-hybrid-search-rrf.md) | Гибридный поиск: вектор + BM25 → RRF, порог по косинусу | accepted | 1 |
| [0008](0008-hmac-agent-context.md) | HMAC-контекст для MCP вместо идентификаторов от модели | accepted | 2 |
| [0009](0009-s3-storage-rustfs.md) | S3-хранилище: RustFS вместо MinIO | accepted | 0 |
| [0010](0010-psycopg3-single-driver.md) | psycopg 3 — единственный драйвер PostgreSQL | accepted | 0 |
| [0011](0011-docling-serve-and-mcp-sdk.md) | docling-serve как сервис; MCP на официальном SDK (`MCPServer`) | accepted | 1 |
| [0012](0012-crm-take-and-live-events.md) | «Забрать» из любой активной стадии; live-события через PostgreSQL NOTIFY | accepted | 4 |
| [0013](0013-backup-pgdump-s3-mirror.md) | Бэкап: pg_dump 16 + копия бакетов кодом приложения, контейнер backup | accepted | 8 |
| [0014](0014-model-budget-levels.md) | Бюджет моделей в три уровня; нагрузочный smoke в процессе | accepted | 8 |
| [0015](0015-lifecycle-without-dead-ends.md) | Жизненный цикл без тупиков: возврат из «Отказа», повторная сделка, бот не молчит в ожидании | accepted | 9 |
| [0016](0016-configurable-qualification-and-price-handoff.md) | Квалификацию и передачу по цене решает код по настраиваемым правилам | accepted | 9 |
| [0017](0017-api-error-reasons.md) | Подкод `details.reason` и поле `details.field` в ошибках API; единый формат для всех ошибок | accepted | 9 |
| [0018](0018-admin-console-connectors-and-secrets.md) | Подключения настраивает админ в CRM; секреты интеграций — в БД зашифрованными | accepted | 9 |
| [0019](0019-deals-entity.md) | Сделка — отдельная сущность рядом с лидом; воронка лида не дублируется | accepted | 9 |
| [0020](0020-models-and-keys-from-crm.md) | Модели и ключи ролей меняет админ в CRM через БД LiteLLM (без рестарта) | accepted | 9 |
