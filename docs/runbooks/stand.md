# Runbook: стенд ансамбля локально (`make up`)

Один `docker compose` поднимает общую инфраструктуру и CRM; ERP и Cabinet до своих вех — заглушки в Caddy.
Файлы: `infra/compose/base.yml` + `dev.yml`, `infra/caddy/Caddyfile.dev`, `infra/ai/*`, `infra/db/init-databases.sh`.

## Первый запуск

```
make env          # .env из .env.example, CHANGE_ME → случайные значения (идемпотентно)
make up           # сборка образов CRM и запуск всего стенда (5–10 мин в первый раз)
make smoke        # /health трёх доменов → 200
```

Домены (порт `HTTP_PORT` из `.env`, по умолчанию 80):

| Домен | Что отвечает |
|---|---|
| `http://crm.localhost` | CRM: SPA (`crm-web`), `/api/*`, `/health`, `/ready` → `crm-api` |
| `http://erp.localhost` | заглушка до M1-ERP-01: `/health` 200, `/api/*` 503 `ERP_NOT_IMPLEMENTED` |
| `http://cabinet.localhost` | заглушка до M2-CAB-01: `/health` 200 |
| `http://langfuse.localhost` | Langfuse (только `make up-obs`) |
| `http://s3.localhost` | консоль RustFS |

Браузеры резолвят `*.localhost` в 127.0.0.1 сами. Для `curl` на macOS — `--resolve crm.localhost:80:127.0.0.1`
(так делает `make smoke`) или строки в `/etc/hosts`.

Порты заняты другим проектом → поменяйте `HTTP_PORT` и `DEV_*_PORT` в `.env`, повторите `make up`.

## Что внутри

| Сервис | Назначение |
|---|---|
| `postgres` | PostgreSQL 17 + pgvector; базы `crm`, `erp`, `litellm`, `langfuse` (создаёт `db-init`, идемпотентно) |
| `redis` | один на ансамбль: БД 0 — Langfuse, 1 — ERP Celery (M1), 2 — ERP Channels (M1) |
| `rustfs`, `s3-init` | S3; бакеты CRM (`kb-sources`, `client-documents`, `tg-attachments`), `langfuse`, `erp` |
| `litellm`, `litellm-seed` | шлюз моделей по алиасам CRM и ERP (`infra/ai/litellm.models.yaml`); ключи провайдеров — только у `litellm` |
| `docling` | конвертация документов базы знаний CRM |
| `crm-migrate`, `crm-api`, `crm-worker`, `crm-mcp-*`, `crm-web` | CRM из `apps/crm` (код монтируется, hot reload) |
| `caddy` | три домена |
| `clickhouse`, `langfuse-worker`, `langfuse-web` | профиль `observability` |

## Повседневное

```
make ps                 # статус
make logs s=crm-api     # логи сервиса
make down               # остановить (данные в volumes остаются)
make up-obs             # с Langfuse
make -C apps/crm migrate  # нет: миграции CRM применяет сервис crm-migrate при каждом make up
```

Команды CRM, которым нужен стенд (`seed`, `create-admin`, `kb-demo`, `settings`), пока запускаются через
compose ансамбля напрямую, например:

```
docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env \
  run --rm crm-api python -m app create-admin --email admin@example.com --name Администратор
```

## Отличия от стенда `apps/crm` (для тех, кто работал с ним)

- Имя проекта `rt-platform` (volumes и сеть свои; старый стенд `railtech` не затрагивается).
- PostgreSQL 17 вместо 16; база CRM называется `crm` (в `apps/crm` — `railtech`). Образ `backup` CRM
  с `pg_dump` 16 несовместим с сервером 17 — перевод на 17 нужен до M5-INF-01 (отмечено в PROGRESS).
- Переменные CRM в `.env` с префиксом `CRM_` (`CRM_JWT_SECRET`, `CRM_SECRETS_KEY`, `CRM_AGENT_CONTEXT_KEY`,
  `CRM_LANGFUSE_*`); compose отдаёт их контейнерам под прежними именами.
- Сервисы CRM с префиксом `crm-`; MCP-серверы — `crm-mcp-kb|crm|docs`, адреса передаются через `*_MCP_URL`.
- Redis теперь общий сервис ансамбля (в CRM был только для Langfuse).

## Если не поднимается

- `make ps` → `crm-api` не healthy: `make logs s=crm-api`; чаще всего — не применились миграции (`make logs s=crm-migrate`).
- `litellm` не healthy: `make logs s=litellm`; база `litellm` создаётся `db-init` — проверьте его лог.
- `docling` стартует до минуты (образ 7 ГБ); `crm-worker` ждёт его.
- Всё снести и начать заново: `make down && docker volume rm $(docker volume ls -q | grep '^rt-platform_')`.
