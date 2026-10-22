# rt-bus — шина событий RailTech Platform v1

Библиотека `rt_bus` (дистрибутив `rt-bus`, Python 3.12): единственный способ сервиса публиковать события своих сущностей и
получать чужие (ADR-0014, ORCHESTRATOR §3.14). Нормативка — `docs/CONTRACTS.md` §9 «Шина rt_bus», runbook волны 11 §2,
решения L1–L11. Транспорт v1 — PostgreSQL outbox сервиса + ретранслятор + подписанный HTTP к подписчикам; бизнес-код
транспорт не видит (v2 — NATS JetStream, этап F).

```
издатель: изменение + publish() в одной транзакции → rt_bus_outbox
          pump(): relay — outbox → rt_bus_delivery (по строке на подписчика, SKIP LOCKED)
                  deliver — аренда пачки → POST <подписчик>/bus/v1/events (HMAC v2) → delivered | повтор | dead
подписчик: receive() — подпись, окно, конверт → rt_bus_inbox (id — ключ) → очередь → process_inbox() → @subscribe-обработчик
```

## Состав

| Модуль | Что |
|---|---|
| `rt_bus` (ядро) | `BusConfig`, `Event`/`new_event`, `SchemaRegistry`, подписки, подпись, политики повторов, `subscribe`, корреляция |
| `rt_bus.sqlalchemy` | `bus_tables(metadata)`, `AsyncBus` — SQLAlchemy 2 async (CRM, EDS, сервисы на FastAPI) |
| `rt_bus.django` | приложение Django (модели и миграции), `DjangoBus`, `views.bus_view`, `middleware.CorrelationMiddleware`, `stash.DjangoCacheStash` (ERP) |
| `rt_bus.memory` | `MemoryReceiver` — приёмник без БД (BFF: у него нет базы, ADR-0011) |
| `rt_bus.fastapi` | `bus_router(...)` (`POST /bus/v1/events`), ASGI `CorrelationMiddleware` |
| `rt_bus.contrib.celery`, `rt_bus.contrib.procrastinate` | периодические задачи `pump`, обработка inbox, подбор зависших, метрики, уборка |

Зависимости ядра: `httpx`, `jsonschema`, `referencing`, `PyYAML`. Экстры: `[sqlalchemy]` (SQLAlchemy 2 async; драйвер —
сервиса: psycopg 3 как в CRM или asyncpg), `[django]` (Django ≥ 5.2), `[fastapi]`. Celery и Procrastinate пакет не
тянет — их ставит сервис.

## Установка

Пакет ставится по пути, сборочных шагов вне каталога нет (hatchling):

```bash
# CRM, BFF (uv)
uv add --editable "../../packages/rt-bus[sqlalchemy,fastapi]"     # BFF: "../../packages/rt-bus[fastapi]"
# ERP (pip)
pip install -e "packages/rt-bus[django]"                           # в образе — копия каталога: pip install "/src/rt-bus[django]"
```

Окружение сервиса:

| Переменная | Что |
|---|---|
| `RT_BUS_CONTRACTS_DIR` | каталог схем `packages/contracts/events` (в образе — вложенная копия). Не задана — поиск `packages/contracts/events` вверх от пакета и от текущего каталога |
| `RT_BUS_SUBSCRIPTIONS` | файл подписок (по умолчанию `bus/subscriptions.yaml` рядом с каталогом схем) |
| `RT_BUS_SECRET_<ИЗДАТЕЛЬ>_<ПОДПИСЧИК>` | секрет пары (верхний регистр, `-` → `_`), несколько через запятую: первым подписывают, принимают любой |
| `RT_BUS_ENDPOINT_<ИМЯ>` | переопределение адреса подписчика (поле `endpoint_env` в подписках) |

Своё хранилище секретов (сопряжение в БД) — `BusConfig(secrets=lambda publisher, subscriber: [...])`.

## Таблицы (L9)

`rt_bus_outbox`, `rt_bus_delivery`, `rt_bus_inbox`, `rt_bus_subscriber_state` — одна схема в обоих адаптерах (тест
сравнивает столбцы, типы, индексы и ограничения миграции Django с `bus_tables`).

- **SQLAlchemy**: `bus_tables(Base.metadata)` при импорте моделей сервиса → `alembic revision --autogenerate` увидит
  четыре таблицы; миграция — в репозитории сервиса.
- **Django**: `INSTALLED_APPS += ["rt_bus.django"]` (метка `rt_bus`) → `manage.py migrate rt_bus`.

## Публикация

```python
from rt_bus import BusConfig
from rt_bus.sqlalchemy import AsyncBus

bus = AsyncBus(BusConfig(service="crm"), sessions=async_sessionmaker(engine))

async with sessions() as session, session.begin():
    client.name = new_name
    await bus.publish(session, "uz.railtech.crm.client.updated.v1", data, subject=f"client/{client.id}")
```

```python
from rt_bus.django.bus import DjangoBus
from rt_bus.django.stash import DjangoCacheStash

bus = DjangoBus(BusConfig(service="erp"), stash=DjangoCacheStash())  # stash — для кода акцепта, см. ниже

with transaction.atomic():
    quote.save()
    bus.publish("uz.railtech.erp.quote.sent.v1", data, subject=deal.number)
```

- Вне транзакции — `NotInTransactionError` (SQLAlchemy: `session.in_transaction()`, Django: `in_atomic_block`); откат
  транзакции — строки outbox нет.
- Конверт строит библиотека: `id` UUID, `time` UTC, `source` = `rt://<service>`, `dataschema` по типу, `tenant`,
  `correlationid` и `traceparent` из контекста (иначе новый UUID). `data` проверяется строго по схеме типа
  (`additionalProperties: false`) — ошибка `EventValidationError` до записи.
- Django: `DjangoBus(..., wakeup=tasks.wakeup)` — после коммита будит `pump` (иначе — по расписанию beat).

## Подписки и доставка

`bus/subscriptions.yaml` (L5): издатель доставляет подписчику только свои события (`source == rt://<service>`), себе не
доставляет, `enabled: false` — новых доставок нет. Файл перечитывается по mtime: **новый подписчик = строка в файле +
секрет пары**, без перезапуска и правки кода.

Доставка: `POST <endpoint>`, `Content-Type: application/cloudevents+json`, заголовки `X-RT-Publisher`, `X-RT-Event-Id`,
`X-RT-Timestamp` (момент попытки), `X-RT-Signature: sha256=HMAC(secret, "{id}.{timestamp}.{body}")`, `X-Request-ID`
(= `correlationid`), `traceparent`. HTTP — вне транзакций: доставка берётся в аренду (`in_flight` до `lease_until`, 60 с),
итог пишется по токену аренды; упавший воркер отдаёт доставку другому по истечении аренды. Два воркера не доставляют
одно и то же (`FOR UPDATE SKIP LOCKED`).

| Ответ | Итог |
|---|---|
| 2xx | `delivered` |
| 400, 404, 410, 413, 415, 422 | сразу `dead` (DLQ); «повторить» доступно |
| 401, 408, 409, 429, 5xx, сеть, таймаут | повтор через 30 с, 2 мин, 10 мин, 1 ч, 6 ч, 24 ч (± 20 %); `Retry-After` у 429/503 заменяет шаг; неудача шестого повтора (7-я попытка) — `dead` |
| нет секрета пары, подписчика нет в файле | отложить на 5 мин, попытка не засчитывается |

**Предохранитель** на подписчика: 5 повторяемых ошибок подряд → пауза 5 мин (остальные подписчики идут), затем одна
пробная доставка; успех сбрасывает счётчик, неудача — снова пауза. Неповторяемые ответы (4xx из таблицы) его не трогают.

## Приёмник и обработчики

```python
from rt_bus import subscribe


@subscribe("uz.railtech.crm.client.updated.v1")  # маска fnmatch: "uz.railtech.crm.contact.*.v1"
def on_client_updated(event):  # Django: (event); SQLAlchemy: async (event, session)
    ...  # memory/BFF: async (event)
```

- FastAPI: `app.include_router(bus_router(lambda: container.bus))`; Django: `path("bus/v1/events", bus_view(get_bus))`;
  BFF: `bus_router(MemoryReceiver(BusConfig(service="platform-bff")))`.
- Порядок: подпись (любой действующий секрет пары, constant-time) → окно 300 с → конверт → `source` = издатель →
  inbox (`event id` — ключ; повтор — 200 `duplicate` без обработки) → `enqueue(event_id)` после коммита.
- Ответы: 200 (`received`, `duplicate`, `skipped`, `processed`), 401 (подпись, неизвестный издатель, вне окна, чужой
  `source`), 400 (не JSON, не конверт), 422 (`data` известного типа не по схеме), 503 (упал inline-обработчик).
- `data` проверяется терпимо (L10): `additionalProperties` не отказ; тип, обязательное поле, enum — 422.
- Нет обработчика, нет схемы типа, версия выше поддерживаемой (`….v2` при обработчике `….v1`) — запись `skipped`, 200.
- Обработка: задача очереди вызывает `bus.process_inbox(event_id)` — обработчики в одной транзакции со статусом
  (`processed`); исключение — `failed` с текстом. Повтор задачи по уже обработанной записи ничего не делает.
- `inline=True` — обработчик выполняется в запросе с полным событием (для кода акцепта: CRM шлёт код в Telegram, в
  inbox — маска `***`); ошибка — откат записи и 503, издатель повторит.

## Периодические задачи

ERP (Celery):

```python
from rt_bus.contrib.celery import install

tasks = install(celery_app, get_bus)  # rt_bus.pump каждые 5 с, requeue_stuck_inbox 60 с, log_metrics 300 с, purge сутки
bus.enqueue = tasks.enqueue  # обработка inbox — задача rt_bus.process_inbox
bus.wakeup = tasks.wakeup  # pump сразу после коммита publish
```

CRM (Procrastinate; cron с шестым полем — секунды):

```python
from rt_bus.contrib.procrastinate import install

tasks = install(procrastinate_app, get_bus, pump_cron="* * * * * */5")
bus.enqueue = tasks.enqueue
```

Без очереди — `asyncio.create_task(bus.run_forever(interval=2))` в lifespan. Повторы доставки — по `next_attempt_at` в
таблице, не ретраями очереди.

## Ручное управление и журнал

| Что | API (SQLAlchemy — те же методы с `await`) |
|---|---|
| «Повторить» доставку (`dead` или ожидающую) | `bus.retry_delivery(delivery_id)` — попытки с нуля; подписчик на паузе получает пробу сразу |
| «Повторить все dead» | `bus.retry_all_dead(subscriber=None)` |
| Журнал доставок | `bus.list_deliveries(status=, subscriber=, event_type=, event_id=, before_id=, limit=)` → `DeliveryView` |
| «Повторить» запись inbox (`failed`/`skipped`) | `bus.retry_inbox(event_id)` |
| Журнал inbox | `bus.list_inbox(status=, event_type=, before=, limit=)` → `InboxView` |
| Подобрать `received`, не попавшие в очередь | `bus.requeue_stuck_inbox(older_than=60)` |
| Уборка | `bus.purge(older_than=timedelta(days=30))` — доставленное и обработанное; `dead` остаётся |

## Метрики

`bus.metrics()` → `BusMetrics`: `outbox_pending`, `oldest_undelivered_age_seconds`, `dlq_size`, `inbox_received`,
`inbox_failed`, по подписчику — `pending`, `in_flight`, `dead`, возраст самого старого, `consecutive_failures`, `paused`.
`bus.log_metrics()` — одна строка `rt_bus_metrics …` (и всё в `extra`).

## Корреляция

`X-Request-ID`/`traceparent` запроса → контекст (`CorrelationMiddleware` для Django и ASGI, или
`rt_bus.set_correlation(...)` из своего middleware) → `correlationid` конверта → `X-Request-ID` доставки → контекст
обработчика → логи: `logging`-фильтр `rt_bus.CorrelationFilter` (`%(correlation_id)s`) или процессор structlog
`rt_bus.structlog_processor`.

## Секретные поля

`BusConfig.secret_fields` (по умолчанию `payload.code` у `uz.railtech.erp.quote.acceptance_code_requested.v1`,
CONTRACTS §9.2). Издатель с хранилищем (`stash=`, Django — `DjangoCacheStash`, TTL 20 мин) пишет в outbox маску, а
значение подставляет в тело доставки; истёк — `dead` `SECRET_EXPIRED`. Приёмник хранит в inbox маску; полное событие
видят только inline-обработчики.

## Разработка

```bash
make -C packages/rt-bus install
make -C packages/rt-bus test-unit   # без базы, секунды
make -C packages/rt-bus check       # ruff, mypy --strict, миграция Django, все тесты на PostgreSQL
```

`make test` берёт `RT_BUS_TEST_DATABASE_URL` (CI — service-контейнер) или поднимает одноразовый `postgres:17` в Docker
(имя — `RT_BUS_PG_CONTAINER`, удаляется после прогона). Тесты SQLAlchemy идут на psycopg 3 и asyncpg, Django — на psycopg2
(как ERP) и psycopg 3 (отдельные процессы pytest). HTTP — `httpx.MockTransport`/`ASGITransport`, без сети. Схемы — копия
контракта B2 в `tests/fixtures/contracts` (после слияния #180 можно перевести тесты на `packages/contracts`).
