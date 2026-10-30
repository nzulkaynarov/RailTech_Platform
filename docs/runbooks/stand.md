# Runbook: стенд ансамбля локально (`make up`)
Статус: действует · Владелец: лид · Обновлено: 2026-10-23

Один `docker compose` поднимает общую инфраструктуру, CRM, ERP, Cabinet и Платформу.
Файлы: `infra/compose/base.yml` + `dev.yml`, `infra/caddy/Caddyfile.dev`, `infra/ai/*`, `infra/db/init-databases.sh`.

## Первый запуск

```
make env          # .env из .env.example, CHANGE_ME → случайные значения (идемпотентно)
make up           # сборка образов CRM и запуск всего стенда (5–10 мин в первый раз)
make smoke        # /health доменов CRM, ERP, Cabinet и /api/v1/health + / Платформы → 200
```

Домены (порт `HTTP_PORT` из `.env`, по умолчанию 80):

| Домен | Что отвечает |
|---|---|
| `http://crm.localhost` | CRM: SPA (`crm-web`), `/api/*`, `/health`, `/ready` → `crm-api` |
| `http://erp.localhost` | ERP (с M1-ERP-01): `/api`, `/admin`, `/ws`, `/static`, `/media`, `/health` → `erp-backend`; остальное → `erp-web` (SPA) |
| `http://cabinet.localhost` | Cabinet (с M2-CAB-01): `/api/portal/*` → `erp-backend` (портальный API); остальное, включая `/health`, → `cabinet-web` (SPA) |
| `http://platform.localhost` | Платформа (с INF-P0-4): `/api/*` (в т.ч. `/api/v1/health`) → `platform-bff` (без буферизации ответа, для SSE); остальное → `platform-web` (SPA). Заголовки безопасности и CSP — как у CRM на проде. TLS в dev нет: адрес `http://platform.localhost:<HTTP_PORT>` |
| `http://langfuse.localhost` | Langfuse (только `make up-obs`) |
| `http://s3.localhost` | консоль RustFS |

Браузеры резолвят `*.localhost` в 127.0.0.1 сами. Для `curl` на macOS — `--resolve crm.localhost:80:127.0.0.1`
(так делает `make smoke`) или строки в `/etc/hosts`.

Порты заняты другим проектом → поменяйте `HTTP_PORT` и `DEV_*_PORT` в `.env`, повторите `make up`.

> **Redis (S0-2).** Вместо одного `redis` — `redis-broker` и `redis-cache` с паролями `REDIS_BROKER_PASSWORD` и `REDIS_CACHE_PASSWORD`; порты на хосте —
> `DEV_REDIS_BROKER_PORT` (6379) и `DEV_REDIS_CACHE_PORT` (6380). В старом `.env` выполните `make env`: он допишет новые переменные; `REDIS_PASSWORD` и
> `DEV_REDIS_PORT` больше не читаются. Старый том `<проект>_redis_data` можно удалить (`docker volume rm`).

## Что внутри

| Сервис | Назначение |
|---|---|
| `postgres` | PostgreSQL 17 + pgvector; базы `crm`, `erp`, `litellm`, `langfuse` (создаёт `db-init`, идемпотентно) |
| `redis-broker` | брокер и результаты Celery ERP (БД 1), Channels ERP (БД 2), очереди Langfuse (БД 3, S0-9); `appendonly yes`, `noeviction` (S0-2) |
| `redis-cache` | кэш, троттлинг и одноразовые `jti` ERP (БД 0), сессии Платформы (БД 3); `volatile-lru`; свой пароль (S0-2) |
| `rustfs`, `s3-init` | S3; бакеты CRM (`kb-sources`, `client-documents`, `tg-attachments`), ERP (`erp-private`, `erp-public`, `erp-temp`), `langfuse`, `backups`, `wal`. Ключ на сервис (S0-9): `s3-init` (образ `rustfs/rc`, `infra/s3/init.sh`) заводит пользователей и политики, ставит правило `erp-temp` (1 сутки) и проверяет доступ; корневой ключ `S3_ROOT_*` знают только `rustfs` и `s3-init`. В старом `.env` выполните `make env`: он допишет `S3_*_ACCESS_KEY/SECRET_KEY` (старые `S3_ACCESS_KEY/S3_SECRET_KEY` уберите и впишите их значения как `S3_ROOT_*`, если том `s3_data` нужно сохранить) |
| `litellm`, `litellm-seed` | шлюз моделей по алиасам CRM и ERP (`infra/ai/litellm.models.yaml`); ключи провайдеров — только у `litellm` |
| `docling` | распознавание документов клиентов CRM (база знаний его не использует — только Markdown) |
| `crm-migrate`, `crm-api`, `crm-bot`, `crm-worker`, `crm-mcp-*`, `crm-web` | CRM из `apps/crm` (код монтируется; hot reload только у `crm-api`, остальные — `docker compose restart <сервис>`). `crm-bot` — Telegram-бот отдельным процессом (S0-4): polling или `/telegram/webhook` через Caddy; токен меняется в «Подключениях» без перезапуска; без токена и Telegram на стенде — `docs/runbooks/crm-bot.md` (заглушка Bot API) |
| `erp-backend`, `erp-mcp`, `erp-worker`, `erp-worker-ai`, `erp-beat`, `erp-web` | ERP из `apps/erp` (копия B2B, M1-ERP-01): Daphne мигрирует при старте (`AUTO_MIGRATE`), `erp-mcp` — инструменты ERP для агента CRM на SDK `mcp` (отдельный процесс, порт 8104 внутри сети, FIX-36; контракт `packages/contracts/mcp-tools.json` монтируется в контейнер), Celery-воркеры, Beat, nginx со сборкой Vite; код бэкенда монтируется, перезапуск руками |
| `cabinet-web` | Cabinet из `apps/cabinet` (M2-CAB-01): nginx со сборкой Vite, своей логики нет; пересборка — `make up`. Имя бота для ссылок — `TELEGRAM_BOT_USERNAME` в `.env`. Разработка экранов — `make -C apps/cabinet dev` (мок, без стенда) |
| `platform-bff`, `platform-web` | Платформа из `apps/platform` (INF-P0-4): BFF на FastAPI (сессии — `redis-cache` БД 3; CRM и ERP берёт по `http://crm-api:8000`, `http://erp-backend:8000`) и статика SPA (file-server Caddy, :8080). Нужен только `redis-cache`: без CRM/ERP `/api/v1/health` отвечает 200 со `status: degraded`. Определены в `dev.yml`; пересборка — `make up`. Срок жизни сессии — `PLATFORM_SESSION_TTL_HOURS` в `.env` |
| `caddy` | четыре домена ансамбля |
| `clickhouse`, `langfuse-worker`, `langfuse-web` | профиль `observability` |

## Повседневное

```
make ps                 # статус
make logs s=crm-api     # логи сервиса
make down               # остановить (данные в volumes остаются)
make up-obs             # с Langfuse
make -C apps/crm migrate  # нет: миграции CRM применяет сервис crm-migrate при каждом make up
```

Команды ERP на стенде: `make -C apps/erp migrate | shell | createsuperuser | seed`.

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

## Профиль `observability` (Langfuse)

`make up-obs` добавляет ClickHouse, `langfuse-worker`, `langfuse-web` (≈2,6 ГБ памяти сверх стенда: по замеру 2026-10-13 — ClickHouse 0,9 ГБ, web 0,9 ГБ, worker 0,8 ГБ) и `http://langfuse.localhost`.
Проверено 2026-10-13: `/api/public/health` через Caddy → `{"status":"OK","version":"4.56.0"}`, оба контейнера healthy. Healthcheck'и ходят по `process.env.HOSTNAME`: Next.js и воркер слушают только адрес из `HOSTNAME`, на `localhost`/`127.0.0.1` внутри контейнера — отказ.
Первый вход — регистрация в UI Langfuse, затем Settings → API Keys → ключи в `.env` (`CRM_LANGFUSE_PUBLIC_KEY`,
`CRM_LANGFUSE_SECRET_KEY`) и `make up`. Веб и воркер при старте применяют миграции ClickHouse; если воркер убит по памяти
посреди миграций (код 137), веб падает с «Table … already exists». Лечение — пересоздать ClickHouse с нуля (трейсов ещё нет):

```
docker compose -p rt-platform --profile observability rm -sf clickhouse langfuse-web langfuse-worker
docker volume rm rt-platform_clickhouse_data rt-platform_clickhouse_logs
make up-obs
```

При нехватке памяти Docker Desktop (текущий объём — `docker info`, HANDOFF §6) на время старта можно остановить `docling`, `crm-worker`,
`crm-mcp-*` и вернуть их `make up`.

### ИИ ERP: ключ шлюза, бюджет, трейсы (M1-ERP-06)

ERP ходит в LiteLLM своим виртуальным ключом `ERP_LITELLM_API_KEY` (генерирует `make env`; в старом `.env` его нет —
выполните `make env`, он допишет переменную). Одноразовый сервис `erp-ai-gateway` при `make up` регистрирует ключ в
LiteLLM: бюджет на день `ERP_AI_DAILY_BUDGET_USD` (сутки UTC) и колбэк Langfuse (`ERP_LANGFUSE_*`, пусто — ключи
CRM `CRM_LANGFUSE_*`, общий проект). После смены ключей Langfuse или бюджета — `make -C apps/erp ai-gateway-sync`.
Состояние без вызова моделей — `make -C apps/erp ai-status` (шлюз жив, бюджет ключа, расход и ошибки за сегодня).
Трейс ERP в Langfuse: имя `erp.<функция>`, `sessionId` = id ИИ-задачи, пользователь `erp-staff-<id>`, в метаданных версия
промпта. Langfuse v4 в режиме events_only: публичные `/api/public/traces` и `/sessions` отвечают 404 — для проверки из
консоли `GET /api/public/v2/observations?fields=core,basic,metadata` (Basic `pk:sk`). Проверка пути без платных вызовов —
временная mock-модель LiteLLM (`litellm_params.mock_response`), поле `mock_response` в теле запроса прокси игнорирует
и идёт к провайдеру.

## Telegram Mini App на стенде: ограничение и проверка через туннель (FIX-15)

**Ограничение.** Стенд `make up` — обычный `http://*.localhost`, без TLS. Mini App требует HTTPS-адрес, а cookie сессии
портала в Mini App — `SameSite=None; Secure` (Cabinet открыт во фрейме Telegram, это другой сайт; настройка ERP
`PORTAL_COOKIE_SAMESITE=None`): по `http` браузер её не сохранит. Поэтому на стенде вход из Mini App не проверить,
а веб-вход по magic-link работает на умолчании (`PORTAL_COOKIE_SAMESITE=Lax`). Не меняйте умолчание на `None` на стенде
без туннеля: вход в браузер по `http` перестанет работать.

**Проверка через туннель** (тестовый бот; раз в вехе, перед гейтом M2 — OWNER-CHECKLIST «До M2»):

1. Поднимите туннель на Caddy стенда с подменой `Host`, чтобы Caddy отдал Cabinet:
   `cloudflared tunnel --url http://localhost:8088 --http-host-header cabinet.localhost` (порт — `HTTP_PORT` из `.env`;
   у ngrok: `ngrok http 8088 --host-header=cabinet.localhost`). Туннель даст адрес вида `https://<имя>.trycloudflare.com`.
2. В `.env`: `PORTAL_COOKIE_SAMESITE=None`, `CABINET_URL=https://<имя>.trycloudflare.com`, `TELEGRAM_BOT_TOKEN` тестового бота
   и `TELEGRAM_BOT_USERNAME`; затем `make up` (перезапуск `erp-backend`). Django видит `Host: cabinet.localhost` — ALLOWED_HOSTS менять не нужно.
3. BotFather → тестовый бот → Menu Button / Mini App → `https://<имя>.trycloudflare.com`.
4. Откройте бота на телефоне (приложение Telegram), нажмите кнопку: в ответе `POST /api/portal/v1/auth/telegram` — `Set-Cookie:
   portal_session=…; HttpOnly; Secure; SameSite=None; Path=/api/portal`, экран «Запросы» открывается. Веб Telegram и настольные
   браузеры с блокировкой сторонних cookie (Safari, Chrome Incognito) cookie фрейма могут не принять — проверка идёт на телефоне.
5. Верните `PORTAL_COOKIE_SAMESITE=Lax` и `CABINET_URL=http://cabinet.localhost`, `make up`.

На проде (M5) `PORTAL_COOKIE_SAMESITE=None` задаётся в окружении `production` вместе с `CABINET_ORIGIN=https://cabinet.railtech.uz`:
у ERP на `DEBUG=False` в CORS только этот origin.

## Проверка: токена ссылки входа нет в журнале ERP (FIX-15)

Daphne запущен с `-v 0` (`infra/compose/base.yml`), журнал запросов ведёт Django (`core.access`) и прячет токен фильтром:

```
make up                                    # перезапуск erp-backend с новой командой
curl -s -o /dev/null --resolve cabinet.localhost:8088:127.0.0.1 http://cabinet.localhost:8088/api/portal/v1/auth/magic/PROBE-TOKEN-4242
docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env logs erp-backend | grep -c PROBE-TOKEN-4242   # 0
docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env logs erp-backend | grep 'auth/magic'          # …/auth/magic/[REDACTED] 404 …
```

Остаточный риск: журналы фронтового прокси (Caddy с включённым `log`, nginx `cabinet-web`) пишут путь страницы
`/auth/magic/<токен>` (SPA-маршрут Cabinet). Ссылки из писем с FIX-21 ведут на `/auth/magic#token=<токен>`: фрагмент браузер на сервер не отправляет, в журналах прокси токена нет; Cabinet меняет его на сессию через `POST /auth/magic` (FIX-24). `GET /auth/magic/{токен}` снят в контракте 0.3.0 (FIX-25) и отвечает 404; путь в журнале всё равно прячется фильтром — проверка выше показывает `…/auth/magic/[REDACTED] 404`.

## Если не поднимается

- Поменяли `infra/caddy/Caddyfile.dev` (или подтянули его `git pull`), а домены ведут себя по-старому: Caddyfile смонтирован одиночным файлом, и после замены файла git'ом контейнер видит старую копию или пустоту («open /etc/caddy/Caddyfile: no such file»). Лечение — `make caddy-reload` (пересоздаёт контейнер Caddy).

- Бот молчит, а `crm-api` в порядке: `make logs s=crm-bot`, статус — «Подключения» / «Состояние системы» (процесс `crm-bot` без пульса там помечен «не отвечает»). Бота запускает только `crm-bot`: `docker compose restart crm-bot`.
- `make ps` → `crm-api` не healthy: `make logs s=crm-api`; чаще всего — не применились миграции (`make logs s=crm-migrate`).
- `litellm` не healthy: `make logs s=litellm`; база `litellm` создаётся `db-init` — проверьте его лог.
- `docling` стартует до минуты (образ 7 ГБ); `crm-worker` ждёт его.
- Всё снести и начать заново: `make down && docker volume rm $(docker volume ls -q | grep '^rt-platform_')`.
