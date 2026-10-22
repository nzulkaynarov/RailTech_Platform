# rt_bus — шина событий v1: API и подключение

Библиотека [`packages/rt-bus`](../../packages/rt-bus/) (дистрибутив `rt-bus`, импорт `rt_bus`, Python 3.12) — единственный
способ, которым сервис публикует события своих сущностей и получает чужие. Основание: [ADR-0014](../adr/0014-integration-bus-rt-bus.md),
правило «интеграции только через шину» (ORCHESTRATOR §3 п. 14). Нормативка: CONTRACTS §9 «Шина rt_bus», [runbook волны 11](../runbooks/wave11-bus-v1.md) §2,
решения лида L1–L11. Транспорт v1 — PostgreSQL outbox сервиса, ретранслятор и подписанный HTTP к подписчикам. Бизнес-код
транспорт не видит (v2 — NATS JetStream, этап F).

```text
издатель:  изменение + publish() в одной транзакции → rt_bus_outbox
           pump(): relay — outbox → rt_bus_delivery (строка на подписчика, SKIP LOCKED)
                   deliver — аренда пачки → POST <подписчик>/bus/v1/events (HMAC v2) → delivered | повтор | dead
подписчик: receive() — подпись, окно, конверт → rt_bus_inbox (id — ключ) → очередь → process_inbox() → обработчик
```

## 1. Состав

| Модуль | Что в нём |
|---|---|
| `rt_bus` (ядро) | `BusConfig`, `Event`/`new_event`, `SchemaRegistry`, подписки, подпись, политики повторов, `subscribe`, корреляция |
| `rt_bus.sqlalchemy` | `bus_tables(metadata)`, `AsyncBus` — SQLAlchemy 2 async (CRM, EDS, сервисы на FastAPI) |
| `rt_bus.django` | приложение Django (модели, миграции), `DjangoBus`, `views.bus_view`, `middleware.CorrelationMiddleware`, `stash.DjangoCacheStash` (ERP) |
| `rt_bus.memory` | `MemoryReceiver` — приёмник без БД (BFF: своей базы у него нет, ADR-0011) |
| `rt_bus.fastapi` | `bus_router(...)` (`POST /bus/v1/events`), ASGI `CorrelationMiddleware` |
| `rt_bus.contrib.celery`, `rt_bus.contrib.procrastinate` | периодический `pump`, обработка inbox, подбор зависших и автоповторов, метрики, уборка |

Зависимости ядра: `httpx`, `jsonschema`, `referencing`, `PyYAML`. Экстры:
- `[sqlalchemy]` — SQLAlchemy 2 async; драйвер выбирает сервис (psycopg 3, как в CRM, или asyncpg);
- `[django]` — Django ≥ 5.2;
- `[fastapi]`.

Celery и Procrastinate пакет не тянет: их ставит сам сервис.

## 2. Установка и окружение

Пакет ставится по пути. Сборочных шагов вне его каталога нет (сборка — hatchling).

```bash
uv add --editable "../../packages/rt-bus[sqlalchemy,fastapi]"   # CRM; BFF — "../../packages/rt-bus[fastapi]"
pip install -e "packages/rt-bus[django]"                         # ERP; в образе — копия каталога пакета
```

| Переменная | Что задаёт |
|---|---|
| `RT_BUS_CONTRACTS_DIR` | каталог схем `packages/contracts/events` (в образе — вложенная копия). Не задана — `packages/contracts/events` ищется вверх от пакета и от текущего каталога |
| `RT_BUS_SUBSCRIPTIONS` | файл подписок; по умолчанию `bus/subscriptions.yaml` рядом с каталогом схем |
| `RT_BUS_SECRET_<ИЗДАТЕЛЬ>_<ПОДПИСЧИК>` | секрет пары (верхний регистр, `-` → `_`); несколько через запятую: первым подписывают, принимают любой |
| `RT_BUS_ENDPOINT_<ИМЯ>` | адрес подписчика вместо записанного в файле (поле `endpoint_env` в подписках) |

Своё хранилище секретов (например, сопряжение в БД) подключается так: `BusConfig(secrets=lambda publisher, subscriber: [...])`.

## 3. Таблицы (L9)

`rt_bus_outbox`, `rt_bus_delivery`, `rt_bus_inbox`, `rt_bus_subscriber_state` — одна схема в обоих адаптерах. Тест
сравнивает столбцы, типы, индексы и ограничения миграции Django с `bus_tables`.

- **SQLAlchemy:** `bus_tables(Base.metadata)` вызвать при импорте моделей сервиса — тогда `alembic revision --autogenerate`
  увидит четыре таблицы. Миграция лежит в репозитории сервиса.
- **Django:** `INSTALLED_APPS += ["rt_bus.django"]` (метка `rt_bus`), затем `manage.py migrate rt_bus`.

## 4. Публикация

```python
bus = AsyncBus(BusConfig(service="crm"), sessions=async_sessionmaker(engine))
async with sessions() as session, session.begin():
    client.name = new_name
    await bus.publish(session, "uz.railtech.crm.client.updated.v1", data, subject=f"client/{client.id}")

bus = DjangoBus(BusConfig(service="erp"), stash=DjangoCacheStash())     # ERP
with transaction.atomic():
    quote.save()
    bus.publish("uz.railtech.erp.quote.sent.v1", data, subject=deal.number)
```

- Вызов вне транзакции — `NotInTransactionError` (SQLAlchemy проверяет `session.in_transaction()`, Django — `in_atomic_block`).
  При откате транзакции строки outbox нет.
- Конверт строит библиотека:
  - `id` — UUID, `time` — UTC;
  - `source` = `rt://<service>`, `dataschema` — по типу, `tenant`;
  - `correlationid` и `traceparent` — из контекста, иначе новый UUID.
- `data` проверяется строго по схеме типа (`additionalProperties: false`): ошибка — `EventValidationError` до записи.
- **Секретные поля по умолчанию закрыты.** Тип с полями из `BusConfig.secret_fields` (по умолчанию `payload.code` у
  `uz.railtech.erp.quote.acceptance_code_requested.v1`, CONTRACTS §9.2) без хранилища `stash=` даёт `ConfigError`.
  - С хранилищем: в outbox пишется маска `***`, значение кладётся в `stash` (Django — `DjangoCacheStash`, TTL 20 мин) и
    подставляется в тело доставки. Значение истекло — доставка уходит в `dead` с ошибкой `SECRET_EXPIRED`.
  - В текстах ошибок схемы значения секретных полей тоже заменяются на `***`.
- Django: `DjangoBus(..., wakeup=tasks.wakeup)` будит `pump` после коммита; иначе `pump` идёт по расписанию.

## 5. Подписки и доставка

Файл `bus/subscriptions.yaml` (L5):
- издатель доставляет подписчику только свои события (`source == rt://<service>`) и себе не доставляет;
- файл перечитывается по mtime, без перезапуска: **новый подписчик — это строка в файле + секрет пары**;
- `enabled: false` останавливает и новые раскладки, и уже разложенные `pending`-доставки: они ждут включения подписчика
  без попыток и проб; после `enabled: true` уходят.

Как устроена доставка:
- запрос: `POST <endpoint>`, `Content-Type: application/cloudevents+json`;
- заголовки:
  - `X-RT-Publisher`, `X-RT-Event-Id`;
  - `X-RT-Timestamp` — момент попытки;
  - `X-RT-Signature: sha256=HMAC(secret, "{id}.{timestamp}.{body}")`;
  - `X-Request-ID` (= `correlationid`), `traceparent`.
- HTTP идёт вне транзакций. Доставка берётся в аренду (`in_flight` до `lease_until`, `lease_seconds` = 60 с), итог
  записывается по токену аренды. Упавший воркер отдаёт доставку другому по истечении аренды. Два воркера одну доставку не
  отправляют (`FOR UPDATE SKIP LOCKED`).
- **Дедлайн попытки** (`attempt_deadline`, 25 с; таймаут httpx `http_timeout`, 10 с — на каждую операцию отдельно):
  медленный ответ не держит пачку и аренду. Итог по дедлайну — повтор с ошибкой `DeadlineExceeded`.
- Django: `deliver()` и `pump()` внутри `transaction.atomic()` — `InTransactionError` (HTTP не идёт под внешней
  транзакцией).

| Ответ подписчика | Итог |
|---|---|
| 2xx | `delivered` |
| 400, 404, 410, 413, 415, 422 | сразу `dead` (DLQ); «повторить» доступно |
| 401, 408, 409, 429, 5xx, сеть, таймаут, дедлайн | повтор через 30 с, 2 мин, 10 мин, 1 ч, 6 ч, 24 ч (± 20 %); после неудачи шестого повтора (7-й попытки) — `dead` |
| `Retry-After` у 429/503 | задержка = max(`Retry-After`, шаг расписания), jitter только вверх: попытки не сжигаются |
| нет секрета пары; подписчика нет в файле | отложить на 5 мин, попытка не засчитывается |

**404/410 сразу в `dead`** обычно значат неверный `endpoint` подписчика или не развёрнутый приёмник: так ведут себя сразу все
его доставки.
- Лечение: исправить адрес (`endpoint` или `RT_BUS_ENDPOINT_<ИМЯ>`), затем «повторить все dead» по подписчику.
- Алерт — на рост `dlq_size` (§8).

**Предохранитель** — на каждого подписчика отдельно:
- 5 повторяемых ошибок подряд → пауза 5 мин; остальные подписчики в это время идут;
- после паузы — одна пробная доставка: успех закрывает предохранитель, повторяемая ошибка снова ставит паузу;
- ответ 4xx из таблицы выше счётчик не увеличивает, а на пробе закрывает предохранитель: подписчик жив.

## 6. Приёмник и обработчики

```python
@subscribe("uz.railtech.crm.client.updated.v1")   # маска fnmatch: "uz.railtech.crm.contact.*.v1"
def on_client_updated(event): ...                  # Django: (event); SQLAlchemy: async (event, session); BFF: async (event)
```

Подключение приёмника:
- FastAPI: `app.include_router(bus_router(lambda: container.bus))`;
- Django: `path("bus/v1/events", bus_view(get_bus))`;
- BFF: `bus_router(MemoryReceiver(BusConfig(service="platform-bff")))`.

Порядок обработки запроса:
1. Подпись — любой действующий секрет пары, сравнение constant-time.
2. Окно 300 с.
3. Конверт.
4. `source` = издатель.
5. Запись в inbox (ключ — `event id`; повтор — 200 `duplicate` без обработки).
6. `enqueue(event_id)` после коммита. В Django — через `transaction.on_commit`, то есть и после коммита внешней
   транзакции запроса.

Ответы приёмника:
- 200 — `received`, `duplicate`, `skipped`, `processed`;
- 401 — подпись, неизвестный издатель, вне окна, чужой `source`;
- 400 — не JSON, не конверт;
- 422 — `data` известного типа не по схеме;
- 503 — упал inline-обработчик.

Правила:
- `data` проверяется терпимо (L10): лишние поля (`additionalProperties`) не отказ; неверный тип, нет обязательного поля,
  неверное значение enum — 422.
- Нет обработчика, нет схемы типа, версия выше поддерживаемой (`….v2` при обработчике `….v1`) — запись `skipped`, 200.
- **Обработка:** задача очереди вызывает `bus.process_inbox(event_id)`; обработчики выполняются в одной транзакции со
  статусом записи.
  - Исключение → автоповтор через 30 с, 2 мин, 10 мин (`BusConfig.inbox_retry_delays`, ± 20 %, всего до 4 попыток),
    затем `failed` с текстом ошибки.
  - Повтор задачи по уже обработанной записи или раньше срока ничего не делает.
- `inline=True` — обработчик выполняется в запросе с полным событием. Пример — код акцепта: CRM шлёт его в Telegram, а в
  inbox лежит маска. Ошибка inline-обработчика — откат записи и 503, издатель повторит.

## 7. Периодические задачи

```python
tasks = rt_bus.contrib.celery.install(celery_app, get_bus)    # ERP: pump 5 с, requeue_stuck_inbox 60 с, metrics 300 с, purge сутки
bus.enqueue, bus.wakeup = tasks.enqueue, tasks.wakeup

tasks = rt_bus.contrib.procrastinate.install(app, get_bus, pump_cron="* * * * * */5")   # CRM (6-е поле — секунды)
bus.enqueue = tasks.enqueue
```

- Без очереди: `asyncio.create_task(bus.run_forever(interval=2))` в lifespan.
- Повторы доставки и обработки управляются `next_attempt_at` в таблицах, а не ретраями очереди.
- `requeue_stuck_inbox` ставит в очередь записи, которые очередь не взяла, и автоповторы, у которых настал срок.
  Взятая запись получает отметку времени, поэтому каждый подбор не ставит её в очередь заново.

## 8. Ручное управление, журнал, метрики

| Что | API (в SQLAlchemy — те же методы с `await`) |
|---|---|
| «Повторить» доставку (`dead` или ожидающую) | `retry_delivery(delivery_id)` — попытки с нуля; подписчик на паузе получает пробу сразу |
| «Повторить все dead» | `retry_all_dead(subscriber=None)` |
| Журнал доставок | `list_deliveries(status=, subscriber=, event_type=, event_id=, before_id=, limit=)` → `DeliveryView` |
| «Повторить» запись inbox (`failed`/`skipped`) | `retry_inbox(event_id)` |
| Журнал inbox | `list_inbox(status=, event_type=, before=, limit=)` → `InboxView` |
| Уборка | `purge(older_than=timedelta(days=30))` — удаляет доставленное и обработанное; `dead` и `failed` остаются |

`metrics()` возвращает `BusMetrics`:
- `outbox_pending`, `oldest_undelivered_age_seconds`, `dlq_size`;
- `inbox_received`, `inbox_retrying`, `inbox_failed`;
- по каждому подписчику: `pending`, `in_flight`, `dead`, возраст самого старого, `consecutive_failures`, `paused`.

`log_metrics()` пишет одну строку `rt_bus_metrics …`, все значения — ещё и в `extra`. Алерты: рост `dlq_size` и
`inbox_failed`, `oldest_undelivered_age_seconds` больше часа.

## 9. Корреляция

Цепочка: `X-Request-ID`/`traceparent` запроса → контекст → `correlationid` конверта → `X-Request-ID` доставки → контекст
обработчика → логи.
- Контекст ставит `CorrelationMiddleware` (Django и ASGI) или вызов `rt_bus.set_correlation(...)` из своего middleware.
- В логи корреляцию пишет фильтр `rt_bus.CorrelationFilter` (`%(correlation_id)s`) или процессор structlog
  `rt_bus.structlog_processor`.

## 10. Разработка

```bash
make -C packages/rt-bus install && make -C packages/rt-bus test-unit   # без базы, секунды
make -C packages/rt-bus check                                          # ruff, mypy --strict, миграция Django, все тесты
```

- `make test` берёт `RT_BUS_TEST_DATABASE_URL` (в CI — service-контейнер) или поднимает одноразовый `postgres:17` в Docker
  (имя — `RT_BUS_PG_CONTAINER`, удаляется после прогона).
- Драйверы в тестах: SQLAlchemy — psycopg 3 и asyncpg; Django — psycopg2 (как ERP) и psycopg 3, отдельными процессами
  pytest.
- HTTP — `httpx.MockTransport`/`ASGITransport`, без сети.
- Схемы и подписки — из `packages/contracts` этого репозитория (другой каталог — `RT_BUS_TEST_CONTRACTS_DIR`).
