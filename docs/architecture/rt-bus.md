# rt_bus — шина событий v1: API и подключение

Библиотека [`packages/rt-bus`](../../packages/rt-bus/) (дистрибутив `rt-bus`, импорт `rt_bus`, Python 3.12) — единственный
способ, которым сервис публикует события своих сущностей и получает чужие. Основание: [ADR-0014](../adr/0014-integration-bus-rt-bus.md),
правило «интеграции только через шину» (ORCHESTRATOR §3 п. 14). Нормативка: CONTRACTS §9 «Шина rt_bus», [runbook волны 11](../runbooks/wave11-bus-v1.md) §2,
решения лида L1–L21 (§11). Транспорт v1 — PostgreSQL outbox сервиса, ретранслятор и подписанный HTTP к подписчикам. Бизнес-код
транспорт не видит (v2 — NATS JetStream, этап F).

```text
издатель:  изменение + publish() в одной транзакции → rt_bus_outbox
           pump(): relay — outbox → rt_bus_delivery (строка на подписчика, SKIP LOCKED)
                   deliver — аренда пачки → по подписчикам независимо: POST <подписчик>/bus/v1/events (HMAC v2)
                             → delivered | повтор | dead
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

**Пробуждение ретранслятора (B5a).** Транзакция с `publish` после коммита сразу ставит задачу `pump` — доставка начинается
за доли секунды, а не на ближайшем тике (5 с). Периодический `pump` остаётся страховкой: он же подбирает события, если
пробуждение потерялось.
- Подключение: `bus.wakeup = tasks.wakeup` (ERP — `integration/bus.py`, CRM и EDS — `Container.bus`, `wakeup=tasks.wakeup`).
  Без `wakeup` `pump` идёт только по расписанию.
- **Откат — пробуждения нет.** Задача ставится только после настоящего коммита: `publish` из откатанной транзакции или
  откатанной точки сохранения будить не может.
- **Один раз на транзакцию.** Сколько бы `publish` ни было в транзакции (в том числе во вложенных блоках), пробуждение одно.
  - Django: `transaction.on_commit` — после коммита внешней транзакции; повтор определяется по очереди `run_on_commit`.
  - SQLAlchemy: слушатели сессии `after_commit`, `after_soft_rollback` и `after_transaction_end` (ставятся при первом
    `publish` сессии), метка стоит на транзакции или точке сохранения, где был `publish`. `RELEASE SAVEPOINT` не будит —
    метка переходит на родителя, будит коммит внешней транзакции; откат точки сохранения снимает её метки.
  - Пробуждения разных транзакций сливает очередь, но только между собой: Procrastinate — `queueing_lock`
    `rt_bus.pump.wakeup` (ожидающее пробуждение ещё не начало раскладку и заберёт новое событие, повторное — `AlreadyEnqueued`,
    это норма); Celery — каждая транзакция ставит свою задачу, лишний `pump` безвреден (`FOR UPDATE SKIP LOCKED`).
  - **С периодическим проходом пробуждение не сливается** (W11B-G-6): у периодического `pump` свой ключ `rt_bus.pump`. Иначе
    пробуждение ждало бы запуска уже стоящей в очереди периодической задачи (на стенде гейта B — 4,8 с вместо долей секунды).
    Два `pump` одновременно безопасны: доставки берутся `FOR UPDATE SKIP LOCKED`, итоги пишутся по подписчикам в порядке имён
    (§5).
- **Недоступная очередь не ломает изменение.** Ошибка постановки — запись `rt_bus_wakeup_failed` в лог; коммит и событие на
  месте, событие уйдёт периодическим `pump`. Django: Celery повторяет подключение один раз с паузой 0,2 с;
  время подключения ограничено настройкой транспорта брокера сервиса — ERP: `CELERY_BROKER_TRANSPORT_OPTIONS` с
  `socket_connect_timeout` 1 с (`core/settings/infra.py`); без неё недоступный адрес держал бы коммитящий запрос до
  таймаута ОС (~75 с). SQLAlchemy: пробуждение — фоновая задача asyncio, коммит ответа не ждёт;
  `AsyncBus.drain_wakeups()` (и `aclose()`) дожидается незавершённых. Сервис вызывает его, пока очередь ещё открыта (CRM: `Container.drain_bus()` в
  lifespan API и бота, в воркере и в `create_admin`; EDS — в lifespan API, воркере и `python -m app bus`), иначе отложенное пробуждение упрётся в закрытый пул очереди.
- Очередь: пробуждение идёт туда же, куда пишет Beat. ERP — `CELERY_TASK_DEFAULT_QUEUE = "default"`, её обслуживает
  `erp-worker` (`-Q default,pdf,imports`); тест `integration/tests/test_bus_wakeup.py` ловит уход в очередь без воркера.
  CRM — очередь `rt_bus`, воркер `python -m app worker` берёт все очереди.
- **Воркер Procrastinate опрашивает очередь раз в секунду** (`run_worker_async(**WORKER_OPTIONS)`, `fetch_job_polling_interval`
  = 1 с вместо 5 с по умолчанию; CRM — `app/__main__.py`). Новую задачу воркер узнаёт по NOTIFY, а флаг NOTIFY сбрасывается
  после каждой выборки: уведомление, пришедшее во время выборки, теряется, и задача ждёт опроса. На стенде гейта B периодическая
  задача стартовала ровно через 5,0 с после постановки — предел опроса. С опросом в 1 с «хвост» пробуждения не больше секунды.
  Стоимость — один лёгкий запрос в секунду на воркер. Воркер EDS (`apps/eds/app/__main__.py`) пока опрашивает с настройкой по
  умолчанию (5 с) — подключить `**WORKER_OPTIONS` в задаче зоны EDS.

## 5. Подписки и доставка

Файл `bus/subscriptions.yaml` (L5):
- издатель доставляет подписчику только свои события (`source == rt://<service>`) и себе не доставляет;
- файл перечитывается по mtime, без перезапуска: **новый подписчик — это строка в файле + секрет пары**;
- **`enabled: false` останавливает отправку, но не теряет события** (решение архитектора 2026-10-26, W11B-G-2; L16):
  - раскладка по-прежнему создаёт строки доставки в `pending` — и для событий, опубликованных за время остановки;
  - ретранслятор выключенному подписчику ничего не отправляет: ни попыток, ни проб, предохранитель его не трогает;
  - после `enabled: true` накопленное уходит пачками (`delivery_batch`) в порядке выбора — по сроку и номеру доставки, то есть
    примерно по времени создания событий; внутри пачки запросы идут параллельно, и порядок получения у подписчика не
    гарантирован (подписчики применяют снимки по `updated_at`). Это про события, разложенные за время остановки: они готовы сразу
    и расписания повторов не ждут. Доставки, которые к моменту остановки уже ждали повтора после ошибки, идут по своему сроку;
  - ждущие доставки видны в журнале; «Повторить» (`retry_delivery`) на них ничего не отправляет, пока подписчик выключен.
- **`drop: true`** (необязательно, по умолчанию `false`; действует только при `enabled: false`): прошлое подписчику не нужно
  (заглушка, стенд) — строки доставки для событий за время остановки **не создаются**. Уже разложенные `pending` остаются и уходят
  после включения. При `enabled: true` поле `drop` не действует: новые события раскладываются как обычно. Схема —
  `packages/contracts/bus/subscriptions.schema.json`.

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
- **Подписчики независимы** (W11C-G-1; L21): взятая пачка (`delivery_batch`, вперемешку по подписчикам) разбирается на группы
  по подписчику. Запросы группы идут параллельно, итог группы пишется, как только ответили её запросы, — не дожидаясь чужих.
  Медленный, но живой подписчик (200 через секунды) задерживает только себя. `pump` не ждёт его между пачками: пока запросы
  в пути, он каждые `inflight_poll` (0,25 с) раскладывает новое и набирает следующую пачку — кроме подписчиков, у которых в
  пути уже `subscriber_concurrency` (20) запросов: им пачку не набирают, пока они не ответят, так что очередь медленного
  подписчика не занимает пачки быстрых. В конце (нет работы или вышло `max_seconds`) `pump` дожидается запросов в пути —
  дедлайном попытки.
  Пул соединений httpx общим потолком не ограничен (`delivery_limits()`): с потолком в 100 соединений ответы медленного
  подписчика занимали пул целиком, и запрос быстрого ждал свободного соединения — конца чужого ответа (замер W13-A0: 3,6 с
  до `platform-bff`). Вместо общего потолка — **предел на подписчика в процессе**: семафор `subscriber_connections` =
  `subscriber_concurrency + delivery_batch` (29), общий для всех одновременных проходов (SQLAlchemy — `asyncio.Semaphore`,
  Django — `threading.BoundedSemaphore` в потоках пула). Медленный подписчик не может занять сокеты другого, а сокетов
  в процессе не больше «подписчики × предел». Ожидание места входит в дедлайн попытки (`attempt_deadline`): подписчик,
  который не успевает за потоком, получает «повтор», как и при зависшем ответе.
  Исключение — ERP: клиент доставки строится в `apps/erp/backend/integration/bus_http.py` со своим `SecretMaskingTransport` над
  `httpx.HTTPTransport()`, и лимиты `delivery_limits()` на него не действуют — у ERP остаётся потолок httpx по умолчанию
  (100 соединений на процесс). Предел на подписчика (29) при этом работает и там, поэтому общий потолок срабатывает лишь
  при трёх и более одновременно медленных подписчиках; снять его — отдельная правка `bus_http.py` (хвост).
- **Дедлайн попытки** (`attempt_deadline`, 25 с; таймаут httpx `http_timeout`, 10 с — на каждую операцию отдельно):
  медленный ответ не держит ни пачку, ни аренду. Итог по дедлайну — повтор с ошибкой `DeadlineExceeded`.
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
- **проба идёт по сроку паузы, а не по сроку повтора доставки** (C1-G-6): берётся готовая доставка подписчика, а если готовых
  нет (тихий период, срок повторов далеко) — ближайшая по расписанию. Так восстановление подписчика не ждёт расписания повторов
  (после простоя в 10 минут — до ~10 минут). Неудача такой «ранней» пробы продлевает паузу, но срок и число попыток самой
  доставки не меняет: проба не сжигает попытки (на счётчик предохранителя ошибка идёт);
- ответ 4xx из таблицы выше счётчик не увеличивает, а на пробе закрывает предохранитель: подписчик жив.

**Догон после восстановления** (C1-G-6; L18): первая успешная доставка (в том числе ранняя проба) подписчика, у которого было не меньше `threshold` ошибок
подряд (предохранитель закрылся), сбрасывает `next_attempt_at` всех его ожидающих повторов к «сейчас» (счётчик попыток не
меняется), а `pump` берёт следующую пачку сразу, не дожидаясь тика. Накопленное уходит обычными пачками по `delivery_batch`,
не одним залпом, и не по расписанию 30 с … 24 ч. Ошибки ниже порога (одиночное «ядовитое» событие) расписание чужих повторов не
сбрасывают: здоровый трафик не выжигает попытки больному событию.

**Запись итогов** (W11B-G-1, W11C-G-1; L19, L21): итоги пишутся по подписчикам — группа на подписчика, короткая транзакция по
мере завершения запросов группы (внутри группы — по `id` доставки). Транзакция группы касается только строк её подписчика
(доставки и `rt_bus_subscriber_state`), поэтому группы разных подписчиков, в каком бы порядке они ни завершились и ни
писались (SQLAlchemy — по одной на `pump` под замком, пул соединений ограничен; Django — основным потоком), не блокируют
друг друга взаимно, как и параллельные `pump` (периодический и пробуждение). Взаимная блокировка или сбой сериализации
(SQLSTATE `40P01`, `40001`) — группа повторяется (до 4 раз, пауза от 50 мс); иная ошибка одной группы не мешает записи остальных:
чужие подписчики не ждут аренды (60 с); `pump` дописывает уже летящие запросы, ошибка поднимается в конце.

**Два адаптера — одна семантика.** SQLAlchemy (CRM, EDS): задача `asyncio` на подписчика, запросы `httpx.AsyncClient`. Django
(ERP): запросы уходят в пул потоков (только HTTP, без БД), основной поток набирает пачки и пишет итоги готовых групп —
соединение Django остаётся одно. Зависший ответ в Django доходит до таймаута `httpx` в фоне, его итог уже не пишется. Отмена
`pump` (остановка воркера) прерывает запросы: аренда истечёт, доставки уйдут следующему проходу. Сервис может переопределить
`before_deliver()` — вызывается перед каждым набором пачки (CRM обновляет секреты вебхуков).

## 6. Приёмник и обработчики

```python
@subscribe("uz.railtech.crm.client.updated.v1")   # маска fnmatch: "uz.railtech.crm.contact.*.v1"
def on_client_updated(event): ...                  # Django: (event); SQLAlchemy: async (event, session); BFF: async (event)
```

Подключение приёмника:
- FastAPI: `app.include_router(bus_router(lambda: container.bus))`;
- Django: `path("bus/v1/events", bus_view(get_bus))`;
- BFF (B5): `bus_router(MemoryReceiver(BusConfig(service="platform-bff"), registry=…))` — `apps/platform/bff/app/bus.py`: обработчик
  публикует подсказку в Redis, процессы BFF раздают её открытым SSE-соединениям (`docs/architecture/platform-bff.md` §5).

Порядок обработки запроса:
1. Подпись — любой действующий секрет пары, сравнение constant-time.
2. Окно 300 с.
3. Конверт.
4. `source` = издатель.
5. Домен типа принадлежит издателю (L17): тип `uz.railtech.<домен>.…` вправе публиковать только издатель этого домена.
6. Запись в inbox (ключ — `event id`; повтор — 200 `duplicate` без обработки).
7. `enqueue(event_id)` после коммита. В Django — через `transaction.on_commit`, то есть и после коммита внешней
   транзакции запроса.

Ответы приёмника:
- 200 — `received`, `duplicate`, `skipped`, `processed`;
- 401 — подпись, неизвестный издатель, вне окна, чужой `source`;
- 400 — не JSON, не конверт, домен типа не принадлежит издателю (`foreign_type`);
- 422 — `data` известного типа не по схеме;
- 503 — упал inline-обработчик.

Принадлежность домена (L17) — данные, а не код: `BusConfig.publisher_domains` (по умолчанию `rt_bus.receiver.DEFAULT_PUBLISHER_DOMAINS`):

| Издатель | Домены типа |
|---|---|
| `crm` | `crm`, `identity` (сотрудник — `source` `rt://crm`, ADR-0015) |
| `erp` | `erp` |
| `eds` | `eds` |
| `platform-bff` | `platform` |

Издателя нет в таблице — ему принадлежит только домен с его именем; новому издателю (`connector-<имя>`) домен задаёт
`publisher_domains`. **Почему 400, а не 401**: событие с верной подписью пары и верным `source`, но чужим доменом — нарушение
контракта издателем, повтор его не вылечит. По таблице отправителя (§5) 400 — сразу `dead` и не растит счётчик предохранителя; 401 —
повтор 30 с … 24 ч и ошибки подряд, которые остановили бы здоровый трафик пары. Причина в журнале приёмника
(`rt_bus_receive_rejected`), в ответе только `{"error": "foreign_type"}`.

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
bus.enqueue, bus.wakeup = tasks.enqueue, tasks.wakeup
```
- `wakeup` — пробуждение по коммиту (§4): тот же `pump`, поставленный вне расписания, со своим ключом очереди
  (Procrastinate: `rt_bus.pump.wakeup`) — с периодическим проходом не сливается.
- Воркер Procrastinate: `run_worker_async(..., **rt_bus.contrib.procrastinate.WORKER_OPTIONS)` — опрос очереди раз в секунду (§4).

- Без очереди: `asyncio.create_task(bus.run_forever(interval=2))` в lifespan.
- Повторы доставки и обработки управляются `next_attempt_at` в таблицах, а не ретраями очереди.
- `requeue_stuck_inbox` ставит в очередь записи, которые очередь не взяла, и автоповторы, у которых настал срок.
  Взятая запись получает отметку времени, поэтому каждый подбор не ставит её в очередь заново.

## 8. Ручное управление, журнал, метрики

| Что | API (в SQLAlchemy — те же методы с `await`) |
|---|---|
| «Повторить» доставку (`dead` или ожидающую) | `retry_delivery(delivery_id, actor=)` — попытки с нуля; подписчик на паузе получает пробу сразу |
| «Повторить все dead» | `retry_all_dead(subscriber=None, actor=)` |
| Журнал доставок | `list_deliveries(status=, subscriber=, event_type=, event_id=, type_contains=, created_from=, created_to=, before_id=, limit=)` → `DeliveryView`, новые сверху |
| «Повторить» запись inbox (`failed`/`skipped`) | `retry_inbox(event_id, actor=)` |
| Журнал inbox | `list_inbox(status=, event_type=, type_contains=, errors_only=, before=, before_event_id=, limit=)` → `InboxView` |
| Подписчики издателя | `subscribers()` → `SubscriberView`; `overview()` → `BusOverview` (метрики + подписчики) |
| Уборка | `purge(older_than=timedelta(days=30))` — удаляет доставленное и обработанное; `dead` и `failed` остаются |

- `actor` — кто нажал (`crm-user:7`, `erp-user:12`): пишется в записи лога `rt_bus_delivery_retry_manual`,
  `rt_bus_dead_retry_manual`, `rt_bus_inbox_retry_manual`. Журнал «кто и когда» в базе ведёт сервис (см. «Журнал в Admin»).
- `errors_only` — записи `failed` и ждущие автоповтора после ошибки обработчика (`received` с `error`).
- Страница inbox — курсор (`before`, `before_event_id`) последней строки: порядок `received_at DESC, event_id`, строки с
  одинаковым временем не теряются между страницами. Страница доставок — `before_id`.
- `SubscriberView` — подписчики, которым издатель доставляет (маска типа на его домен, себе — нет), и все, у кого остались
  доставки или состояние: `configured` (есть в файле подписок), `enabled`, `drop`, `endpoint` (без учётных данных URL),
  `pending`, `in_flight`, `dead`, возраст самого старого недоставленного (без `dead`), `consecutive_failures`, `paused_until`
  (только действующая пауза), последние успех, ошибка и её текст.

`metrics()` возвращает `BusMetrics`:
- `outbox_pending`, `oldest_undelivered_age_seconds`, `dlq_size`;
- `inbox_received`, `inbox_retrying`, `inbox_failed`;
- по каждому подписчику: `pending`, `in_flight`, `dead`, возраст самого старого, `consecutive_failures`, `paused`, `enabled`.

`log_metrics()` пишет одну строку `rt_bus_metrics …` (в конце — `paused=` и `disabled=`), все значения — ещё и в `extra`.
Алерты: рост `dlq_size` и `inbox_failed`, `oldest_undelivered_age_seconds` больше часа.

**Выключенный подписчик и возраст.** Доставки у подписчика с `enabled: false` копятся намеренно (§5), поэтому они **не входят**
в общий `oldest_undelivered_age_seconds` — алерт «старше часа» не срабатывает на остановку на время работ. Сами ожидающие
видны отдельно: у подписчика `enabled: false`, `pending` и собственный `oldest_undelivered_age_seconds`. Забытая остановка —
не авария шины, а операторская: ищите `disabled=` в строке `rt_bus_metrics` и `enabled: false` в метриках подписчика.

### Журнал в Admin

С волны 13 (W13-A2) оператору не нужны CLI `bus status|dead|failed|retry|retry-dead|retry-inbox` (CRM, EDS),
`manage.py bus_retry` и Django admin ERP «rt_bus → Delivery/Inbox/Subscriber state»: то же делает экран **Admin · Журнал
интеграций** Платформы (`/admin/bus`). CLI и админка остаются запасным путём (Платформа или BFF недоступны).

| Что на экране | Заменяет | API домена (общий код этого раздела) | BFF (`platform-bff.yaml` 0.9.0) |
|---|---|---|---|
| Подписчики по доменам: состояние словом, пауза предохранителя до …, ждут, DLQ, возраст, последняя ошибка | `bus status`, `bus_retry --metrics`, «Subscriber state» | `GET …/bus/overview` | `GET /admin/bus` |
| Доставки с фильтрами (домен, статус, подписчик, подстрока типа, период) и «Показать ещё» | `bus dead`, `bus_retry --list`, «Delivery» | `GET …/bus/deliveries` | `GET /admin/bus/deliveries` |
| Недоставленные (DLQ) | `bus dead` | то же, `status=dead` | то же, `status=dead` |
| «Повторить» доставку | `bus retry <id>`, `bus_retry --delivery` | `POST …/bus/deliveries/{id}/retry` | `POST /admin/bus/{domain}/deliveries/{id}/retry` |
| «Повторить все dead подписчика» с блоком «Что произойдёт» | `bus retry-dead --subscriber`, `bus_retry --all-dead` | `POST …/bus/deliveries/retry-dead` `{subscriber}` | `POST /admin/bus/{domain}/deliveries/retry-dead` |
| Входящие с ошибками и «Повторить обработку» | `bus failed`, `bus retry-inbox`, `bus_retry --inbox`, «Inbox» | `GET …/bus/inbox?errors=true`, `POST …/bus/inbox/{event_id}/retry` | `GET /admin/bus/inbox`, `POST /admin/bus/{domain}/inbox/{event_id}/retry` |

- **Пути доменов:** CRM и EDS — `/api/v1/bus/*` (`crm.yaml`, `eds.yaml` тег `bus`), ERP — `/api/v1/integration/bus/*/`
  (`erp-internal.yaml`). Поля ответов одинаковые у всех трёх; страницы — явный keyset (`before_id`; `before` +
  `before_event_id`) и `has_more`, чтобы BFF мог слить три домена в один журнал по времени со своим составным курсором.
- **Права** — раздел `admin` каталога уровня `full`: CRM — `integrations:read` (чтение) и `integrations:write` (повторы);
  ERP — `team.manage` (код раздела `admin` в ERP) или администратор ERP; EDS — код `bus.manage` (с eds.yaml 0.3.0, только
  `admin: full`). BFF пускает только `admin: full` (директору — 403), в каждый домен идёт с токеном сотрудника; в EDS —
  токеном доступа EDS, полученным обменом SSO-токена CRM `aud=eds` (`docs/architecture/sso-token.md`).
- **Частичный ответ:** домен, который не ответил или отказал, — в `sources` (`unavailable`, `forbidden`, `not_applicable`),
  остальные показываются; экран пишет это плашкой словами.
- **Повтор идемпотентен:** повторять нечего (доставлено, в работе, записи нет) — `retried: 0`. Каждое нажатие пишется в журнал
  домена с автором и временем: CRM — журнал аудита (`bus.delivery_retried`, `bus.dead_retried`, `bus.inbox_retried`), ERP —
  «Журнал доступа» (`admin.bus.*`), EDS — журнал EDS (`bus.*`); и в лог шины (`actor`).
- **Тел событий в журнале нет** — только метаданные доставки: тип, id события, объект (`subject`), корреляция, издатель,
  подписчик, статус, попытки, код и текст ошибки, время. Тело может содержать персональные данные клиентов; для разбора
  достаточно id события и корреляции (по ним — логи, `docs/runbooks/request-id.md`). Текст ошибки приходит от подписчика и
  обрезается библиотекой (до 500 символов).

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
- Конкурентные тесты «медленный подписчик» (`tests/sa/test_wave13.py`, `tests/dj/test_wave13.py`) идут на реальном времени (ответ
  2,5 с). Замер на стенде compose — `docs/screens/w13-a0-bus/logs/measure.sh` (заглушка `slow_stub.py`, таблица
  `latency_table.py`); подробности и цифры — в `docs/screens/w13-a0-bus/logs/`.

## 11. Решения волн 11, 11c и 13 (L1–L21)

Решения лида волны 11 (2026-10-22…23) по runbook §2 и ответам архитектора; источник правды — этот раздел и CONTRACTS §9.

| № | Решение |
|---|---|
| L1 | Конверт CloudEvents 1.0, structured mode. Обязательны `specversion`, `id` (UUID), `source` (`rt://crm\|erp\|eds\|platform-bff`), `type`, `time` (UTC), `datacontenttype`, `dataschema` (`rt://contracts/events/<домен>/<сущность>.<действие>/v<N>`), `tenant` (`railtech`), `correlationid`, `data`; необязательны `subject`, `traceparent`. Отправитель строгий, читатель терпимый (доп. атрибуты-расширения допустимы). |
| L2 | Тип `uz.railtech.<домен>.<сущность>.<действие>.v<N>` ↔ `packages/contracts/events/<домен>/<сущность>.<действие>.v<N>.json`; сущность и действие — один сегмент snake_case. Домены `crm`, `erp`, `eds`, `identity`, `platform`; сотрудник — `identity` с `source` `rt://crm` (ADR-0015). |
| L3 | Доставка: `POST <подписчик>/bus/v1/events`, `application/cloudevents+json`, заголовки `X-RT-Publisher`, `X-RT-Event-Id`, `X-RT-Timestamp` (момент попытки), `X-RT-Signature: sha256=HMAC(secret, "{id}.{ts}.{body}")`, окно 300 с. Ответы: 2xx (в т. ч. повтор и skipped), 401, 400, 422. Неповторяемые у отправителя — 400, 404, 410, 413, 415, 422 (сразу dead); прочее — повтор 30 с, 2 мин, 10 мин, 1 ч, 6 ч, 24 ч с jitter ±20 %, затем dead (7 попыток). |
| L4 | Секрет пары `RT_BUS_SECRET_<ИЗДАТЕЛЬ>_<ПОДПИСЧИК>` (список через запятую: первым подписывают, принимают любой) или поставщик секретов сервиса. |
| L5 | `packages/contracts/bus/subscriptions.yaml`: `{version: 1, subscribers: [{name, endpoint, endpoint_env?, enabled?, types: [маски fnmatch]}]}`; издатель доставляет только свои события и не себе; новый подписчик — строка в файле и секрет в окружении. |
| L6 | Один генератор моделей — datamodel-code-generator → Pydantic v2, пакет `rt-contracts` в `packages/contracts/generated/python/`; `rt-bus` от него не зависит и проверяет `data` по JSON Schema каталога контрактов. |
| L7 | Старые `events.schema.json` и `examples/events/` удаляют последние потребители (B3 — ERP и infra, B4 — CRM и сами файлы). |
| L8 | В пределах vN — только новые необязательные поля и новые типы; всё прочее, включая расширение enum и снятие required, — v(N+1) с двойной публикацией (`events_compat.py` в `make contracts`). |
| L9 | Таблицы `rt_bus_outbox`, `rt_bus_delivery`, `rt_bus_inbox`, `rt_bus_subscriber_state` — одна схема в SQLAlchemy и Django. |
| L10 | Схемы `data` строгие для отправителя; приёмник прощает только `additionalProperties` (новое необязательное поле не даёт 422). |
| L11 | Пути контракта: см. CONTRACTS §9; события CRM/identity — снимки с `updated_at`, более старый снимок не применяется; `contact.deleted` несёт `deleted_at`. |
| L12 | Секрет пары CRM ↔ ERP: окружение, иначе `hex(HMAC-SHA256(webhook_secret, "rt-bus/v1/{издатель}->{подписчик}"))` от каждого действующего секрета сопряжения (ERP хранит и прежний на время ротации). Прочие подписчики — только окружение. |
| L13 | Одна сессия — одна система: ERP-часть шины (публикация, приёмник, проекции событий CRM) — B3, CRM-часть — B4. |
| L14 | Пакеты в образах — compose `additional_contexts` (`rtbus`, `contracts`) и `COPY --from`, то же в `deploy.yml`; контракты в образе — `/opt/rt/contracts`. |
| L15 | Документация шины — только в `docs/`: этот файл, CONTRACTS §9, runbook'и `docs/runbooks/rt-bus-*.md`. |

Решения волны 11c (F1, 2026-10-26; основание — [отчёт гейта B](../runbooks/wave11b_gate_b_report.md) §4, [отчёт гейта C1](../runbooks/c1_eds_gate_report.md) §4, [runbook волны](../runbooks/wave11c-bus-fixes.md)):

| № | Решение |
|---|---|
| L16 | `enabled: false` не теряет события: раскладка создаёт доставки в `pending`, ретранслятор их не отправляет, после `enabled: true` они уходят пачками в порядке выбора. `drop: true` (только при `enabled: false`, по умолчанию `false`) — события за время остановки не копятся. Ожидающие выключенного подписчика не входят в общий `oldest_undelivered_age_seconds`; у подписчика в метриках `enabled`. Решение архитектора (W11B-G-2). |
| L17 | Приёмник отклоняет событие, чей домен типа не принадлежит издателю пары: 400 `foreign_type` (повтор не поможет; предохранитель не растёт). Таблица домен ↔ издатель — данные (`BusConfig.publisher_domains`). |
| L18 | Проба предохранителя идёт по сроку паузы, а не по сроку повтора доставки (неудача ранней пробы срок и попытки доставки не меняет). Первая успешная доставка подписчика с открывавшимся предохранителем (≥ `threshold` ошибок подряд) сбрасывает его ожидающие повторы к «сейчас», `pump` берёт следующую пачку сразу (C1-G-6). Одиночные ошибки расписание не сбрасывают. |
| L19 | Итоги пачки пишутся по подписчикам в порядке имён, короткой транзакцией на подписчика; `40P01`/`40001` — повтор группы; ошибка одной группы не держит аренду чужих (W11B-G-1). |
| L20 | Пробуждение Procrastinate — свой `queueing_lock` `rt_bus.pump.wakeup`, с периодическим `pump` не сливается; воркер опрашивает очередь раз в секунду (`WORKER_OPTIONS`) (W11B-G-6). |

Решения волны 13 (A0, 2026-10-26; основание — [отчёт гейта 11c](../runbooks/wave11c_gate_report.md) §4 W11C-G-1):

| № | Решение |
|---|---|
| L21 | Отправка и запись итога доставки независимы по подписчику: пачка делится на группы подписчиков, у каждой своя задача (SQLAlchemy) или группа запросов в пуле потоков (Django), итог пишется по мере завершения; `pump` не ждёт медленных, пока набирает пачки для остальных, и ограничивает число запросов в пути на подписчика (`BusConfig.subscriber_concurrency`, 20; `inflight_poll`, 0,25 с). Выбрано это, а не «запись по завершению каждого запроса» (лишние транзакции, тот же эффект) и не «отдельный воркер на подписчика» (процессы, настройка на каждого, новый подписчик = строка в файле, а не деплой). `deliver()` — один проход, кончается, когда закончили все группы. Расписание повторов, предохранитель, пробы, аренда, `enabled: false`, идемпотентность, `foreign_type` — без изменений (L3, L16–L19). |

Решения архитектора 2026-10-23 к волне: ИНН и реквизиты клиента — поле CRM, ERP применяет их в проекцию и не даёт править
(`REQUISITES_MANAGED_BY_CRM`); `contact.deleted` в ERP — архивирование; стирание лида — `uz.railtech.crm.lead.erased.v1` (только
идентификаторы); `lead.stage_changed.reason` — только код из справочника CRM; WARN oasdiff сборку не валит, ERR валит; до 1.0
ломающее в OpenAPI — с повышением минорной (B6b).
