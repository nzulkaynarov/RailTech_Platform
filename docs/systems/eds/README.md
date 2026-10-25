# EDS (электронный документооборот) — `apps/eds`
Статус: действует (каркас — волна 12, задача E2; домен — E3) · Владелец: архитектор · Обновлено: 2026-10-26

EDS — отдельный сервис со своей базой `eds` (ADR-0015): письма и резолюции, служебные записки, заявления, отчёты, общий движок
маршрутов согласования, реестр и нумерация документов. Стек — [ADR-0013](../../adr/0013-stack-and-standards.md): FastAPI + SQLAlchemy 2
(async, psycopg 3) + Alembic + Procrastinate. Интеграции — только через шину `rt_bus` ([ADR-0014](../../adr/0014-integration-bus-rt-bus.md),
[`rt-bus.md`](../../architecture/rt-bus.md)). План волны — [`wave12-eds-c1.md`](../../runbooks/wave12-eds-c1.md). Правила кода — [`CONVENTIONS.md`](CONVENTIONS.md).

| Владеет данными | Публикует события | Подписывается на |
|---|---|---|
| входящие и исходящие письма с регистрацией, резолюции, служебные записки, заявления, отчёты; **общий движок маршрутов согласования** (КП, договор, служебка); реестр и архив документов (метаданные, версии, сканы, журнал «кто и когда») | `letter.*`, `document.*`, `approval.requested/decided` (контракт — `packages/contracts/events/eds/`) | CRM: `identity.user.*`; ERP: `request.created`, `quote.ready_for_approval` |

## Что сделано (E2) и что дальше

В каркасе (E2) **нет доменных моделей**: есть всё, на чём стоит домен.

| Есть | Где |
|---|---|
| `GET /health` — живость и база (`200`/`503`), `X-Request-ID` в ответе и в каждой записи журнала, единый формат ошибок `Error` (`code`, `message`, `source="eds"`, `details`) | `app/api/health.py`, `app/errors.py`, `app/log.py` |
| вход: `POST /api/v1/auth/sso/exchange` (SSO-токен сотрудника CRM → токен доступа EDS), `GET /api/v1/me`, зависимости `current_employee` и `require_permission(*коды)` | `app/api/`, `app/security/`, `app/services/sso.py` |
| проекция сотрудников `employees` из `identity.user.created/updated/deactivated` (права `permissions.eds`), идемпотентно | `app/bus/handlers.py`, `app/services/employees.py` |
| шина: таблицы outbox/inbox, приёмник `POST /bus/v1/events`, ретранслятор и обработка inbox в `eds-worker`, `python -m app bus …` | `app/bus/`, `app/tasks/`, `app/cli/bus_cli.py` |
| миграции Alembic (одна голова): Procrastinate, `rt_bus_*`, `employees`, `sso_jti` | `alembic/versions/` |

Дальше: **E3** — домен (реестр и нумерация, письма, документы, маршруты, файлы в S3, журнал) и API по `packages/contracts/openapi/eds.yaml`; **E4** — CRM
публикует `permissions.eds` и выдаёт токен сотрудника для EDS; **E5** — ERP; **E6** — гейт этапа C1. Экраны — этап D (Платформа).

## Структура

```
apps/eds/
  app/            api/ (health, v1/auth, v1/me) · bus/ (handlers, snapshots, runtime) · security/ · services/ · tasks/ · cli/
                  config.py · db.py · log.py · errors.py · container.py · main.py · __main__.py
  alembic/        env.py, versions/ (YYYYMMDD_HHMM_slug), sql/ (снимок схемы Procrastinate 3.10.0)
  tests/          unit (без базы) и pg (настоящий PostgreSQL) — маркер `pg`
  Dockerfile      один образ: api, worker, миграции (`python -m app api|worker`, `alembic upgrade head`)
```

## Команды (из корня репозитория)

| Что | Команда |
|---|---|
| зависимости (новый worktree — первым шагом) | `make -C apps/eds install` |
| ruff, mypy `--strict`, все тесты | `make check-eds` (то же: `make -C apps/eds check`) |
| тесты без базы (секунды) | `make -C apps/eds test-unit` |
| один тест | `cd apps/eds && ./scripts/with_pg.sh uv run pytest tests/<файл>.py -x -q` |
| миграция | `make -C apps/eds migration m="…"` (нужна база по `EDS_DATABASE_URL`) |
| как CI | `scripts/ci_local.sh eds` · образ под CPU `qemu64`: `make cpu-check args="rt-eds"` (на Mac arm64 долго) |

Тесты идут против настоящего PostgreSQL: без `EDS_TEST_DATABASE_URL` `scripts/with_pg.sh` поднимает одноразовый `postgres:17` (удаляется после прогона; имя —
`EDS_PG_CONTAINER`). Стенд ансамбля и его базы тестами не затрагиваются.

## Переменные окружения

Читает только `app/config.py` (`pydantic-settings`); в compose их задаёт `infra/compose/base.yml` из `.env` (шаблоны — `.env.example`, `infra/.env.prod.example`).

| Переменная | Что задаёт |
|---|---|
| `EDS_DATABASE_URL` | `postgresql+psycopg://<роль>:<пароль>@<хост>:5432/eds` (прод: роль `eds_app`, `?sslmode=require`) |
| `EDS_ACCESS_SECRET` | секрет токена доступа EDS (HS256, 15 минут), ≥ 16 символов |
| `PLATFORM_SSO_SECRET` | общий секрет SSO-токена сотрудника CRM; ротация — два значения через запятую |
| `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET` | RustFS: свой ключ сервиса, бакет `eds-private` (в `.env` — `S3_EDS_*`); файлы появятся с доменом (E3) |
| `RT_BUS_SECRET_CRM_EDS`, `RT_BUS_SECRET_ERP_EDS` | приём событий CRM и ERP (проверка подписи) |
| `RT_BUS_SECRET_EDS_ERP`, `RT_BUS_SECRET_EDS_PLATFORM_BFF` | подпись доставки событий EDS в ERP и BFF Платформы |
| `RT_BUS_CONTRACTS_DIR`, `RT_BUS_SUBSCRIPTIONS` | схемы событий и подписки; в образе — `/opt/rt/contracts`, задаёт Dockerfile |
| `RT_BUS_ENDPOINT_<ИМЯ>` | необязательное переопределение адреса подписчика |
| `APP_ENV` (`dev`/`prod`/`test`), `LOG_LEVEL`, `LOG_FORMAT` (`json`/`console`), `EDS_VERSION`, `WORKER_CONCURRENCY` | служебные |

## Вход и права

Своей формы входа у EDS нет. Нормативно — [`sso-token.md`](../../architecture/sso-token.md), «Токен сотрудника для EDS» (решение L-C1-1), и [`wave12-eds-c1.md`](../../runbooks/wave12-eds-c1.md) §2.2:

1. BFF берёт у CRM SSO-токен (`aud=eds`, 60 с, одноразовый `jti`) и вызывает `POST /api/v1/auth/sso/exchange {token}`.
2. Проверки по порядку: подпись `PLATFORM_SSO_SECRET` (оба значения) → `aud == "eds"` → срок (`exp` не прошёл с допуском 5 с, `exp − iat ≤ 60 (+5)`) → `jti` не встречался
   (таблица `sso_jti`, 10 минут, уборка задачей) → сотрудник **только по `sub`** в проекции: нет — `403 USER_NOT_PROVISIONED`, неактивен — `403 USER_INACTIVE`.
   Отказы первых четырёх — `401 INVALID_SSO_TOKEN` (`details.reason`: `signature`, `audience`, `expired`, `lifetime`, `replayed`, `malformed`). Обмен никого не создаёт.
3. Ответ `{access_token, token_type: "bearer", expires_in: 900}`; refresh нет (истёк — новый SSO-токен у CRM).
4. Каждый запрос — `Authorization: Bearer`; сотрудник и его права берутся из проекции **на момент запроса**: отзыв роли и отключение действуют сразу. Нет права — `403 FORBIDDEN`
   (`details.permission`). Коды v1: `letters.read`, `letters.register`, `letters.resolve`, `memos.create`, `memos.approve`, `approvals.decide`, `registry.read`, `registry.export`.

Тест `tests/test_contract_permissions.py` сверяет права маршрутов с `x-rt-permissions` в `eds.yaml`.

## Шина

Подписчик `eds` в `packages/contracts/bus/subscriptions.yaml` получает `identity.user.*`, `erp.request.created`, `erp.quote.ready_for_approval` по `POST http://eds-api:8000/bus/v1/events`
(только сеть compose). Приём: подпись → inbox → задача `rt_bus.process_inbox` в `eds-worker`. Проекция сотрудников — `app/bus/handlers.py`:

- более старый снимок не применяется (версия — `user.updated_at`, у `deactivated` — время события); повтор безвреден;
- права читаются терпимо: нет `user.permissions.eds` (CRM до E4) — прав нет; неизвестные коды хранятся, но не действуют;
- `deactivated` раньше `created` оставляет «надгробие» (`email = ''`), запоздавший старый снимок доступ не вернёт.

Типы без обработчика (`erp.request.created`, `erp.quote.ready_for_approval` — домен, E3) приёмник записывает как `skipped` и отвечает 200. Эксплуатация:
`docker compose … exec eds-api python -m app bus status|dead|failed|retry|retry-dead|retry-inbox`.

## Как поднять локально

`make env && make up` поднимает весь ансамбль, включая `eds-migrate` → `eds-api` и `eds-worker` (база `eds` создаётся `db-init`). Порт EDS на хост не публикуется и в Caddy маршрута нет —
смотреть только изнутри сети compose:

```bash
docker compose -f infra/compose/base.yml -f infra/compose/dev.yml exec eds-api \
  python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/health').read().decode())"
```

Отдельный стенд для проверки без трогания общего: `docker compose -p rt-c1 …` со своим `.env` и `HTTP_PORT` (ORCHESTRATOR §4); поднимать только нужные сервисы
(`postgres`, `s3-init`, `eds-migrate`, `eds-api`, `eds-worker`), после — `down -v`.

## Прод

Образ `rt-eds` собирает `.github/workflows/deploy.yml`; в `prod.yml` — `eds-api`, `eds-worker`, `eds-migrate` (по 192 МБ у api и worker). База `eds` и роль `eds_app` — на VPS 2
(`infra/db/prod-init.sh`, `pg_hba`, бэкап и WAL-G включают `eds`), бакет `eds-private` и ключ `S3_EDS_*` — `s3-init`. Миграции — `deploy.sh` после pg_dump-гейта. Что сделать
владельцу до первого деплоя — [`deploy.md`](../../runbooks/deploy.md), раздел «EDS — сервис документооборота»; память — [`servers.md`](../../runbooks/servers.md).
**Внешнего маршрута нет** ни на одном домене (решение волны 12 §4 п. 4); `make deploy-check` это проверяет (`infra/deploy/tests/eds-prod-test.sh`).
