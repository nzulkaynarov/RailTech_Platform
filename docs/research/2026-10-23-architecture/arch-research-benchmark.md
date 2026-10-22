# Интеграционная архитектура бизнес-платформ: эталоны и что брать RailTech Platform

Дата: 2026-10-22. Автор: исследователь-архитектор (веб-ресёрч). Репозиторий не менялся.

**Условные обозначения.**
- **[Ф]** — факт, подтверждённый источником из списка «Источники» в конце раздела.
- **[П]** — предположение, оценка или вывод автора; перед решением проверить.
- «Ядро» — CRM, EDS и ERP с их базами; «интеграция» — всё, что ходит во внешние системы (1С, SAP, ЭСФ/ЭДО, банк, таможня).

**Короткий ответ.** Все зрелые платформы устроены одинаково: транзакционное ядро с собственной моделью данных,
опубликованный и версионируемый слой API и событий, асинхронная доставка с журналом и повтором, и коннекторы
за пределами ядра — в отдельном движке или «приложении». Для RailTech на одном VPS с CPU x86-64 v1 шину
первой версии стоит строить на PostgreSQL (outbox и inbox плюс очередь на каждый коннектор). Её нужно спрятать
за собственным интерфейсом, чтобы потом без переписывания перейти на NATS JetStream. Kafka, Redpanda,
ClickHouse и интеграционные движки на JVM в ближайшие версии не нужны, а часть из них на этом CPU не запустится.

---

## 1. Как устроены интеграционные архитектуры зрелых платформ

### 1.1. Платформа за платформой

| Платформа | Синхронный API | События (исходящие) | Где живут интеграции | Версионирование |
|---|---|---|---|---|
| Salesforce | REST/SOAP/Bulk, Pub/Sub API (gRPC) | Platform Events (свои события), Change Data Capture (изменения записей); у событий есть replay ID, хранение 72 ч [Ф] | MuleSoft Anypoint вне ядра; API-led: system / process / experience [Ф] | Номер версии API в пути; поддержка версии ≥3 лет, уведомление ≥1 год до снятия, после снятия — 410 Gone [Ф] |
| SAP S/4HANA + BTP | OData, SOAP | SAP Event Mesh / Advanced Event Mesh (брокер на BTP) [Ф] | Integration Suite (iPaaS) и side-by-side расширения на BTP. Принцип Clean Core: ядро не модифицируют, расширяют снаружи через API и события [Ф] | Опубликованные «released» API; классические модификации ядра считаются «не clean» [Ф] |
| Microsoft Dynamics 365 / Dataverse | Web API (OData) | Business events → Azure Service Bus, Event Hub, вебхуки, Power Automate [Ф] | Плагин ставит асинхронное системное задание, Service Bus доставляет слушателю (Function, Logic App). Встроены очередь и повтор; у вебхука повтор пишет разработчик [Ф] | Версии Web API; dual-write синхронизирует F&O и Dataverse почти в реальном времени [П: детали не проверял] |
| Odoo | XML-RPC/JSON-RPC (в 19.0 устарели) → External JSON-2 API (`/json/2/<model>/<method>`, bearer-ключ) [Ф] | Своих событий в ядре нет; используют модули | OCA `queue_job`: отложенные вызовы в отдельной транзакции, каналы с лимитом параллельности, повтор по исключению, сбой одной задачи не блокирует остальные [Ф]; OCA connector framework | Снятие старого RPC запланировано на Odoo 22 (осень 2028) [Ф] — пример длинного окна устаревания |
| ERPNext / Frappe | REST по каждому DocType автоматически [Ф] | Webhook DocType на doc_events (прямой SQL вебхук не вызывает) [Ф] | Фоновые задачи (RQ) с повтором и логом. Event Streaming сайт-сайт **не поддерживается с v15**, репозиторий архивирован в декабре 2024 [Ф] | По мажорным версиям фреймворка |
| 1С:Предприятие | OData (стандартный интерфейс), HTTP-сервисы | Планы обмена, регистрация изменений | Формат EnterpriseData (XML, бизнес-сущности, XSD, поддержка версии ≥1 год после выхода новой major) [Ф]; «Конвертация данных»; **1С:Шина** — ESB с гарантированной доставкой (хранит сообщение до подтверждения), маршрутизацией по содержимому, визуальными каналами; брокер внутри (Artemis) скрыт от клиента [Ф] | Версия формата EnterpriseData в заголовке сообщения [Ф] |
| Bitrix24 | REST (методы по модулям) | Исходящие вебхуки и `event.bind` из приложения; обработчик должен быть доступен из интернета [Ф] | Локальные вебхуки (внутренние интеграции) против приложений Маркетплейса (тиражируемые, с правами и встраиванием) [Ф] | Без явной схемы версий REST [П] |
| Zoho | REST по продуктам | Webhook-триггеры | Zoho Flow — iPaaS «триггер → действия» с фильтрами, задержками, путями ошибок и custom functions [Ф] | — |
| HubSpot | REST, с 2026 версии по дате (`/crm/2026-03/`, `/crm/2026-09/`), мажорные релизы в марте и сентябре, поддержка 18 мес. [Ф] | Вебхуки: до 10 повторов за 24 ч со случайным разбросом; повтор при обрыве, ответе >5 с, 4xx/5xx; подпись v3 (HMAC SHA-256 + метка времени, окно 5 мин) [Ф] | App Marketplace (приложения с OAuth и скоупами); Operations Hub data sync [П: не проверял детально] | Date-based versioning |

### 1.2. Что общего: слои, граница ядра, изоляция, версии

**Слои.** У всех [П, обобщение по таблице выше] одна и та же схема:

```
 Experience  ─ UI, портал, мобильные, BFF          (MuleSoft: experience APIs)
 Process     ─ сквозные процессы и оркестрация     (MuleSoft: process APIs; SAP BTP; Power Automate; Zoho Flow)
 System      ─ коннектор к одной системе-источнику (MuleSoft: system APIs; адаптеры Integration Suite)
 ── опубликованный контракт: API + события ──
 Core        ─ транзакционное ядро и его БД         (S/4HANA, Dataverse, Odoo ORM, Frappe DocType)
```

**Граница ядра.**
- Ядро публикует **стабильный опубликованный интерфейс**: released API у SAP, Web API и business events у
  Dataverse, Platform Events и CDC у Salesforce, EnterpriseData у 1С. Всё прочее — его внутреннее дело [Ф].
- SAP прямо формулирует это как Clean Core: не модифицировать ядро, расширения выносить side-by-side
  и подключать через API и события [Ф].
- Ни одна платформа не даёт внешней системе писать в свои таблицы. Frappe отдельно оговаривает, что прямой SQL
  не порождает событий [Ф] — тот же принцип, что «общих таблиц нет» в RailTech.

**Изоляция интеграций.** Повторяются четыре приёма [Ф по отдельным платформам, П как обобщение]:
1. **Асинхронная отправка из ядра.** У Dataverse плагин ставит асинхронное системное задание, у Odoo — `queue_job`
   в своей транзакции, у Frappe — фоновые задачи. Ядро не ждёт внешнюю систему.
2. **Брокер или журнал с повтором.** Service Bus, Event Mesh, 1С:Шина хранят сообщение до подтверждения.
   Salesforce хранит события 72 ч и даёт replay.
3. **Отдельная среда исполнения для коннекторов.** MuleSoft, BTP, Zoho Flow, приложения маркетплейсов
   Bitrix24 и HubSpot: упавший коннектор не роняет ядро.
4. **Канал на каждый коннектор с лимитом параллельности.** Каналы у `queue_job` — это bulkhead: медленная
   интеграция не съедает воркеры остальных.

**Версионирование.**
- Встречаются три школы: номер версии в пути (Salesforce `vNN.0`), дата (HubSpot `2026-09`, Stripe)
  и мажор фреймворка (Odoo, Frappe).
- Общее у всех: опубликованная политика поддержки (Salesforce ≥3 года, HubSpot 18 мес., 1С EnterpriseData ≥1 год
  после новой major), заблаговременное уведомление и явная ошибка после снятия (410) [Ф].
- События версионируются схемой: XSD у EnterpriseData, схема Platform Event, версия формата в заголовке [Ф].

**Уроки «от противного».**
- Frappe закрыл Event Streaming сайт-сайт и отправил пользователей к REST, вебхукам и фоновым задачам [Ф].
  Самописная «репликация документов между инстансами» оказалась дорогой в поддержке [П].
- Odoo растянул снятие старого RPC на несколько лет [Ф]. API, на который подписались клиенты,
  убирается годами, поэтому первую версию контракта надо делать аккуратно [П].
- Обзор 1С:Шины прямо называет её избыточной для малых объёмов и редких обменов [Ф]. Тяжёлая ESB
  на старте не нужна.

**Источники к разделу 1**
- Salesforce Platform Events, хранение и replay: https://developer.salesforce.com/docs/platform/pub-sub-api/guide/event-message-durability.html ; https://developer.salesforce.com/docs/atlas.en-us.platform_events.meta/platform_events/platform_events_intro_emp.htm
- Salesforce Change Data Capture: https://developer.salesforce.com/docs/atlas.en-us.change_data_capture.meta/change_data_capture/cdc_intro.htm
- Salesforce API End-of-Life Policy: https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/api_rest_eol.htm
- MuleSoft API-led connectivity (обзоры): https://dzone.com/articles/mulesoft-api-led-connectivity-architectural-and-de ; https://blogs.mulesoft.com/?p=29634
- SAP Clean Core и side-by-side: https://blog.sap-press.com/sap-s4hana-clean-core-principles-benefits-and-best-practices ; https://cdn.training.sap.com/cdn/pdf/2_Clean%20Core%20Extension.pdf/ES/EN ; https://answers.sap.com/t5/enterprise-resource-planning-blogs-by-sap/sap-s-4hana-clean-core-with-and-sap-btp/ba-p/13554328
- Dataverse business events и Service Bus: https://learn.microsoft.com/en-us/power-apps/developer/data-platform/business-events ; https://learn.microsoft.com/en-us/training/modules/integrations/4-outbound
- Dual-write (обзор): https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/data-entities/dual-write/dual-write-overview
- Odoo External RPC API (устаревание, JSON-2): https://www.odoo.com/documentation/saas-19.4/developer/reference/external_rpc_api.html
- OCA queue_job: https://github.com/OCA/queue/blob/12.0/queue_job/README.rst ; https://apps.odoo.com/apps/modules/17.0/queue_job
- Frappe Event Streaming (не поддерживается) и интеграции: https://docs.frappe.io/framework/help/event-streaming ; https://docs.frappe.io/erpnext/integrating-erpnext-with-other-applications
- 1С EnterpriseData: https://its.1c.ru/db/content/metod8dev/src/developers/dataexchange/enterprisedata/i8105851.htm ; https://its.1c.ru/db/metod8dev/browse/13/-1/3199/3210
- 1С:Шина (обзоры): https://infostart.ru/1c/articles/1892440/ ; https://infostart.ru/1c/articles/2718684/ ; https://habr.com/en/companies/w_code/articles/865602
- Bitrix24 вебхуки и события: https://apidocs.bitrix24.com/local-integrations/local-webhooks.html ; https://apidocs.bitrix24.com/api-reference/tasks/events-tasks/index.html
- Zoho Flow webhook trigger: https://help.zoho.com/portal/en/kb/flow/user-guide/build/webhook/articles/webhook-trigger
- HubSpot версии и вебхуки: https://developers.hubspot.com/changelog/spring-2026-spotlight ; https://developers.hubspot.com/docs/api-reference/error-handling ; https://developers.hubspot.com/changelog/introducing-version-3-of-webhook-signatures

---

## 2. Паттерны надёжной интеграции

### 2.1. Каталог паттернов: проблема → решение → реализация на Python и Postgres

| Паттерн | Какую проблему решает | Как сделать у нас [П] |
|---|---|---|
| **Transactional outbox** | Двойная запись «сохранил в БД и отправил в шину» неатомарна: либо событие теряется, либо уходит фантом [Ф, microservices.io] | Таблица `outbox` в БД каждой системы, запись в той же транзакции, что и бизнес-изменение (Django `transaction.atomic`, SQLAlchemy session). Ретранслятор читает через `FOR UPDATE SKIP LOCKED` и доставляет |
| **Inbox / идемпотентный потребитель** | Доставка at-least-once приводит к дублям [Ф] | Таблица `inbox(event_id PK, received_at, status)`. Обработка и вставка в `inbox` — в одной транзакции; повтор того же `event_id` — no-op |
| **Idempotency key для команд API** | Повтор POST после таймаута создаёт дубль (Stripe: ключ на запрос, сервер хранит результат) [Ф] | Заголовок `Idempotency-Key` на мутациях межсистемного API; хранение ответа 24–72 ч |
| **Change Data Capture (Debezium)** | Публикация изменений без правки кода приложения; Outbox Event Router маршрутизирует строки outbox по типу агрегата [Ф] | **Не сейчас.** Debezium работает на JVM и Kafka Connect (или Debezium Server). Для двух своих приложений outbox в коде дешевле. Вернуться, если понадобится CDC из чужой БД |
| **Retries с экспоненциальным backoff и jitter, DLQ** | Временные сбои внешних систем; «ядовитые» сообщения | Procrastinate retry или Celery `autoretry_for` с backoff. После N попыток статус `dead`, в UI кнопка «повторить» — как журнал вебхуков ERP→CRM, который уже есть |
| **Circuit breaker** | Повторы по лежащей системе (банк, soliq) добивают её и забивают воркеры [Ф, Fowler] | Счётчик ошибок на коннектор в Redis или Postgres. При «открытом» состоянии задачи откладываются без вызова |
| **Bulkhead** | Медленный коннектор съедает общий пул воркеров | Отдельная очередь и отдельный процесс-воркер на каждый коннектор, лимит параллельности, свой лимит памяти контейнера (cgroups) |
| **Anti-corruption layer (DDD)** | Модель 1С или SAP протекает в ядро | Модуль-переводчик на коннектор: EnterpriseData ↔ канонические события. Ядро не знает слов «Справочник.Контрагенты» |
| **Canonical data model** | N×M преобразований между системами [Ф, EIP] | Небольшой канонический словарь: Контрагент, Номенклатура, Документ, Сумма+Валюта, ИНН/ПИНФЛ. Только для межсистемных событий, не для внутренних таблиц |
| **Saga / процесс-менеджер** | Распределённая транзакция «заявка → КП → договор → счёт → ЭСФ» без 2PC [Ф] | Явная таблица состояний процесса в Postgres, переходы по событиям, компенсации. Temporal — позже (раздел 3.4) |
| **Message envelope, correlation id** | Трассировка и отладка цепочек [Ф, EIP] | Конверт CloudEvents (`id`, `source`, `type`, `time`, `subject`) плюс `traceparent` и `correlationid` |
| **Guaranteed delivery, competing consumers, content-based router** (EIP) | Базовые кирпичи любой шины [Ф] | Реализуются очередью: Postgres → позже NATS |

### 2.2. «Интеграция не должна останавливать ядро»: правила

Обобщение эталонов из раздела 1 и паттернов выше [П]:
1. **Ядро никогда не вызывает внешнюю систему синхронно в пользовательском запросе.** Пользователь получает
   «отправлено, статус: в очереди». Если синхронность нужна (проверка ИНН), то с жёстким таймаутом 2–3 с
   и fallback «проверим позже».
2. **Каждое исходящее действие — событие в outbox.** Доставку делает отдельный процесс.
3. **Очередь и воркер на каждый коннектор** (bulkhead), лимит повторов, DLQ, ручной повтор из UI.
4. **Входящие вебхуки** (банк, ЭДО-оператор) принимаются тонким приёмником. Он проверяет подпись, кладёт сырое
   сообщение в `inbox` и отвечает 200 за миллисекунды. Обработка идёт асинхронно.
5. **Деградация описана заранее.** Если упала 1С или ЭСФ, заявки, КП и склад работают, документы копятся
   в статусе «ожидает отправки». Это видно на дашборде, но не блокирует.

### 2.3. Микросервисы против модульного монолита

- **[Ф] Фаулер, «MonolithFirst»:** почти все успешные микросервисные системы начинались как монолит, который
  потом разросся и был разделён. Системы, сразу построенные на микросервисах, чаще попадали в серьёзные проблемы.
  Границы надо сначала найти.
- **[Ф] Shopify:** сохранили один кодовый репозиторий Rails, но ввели компоненты с владельцами и жёсткие границы.
  Для статической проверки зависимостей сделали инструмент Packwerk. Урок их первого прохода: компоненты
  без «стен» не работают — вызовы через границу и общие модели продолжались.
- **[Ф] Basecamp, «The Majestic Monolith»:** маленькой команде монолит даёт скорость. Распределённая система —
  налог, который окупается только на большом масштабе.
- **Вывод для RailTech [П].**
  - Три системы уже разделены (CRM, ERP, Cabinet) по главному пользователю. Дальше дробить не нужно.
  - Внутри каждой — модульный монолит с явными модулями и проверкой импортов в CI: `import-linter`
    для Python — аналог Packwerk.
  - EDS как третий логический домен: начать **модулем со своей схемой и своими событиями** внутри существующего
    бэкенда (вероятно, ERP — там документы). Контракт событий EDS публиковать так, будто это отдельная система.
    Тогда вынос в отдельный сервис позже — механическая операция, а не переписывание.

**Источники к разделу 2**
- Hohpe, Woolf, Enterprise Integration Patterns: https://www.enterpriseintegrationpatterns.com/patterns/messaging/
- Transactional outbox, идемпотентный потребитель, saga: https://microservices.io/patterns/data/transactional-outbox.html ; https://microservices.io/patterns/communication-style/idempotent-consumer.html ; https://microservices.io/patterns/data/saga.html
- Debezium Outbox Event Router: https://debezium.io/documentation/reference/2.4/transformations/outbox-event-router.html
- Stripe idempotent requests: https://docs.stripe.com/api/idempotent_requests
- Fowler, CircuitBreaker: https://martinfowler.com/bliki/CircuitBreaker.html
- Anti-corruption layer (Azure Architecture Center): https://learn.microsoft.com/en-us/azure/architecture/patterns/anti-corruption-layer
- Fowler, MonolithFirst: https://martinfowler.com/bliki/MonolithFirst.html
- Shopify: https://shopify.engineering/deconstructing-monolith-designing-software-maximizes-developer-productivity ; https://shopify.engineering/enforcing-modularity-rails-apps-packwerk ; https://shopify.engineering/shopify-monolith
- DHH, The Majestic Monolith: https://signalvnoise.com/svn3/the-majestic-monolith/
- import-linter (контроль границ модулей Python): https://import-linter.readthedocs.io/

---

## 3. Выбор шины для маленькой инфраструктуры

### 3.1. Ограничение CPU x86-64 v1: что запустится

Уровни микроархитектуры [Ф]: v1 — базовый x86-64; v2 добавляет SSE3, SSSE3, SSE4.1, SSE4.2, POPCNT, CMPXCHG16B;
v3 — AVX, AVX2, BMI1/2, FMA, MOVBE.

| Компонент / образ | Требование к CPU | Статус на нашем VPS |
|---|---|---|
| ClickHouse | SSE4.2 обязателен (установщик проверяет; официальной сборки без SSE4.2 нет) [Ф] | Не запустится. Следствие: Langfuse v3 (хранилище на ClickHouse) тоже [П: проверить по документации Langfuse] |
| Redpanda | «x86_64 (Westmere or newer)», ≥2 ГБ памяти на ядро [Ф]. Westmere — это SSE4.2 и POPCNT, то есть фактически v2 [П] | Не запустится [П, высокая уверенность]; по памяти тоже не влезает |
| Образы на RHEL 9 / UBI 9 | Базовый уровень RHEL 9 — x86-64-v2; при старте `Fatal glibc error: CPU does not support x86-64-v2` [Ф] | Не запустятся. Сюда относятся образы Confluent `cp-*` на ubi9-minimal/ubi9-micro [Ф: база UBI9; П: что падают] |
| Образы на Wolfi / Chainguard (официальный LiteLLM) | Известно на практике: не стартует на CPU без SSE4.x [П: анекдотическое свидетельство и ваш опыт] | Не запустится — у вас подтверждено |
| GraalVM native-image (например `apache/kafka-native`) | По умолчанию собирается под **x86-64-v3**; для старых CPU нужен `-march=compatibility` [Ф] | Скорее всего не запустится [П: флаги сборки kafka-native не проверены] |
| Apache Kafka на JVM (`apache/kafka`) | База `eclipse-temurin:25-jre-alpine` [Ф]; HotSpot JIT определяет возможности CPU на лету [П] | Скорее запустится [П], но 1–2 ГБ памяти на брокер [П] — дорого |
| NATS Server (Go) | Go по умолчанию собирает с `GOAMD64=v1`, бинарник проверяет уровень при старте [Ф] | Должен запуститься [П: проверить `nats-server -v` на сервере]. Память от 32 МиБ (core) и 64–256 МиБ (JetStream, файловое хранилище) в тестах минимальных конфигураций [Ф] |
| Temporal Server (Go) | То же, GOAMD64=v1 по умолчанию [Ф для Go; П для их сборки] | Должен запуститься [П]. Плюс 2 ГБ на однонодовую установку с Postgres по сторонним оценкам [Ф: сторонние гайды] |
| RabbitMQ (Erlang/OTP, JIT BeamAsm) | JIT включён по умолчанию на x86-64. Требования к наборам инструкций в документации не найдены; JIT можно отключить при сборке [Ф] | Вероятно запустится [П]. Проверка: `erl -noshell -eval 'io:format("~p~n",[erlang:system_info(emu_flavor)]),halt().'` |
| Redis / Valkey (C) | Собираются под базовый x86-64 [П] | Работает (уже используется в ERP для Celery и Channels [П по контексту]) |
| PostgreSQL, Python, Procrastinate, pgmq | Python и Postgres работают — по условию задачи. pgmq — расширение на SQL/Rust, поддерживает Postgres 14–18 [Ф] | Работают |
| n8n (Node.js) | Node на базовом x86-64 [П] | Вероятно запустится [П] |
| Apache Camel / Camel K | JVM | Запустится, но 0,5–1 ГБ и JVM-экспертиза [П] — не наш стек |

**Почти бесплатный рычаг [Ф+П].**
- QEMU-модель CPU `qemu64` намеренно минимальна: в ней нет SSE4.2 и POPCNT. Типовое лечение —
  `host-passthrough`, `host-model` или именованная модель (Nehalem и новее) [Ф].
- Скорее всего, физический CPU хоста намного новее, а VPS просто отдаёт гостю `qemu64` [П].
- Первое действие: проверить на сервере `/lib64/ld-linux-x86-64.so.2 --help | grep x86-64-v`. Ответ покажет
  поддерживаемые уровни (glibc ≥2.33). Затем попросить хостера сменить тип CPU или перейти на тариф
  с `host-model`.
- Это снимет половину ограничений сразу. Архитектуру при этом всё равно стоит строить так, чтобы она от этого
  не зависела.

### 3.2. Сравнение кандидатов на роль шины

Оценки памяти — порядок величины для однонодовой установки с малой нагрузкой [П]. Цифры с [Ф] — из документации.

| Критерий | PostgreSQL как очередь (outbox + Procrastinate/pgmq) | Redis Streams | NATS JetStream | RabbitMQ (quorum queues / streams) | Kafka / Redpanda |
|---|---|---|---|---|---|
| Надёжность доставки | Транзакционно с бизнес-данными (лучшее, что бывает для outbox). Долговечность = долговечность Postgres | At-least-once через consumer groups и PEL (XACK, XAUTOCLAIM) [Ф]. Долговечность зависит от AOF/fsync, по умолчанию возможна потеря до ~1 с [П] | Файловое хранилище, ack, повторная доставка, дедупликация по Msg-Id [Ф] | Quorum queues на Raft, рекомендованы для сохранности; обработка «ядовитых» сообщений встроена [Ф]. На одном узле реплик нет [П] | Лог с репликацией; эталон надёжности |
| Повтор, DLQ | Retry в Procrastinate [Ф]; visibility timeout и archive в pgmq [Ф]; DLQ — статус в таблице | Вручную: PEL + счётчик доставок → отдельный stream | MaxDeliver, BackOff, advisory-события о превышении [П: детали проверить] | delivery-limit и dead-letter exchange [Ф/П] | Вручную (retry-топики) |
| Порядок | Внутри ключа — через блокировки (Procrastinate locks) [Ф]; FIFO-группы в pgmq [Ф] | В пределах stream | В пределах subject и потребителя | В пределах очереди с одним потребителем; Single Active Consumer | В пределах партиции |
| Память | 0 сверх Postgres (БД на втором VPS) | Уже запущен — 0 сверх | 32–256 МиБ минимум [Ф]; прод-рекомендация 4 ядра / 8 ГиБ [Ф] — для кластера под нагрузкой | 150–400 МБ на узел [П]; порог памяти по умолчанию 0,6 RAM [П] | 1–2 ГБ+ (JVM) [П]; Redpanda ≥2 ГБ/ядро [Ф] |
| Эксплуатация | Нулевая: уже бэкапится, мониторится, знаком команде | Низкая | Низкая: один статический бинарник | Средняя: Erlang, политики, плагины | Высокая |
| x86-64 v1 | Да | Да | Вероятно да (Go v1) | Вероятно да | Kafka JVM — вероятно; Redpanda — нет |
| Путь к кластеру | Реплика Postgres; дальше упирается в одну БД | Sentinel/Cluster — слабые гарантии | Кластер из 3 узлов, R3 — штатно | Кластер из 3 узлов, quorum queues | Штатно, но тяжело |
| Межсистемная доставка (CRM ↔ ERP, разные БД) | Нужен ретранслятор и HTTP/вебхук между системами (у вас уже есть подписанные вебхуки ERP→CRM с журналом) | Да, общий брокер | Да, общий брокер | Да, общий брокер | Да |

**Ограничения Postgres как шины [Ф].**
- `LISTEN/NOTIFY` не долговечен: уведомление получают только подключённые слушатели, полезная нагрузка
  до ~8000 байт. Использовать его можно только как «будильник», источник правды — таблица.
- Очереди на таблицах требуют внимания к VACUUM и разбуханию при высокой частоте [П]. pgmq и Procrastinate
  решают это архивом и чисткой [Ф/П].
- Объём событий B2B-компании — тысячи–десятки тысяч в сутки [П]. Это на порядки ниже предела Postgres
  на `SKIP LOCKED`.

### 3.3. Рекомендация по шине (по версиям)

| Версия платформы | Транспорт шины | Почему |
|---|---|---|
| v1 «на коленках, но правильно» | **Postgres:** outbox и inbox в БД каждой системы; доставка между системами — подписанные HTTP-вебхуки с журналом (у вас уже есть ERP→CRM) плюс очередь на коннектор в Procrastinate (CRM) и Celery или Procrastinate (ERP) | Ноль новых сервисов, транзакционность, бэкап и мониторинг уже есть |
| v2 «одна шина для всех» | **NATS JetStream** одним узлом рядом с приложениями. Ретрансляторы outbox публикуют в JetStream, потребители и коннекторы подписываются. Postgres-outbox остаётся источником правды | Лёгкий (десятки–сотни МБ), Go, вероятно v1-совместим. Fan-out многим потребителям без N вебхуков, replay |
| v3 «отказоустойчивость» | NATS-кластер из 3 узлов (R3) на 2–3 VPS | Штатный путь роста NATS |
| Не брать | Kafka, Redpanda, Debezium, 1С:Шина-подобная ESB, Camel | Память, JVM, CPU v2+, операционная сложность несоразмерны объёму |

Ключевое [П]: код приложений знает только **свой интерфейс** `bus.publish(event)` / `@bus.subscribe(type)`.
Тогда транспорт меняется с «Postgres + HTTP» на NATS без правок бизнес-кода. Так поступает 1С:Шина
(брокер Artemis внутри — «чёрный ящик» для клиента [Ф]), и это главный урок оттуда.

### 3.4. Интеграционные движки и оркестрация

| Движок | Что это | Для RailTech [П] |
|---|---|---|
| Apache Camel | Библиотека EIP на JVM, сотни компонентов | Нет: JVM и чужой стек. Паттерны берём, движок — нет |
| n8n | Визуальный low-code iPaaS на Node.js, есть очередь на Redis | Возможно в v2–v3 как инструмент для внедренцев, чтобы клиенты собирали свои простые связки (аналог Zoho Flow или Power Automate). **Не** для критичных интеграций: логика уходит из-под контроля версий и тестов |
| Temporal | Durable execution: workflow как код, история в БД (Postgres поддерживается) [Ф] | v3, когда саг станет больше 3–5 и появятся долгие процессы с таймерами (договор → оплата → отгрузка → ЭСФ). Сейчас ~2 ГБ памяти [Ф: сторонние оценки] и новая операционная сущность. Промежуточный вариант — таблица состояний процесса плюс периодические задачи Procrastinate [П]. Лёгкая альтернатива на Python и Postgres — DBOS Transact [П: не исследовал] |
| Procrastinate (уже в CRM) | Очередь задач на Postgres: retry, блокировки для последовательного выполнения, periodic tasks, интеграция с Django [Ф] | Да, как транспорт v1 и для ERP: одна технология очередей на обе системы снижает когнитивную нагрузку. Celery в ERP оставить для существующего |

**Источники к разделу 3**
- Go GOAMD64 и уровни микроархитектуры: https://go.dev/wiki/MinimumRequirements
- RHEL 9 / UBI 9 x86-64-v2: https://www.phoronix.com/news/RHEL-9-x86-64-v2-Plans ; https://access.redhat.com/node/7057314 ; https://forums.rockylinux.org/t/fatal-glibc-error-cpu-does-not-support-x86-64-v2/14307/3
- QEMU qemu64 и host-passthrough: https://listman.redhat.com/archives/libguestfs/2022-April/028711.html
- Redpanda requirements: https://docs.redpanda.com/current/deploy/redpanda/manual/production/requirements/
- ClickHouse и SSE4.2 (косвенно): https://forum.sentry.io/t/onpremise-sentry-10-installation-issue/9530 ; https://www.hikunpeng.com/document/detail/en/kunpengdevps/userguide/usermanual/KunpengDevKit_0125.html
- GraalVM Native Image `-march` (по умолчанию x86-64-v3): https://www.graalvm.org/jdk25/reference-manual/native-image/optimizations-and-performance/ ; https://www.phoronix.com/news/GraalVM-JDK20-Summer-2023
- Apache Kafka Docker (JVM и native): https://github.com/apache/kafka/blob/trunk/docker/jvm/Dockerfile ; https://hub.docker.com/r/apache/kafka-native
- Confluent images на UBI9: https://docs.confluent.io/platform/current/installation/docker/image-reference.html
- LiteLLM на Chainguard / Wolfi: https://docs.litellm.ai/release_notes/v1.57.3 ; анекдот про старый CPU: https://derekcreason.substack.com/p/tech-updates-4
- Erlang BeamAsm JIT: https://www.erlang.org/doc/apps/erts/beamasm.html
- NATS sizing: https://docs.nats.io/learn/deployment/sizing-and-resources ; https://www.synadia.com/blog/why-is-jetstream-using-so-much-ram
- RabbitMQ quorum queues: https://www.rabbitmq.com/docs/quorum-queues
- Redis Streams consumer groups: https://redis.io/docs/latest/commands/xclaim/ ; https://redis.io/docs/latest/develop/data-types/streams/ ; persistence: https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/
- PostgreSQL NOTIFY: https://www.postgresql.org/docs/current/sql-notify.html
- pgmq: https://github.com/pgmq/pgmq
- Procrastinate: https://procrastinate.readthedocs.io/en/stable/
- Temporal (сторонние оценки ресурсов): https://ramnode.com/guides/temporal ; https://docs.controlplane.com/template-catalog/templates/temporal ; официально: https://docs.temporal.io/self-hosted-guide
- Langfuse self-hosting (v3 требует ClickHouse — проверить): https://langfuse.com/self-hosting

---

## 4. Стандарты контрактов и версионирования

### 4.1. Стандарты

| Стандарт | Для чего | Статус и факты | Для RailTech [П] |
|---|---|---|---|
| **OpenAPI 3.1** | Синхронные API | 3.1 полностью совместим с JSON Schema 2020-12 [Ф] | Уже используется в `packages/contracts`. Оставить |
| **AsyncAPI 3.0** | События: каналы, операции, сообщения; «OpenAPI для событий» | В 3.0 разделены каналы и операции (send/receive), поддерживаются NATS, AMQP, Kafka, HTTP [Ф] | Описать все события шины в одном AsyncAPI-документе на систему-издателя |
| **CloudEvents 1.0** (CNCF) | Единый конверт события: `specversion`, `id`, `source`, `type`, `time`, `subject`, `datacontenttype`, `dataschema`; привязки к HTTP, AMQP, NATS, Kafka; расширение distributed tracing (`traceparent`) [Ф] | Графирован в CNCF [Ф] | Конверт всех событий. Транспорт меняется — конверт нет |
| **JSON Schema 2020-12** | Схема полезной нагрузки | Общая для OpenAPI 3.1 и AsyncAPI [Ф] | Схема `data` каждого типа события, ссылка в `dataschema` |
| **Schema registry** | Хранение версий схем и проверка совместимости (backward / forward / full) — Confluent, Apicurio [Ф] | — | На v1 «реестр» — каталог `packages/contracts/events/<type>/v<N>.json` в git, плюс проверка совместимости в CI. Отдельный сервис — не раньше v3 |
| **Pact (consumer-driven contracts)** | Потребитель фиксирует ожидания, поставщик проверяет их в CI; есть поддержка сообщений (message pacts) [Ф] | Pact Broker — отдельный сервис [Ф] | Для пары CRM↔ERP полезно, но Broker не нужен: pact-файлы хранить в `packages/contracts` [П] |
| **Semver** | MAJOR — несовместимо, MINOR — совместимое добавление, PATCH — исправление [Ф] | — | Версия контракта события в типе: `...order.confirmed.v1`. Пакет contracts — semver |
| **Deprecation / Sunset HTTP-заголовки** | Машинно-читаемое предупреждение об устаревании | RFC 8594 (Sunset), RFC 9745 (Deprecation) [Ф] | Ставить на устаревающие эндпойнты; клиенты логируют |

### 4.2. Политика версий API и событий: как у эталонов

- **Правило совместимости [Ф: Google AIP, общая практика].** В пределах мажора разрешены только добавления:
  новые необязательные поля, новые эндпойнты и типы событий. Удаление, переименование, смена типа или
  смысла поля означают новый мажор.
- **Потребитель терпим к новым полям** (tolerant reader, Фаулер) [Ф]. Обязательно для событий:
  потребитель игнорирует неизвестные поля.
- **Окно поддержки**: Salesforce ≥3 года, HubSpot 18 мес., 1С EnterpriseData ≥1 год после новой major [Ф].
  Для RailTech разумно [П]: старый мажор живёт ≥2 релизных поезда и ≥6 месяцев после выхода нового,
  внешние клиенты уведомляются за ≥3 месяца.
- **Двойная публикация при смене мажора события [П]**: издатель некоторое время шлёт `v1` и `v2`, потребители
  мигрируют, затем `v1` выключается. Это аналог expand-contract для событий.

### 4.3. Как версионируют релизы платформ

| Практика | Эталон | Суть | Для RailTech [П] |
|---|---|---|---|
| Release train | Salesforce — три релиза в год (Spring, Summer, Winter) [Ф: общеизвестно, ссылка ниже]; HubSpot — март и сентябрь [Ф] | Фиксированный календарь, «поезд уходит вовремя» | Ежемесячный поезд платформы `2026.11`, `2026.12`; хотфиксы — патч-версии |
| LTS | Odoo (мажор раз в год, поддержка трёх последних) [П: проверить]; Ubuntu LTS | Длинная поддержка выбранных версий для консервативных клиентов | Не раньше, чем появятся внешние компании-клиенты (v3+) |
| Trunk-based development | trunkbaseddevelopment.com | Короткоживущие ветки, частое слияние в main | Уже практикуется (ветки → PR → main) |
| Feature flags | Fowler / Hodgson, «Feature Toggles» [Ф] | Выкатка кода отдельно от включения функции; флаги релизные, операционные, разрешений | Флаги на компанию-арендатора и роль. Особенно полезны для коннекторов: «ЭСФ: включено для компании X» |
| Expand-contract (parallel change) миграций БД | Fowler «ParallelChange» [Ф] | Сначала добавить новое (expand), перевести код, потом удалить старое (contract) — каждый шаг отдельным релизом | Обязательное правило для Alembic и Django-миграций: никаких «переименовать колонку» одной миграцией |

**Источники к разделу 4**
- OpenAPI 3.1: https://spec.openapis.org/oas/v3.1.0
- AsyncAPI 3.0: https://www.asyncapi.com/docs/reference/specification/v3.0.0
- CloudEvents: https://github.com/cloudevents/spec/blob/main/cloudevents/spec.md ; расширение distributed tracing: https://github.com/cloudevents/spec/blob/main/cloudevents/extensions/distributed-tracing.md ; https://cloudevents.io/
- JSON Schema: https://json-schema.org/specification
- Confluent Schema Registry, режимы совместимости: https://docs.confluent.io/platform/current/schema-registry/fundamentals/schema-evolution.html ; Apicurio: https://www.apicur.io/registry/
- Pact: https://docs.pact.io/ ; message pacts: https://docs.pact.io/getting_started/how_pact_works#non-http-testing-message-pact
- Semantic Versioning: https://semver.org/
- RFC 8594 Sunset: https://www.rfc-editor.org/rfc/rfc8594 ; RFC 9745 Deprecation: https://www.rfc-editor.org/rfc/rfc9745
- Google AIP-180 (обратная совместимость): https://google.aip.dev/180
- Fowler, TolerantReader: https://martinfowler.com/bliki/TolerantReader.html ; ParallelChange: https://martinfowler.com/bliki/ParallelChange.html ; Feature Toggles: https://martinfowler.com/articles/feature-toggles.html
- Trunk-based development: https://trunkbaseddevelopment.com/
- Stripe API versioning: https://stripe.com/blog/api-versioning
- Salesforce releases: https://help.salesforce.com/s/articleView?id=release-notes.salesforce_release_notes.htm
- HubSpot versioning: https://developers.hubspot.com/changelog/spring-2026-spotlight

---

## 5. Надёжность и эксплуатация бизнес-платформы

### 5.1. SLO, SLA, бюджет ошибок

- **[Ф] Google SRE.** SLI — измеряемая метрика (доля успешных запросов, задержка). SLO — целевое значение.
  SLA — договорное обязательство с последствиями.
- **[Ф] Бюджет ошибок** = 1 − SLO. Политика бюджета определяет, что происходит при его исчерпании:
  заморозка фич, приоритет надёжности.
- **Для RailTech [П].** Раздельные SLO для ядра и интеграций — прямое выражение принципа «интеграция
  не останавливает ядро»:

| Контур | SLI | SLO (стартовый) |
|---|---|---|
| Ядро: UI и API сотрудников | доля успешных запросов (не 5xx) и p95 задержки | 99,5 % в месяц (~3,6 ч простоя); p95 < 800 мс |
| Портал клиента | доступность | 99,5 % |
| Шина: доставка событий между системами | возраст самого старого недоставленного события; p95 «опубликовано → обработано» | p95 < 1 мин; ни одно событие не старше 15 мин без алерта |
| Внешние коннекторы (1С, ЭСФ, банк) | доля сообщений, доставленных за 1 ч; размер DLQ | 99 % за 1 ч; DLQ = 0 в конце дня (разобрано вручную) |

Падение 1С или soliq.uz не тратит бюджет ядра [П].

### 5.2. Наблюдаемость

- **[Ф] OpenTelemetry, messaging semconv.** Связать трассу потребителя с трассой издателя можно, только если
  контекст передаётся с сообщением. Трассировка брокера транспорт не связывает.
  - Издатель **должен** прикреплять к каждому сообщению контекст создания (creation context).
  - Для пакетной обработки используются span links.
  - Конвенции имеют статус «экспериментальные».
- **[П] Практически:**
  - `traceparent` (W3C Trace Context) кладётся в CloudEvents-расширение и в заголовки HTTP-вебхуков.
  - Ретранслятор outbox и воркеры коннекторов создают span `publish` / `process`.
  - Метрики: длина очереди и возраст старейшего сообщения по каждому коннектору, число повторов, размер DLQ,
    состояние circuit breaker.
  - Логи — JSON с `trace_id`, `event_id`, `tenant`.
  - На v1 хватит OpenTelemetry SDK, экспорта в один бэкенд с низким потреблением памяти и Prometheus-метрик.
    Конкретный бэкенд выбирать с учётом CPU v1: ClickHouse-based не подойдут.

### 5.3. Резервирование, RPO и RTO

- **[Ф]** RPO — допустимая потеря данных во времени, RTO — допустимое время восстановления.
- **[Ф] AWS Well-Architected, стратегии DR** в порядке роста стоимости: backup & restore → pilot light →
  warm standby → multi-site active/active.
- **[П] Для RailTech:**
  - v1: backup & restore с непрерывным архивом WAL (pgBackRest или WAL-G) в объектное хранилище в другой
    локации. RPO ≤ 5 мин, RTO ≤ 4 ч. **Ежемесячная проверка восстановления** — бэкап без проверки не считается.
  - v2: потоковая реплика Postgres (pilot light / warm standby). RTO ≤ 1 ч.
  - Outbox и inbox в той же БД — значит, после восстановления события не теряются и не дублируются сверх
    идемпотентности.

### 5.4. Деградация

| Что упало | Что продолжает работать [П: целевое поведение] |
|---|---|
| 1С / SAP | Всё ядро; выгрузки копятся в очереди коннектора; баннер «синхронизация с 1С отложена» |
| ЭСФ / ЭДО-оператор | Документы создаются и подписываются; статус «ожидает отправки», повтор с backoff; при открытом circuit breaker — без нагрузки на оператора |
| Банк-клиент | Счета выставляются; выписки догоняются при восстановлении (идемпотентно по ID операции банка) |
| LiteLLM / провайдер модели | CRM и бот уходят в режим «оператор» (передача человеку), ядро не страдает |
| Шина (NATS в v2) | Outbox копит события в Postgres; ретранслятор догоняет — ядро не блокируется |
| ERP недоступна для CRM | CRM работает с последним известным состоянием; команды в ERP копятся в outbox CRM |

### 5.5. Масштабирование: от одного сервера к нескольким

Порядок шагов [П, опирается на MonolithFirst и опыт Shopify и Basecamp]:
1. **Вертикально и разделить роли.** БД уже на отдельном VPS — это правильный первый шаг. Ограничить память
   каждого контейнера и вынести воркеры коннекторов в отдельные контейнеры (bulkhead на уровне ОС).
2. **Второй прикладной VPS.** Перенести туда «шумное»: воркеры интеграций, ИИ (LiteLLM, бот), NATS.
   Веб-процессы ядра остаются на первом.
3. **Реплика БД** для чтения и отчётов; пул соединений (PgBouncer).
4. **Горизонтально.** Несколько экземпляров stateless-веб за Caddy; NATS-кластер из трёх узлов; Postgres
   с автоматическим переключением (Patroni).
5. Только потом — отдельные БД или сервисы для доменов, у которых доказанная независимая нагрузка.

### 5.6. Мультиарендность

- **[Ф] AWS SaaS Lens.**
  - **Silo** — выделенные ресурсы на арендатора: сильнейшая изоляция, самая высокая стоимость.
  - **Pool** — общие ресурсы, изоляция в ПО (например, Row-Level Security Postgres): самая дешёвая
    и самая слабая изоляция.
  - **Bridge** — смешение моделей по слоям или сервисам.
  - «Targeted isolation» — разные модели для разных микросервисов (например, свой БД-слой
    для «регулируемых» арендаторов).
- **[П] Для RailTech:**
  - Сейчас одна установка на одну компанию, то есть silo по развёртыванию. Это нормально для большого
    клиента и проще в соответствии требованиям (данные клиента в его контуре).
  - Чтобы не закрыть путь к pool для малых компаний, **сейчас** нужно:
    - `tenant` в конверте каждого события (расширение CloudEvents) и в ключах идемпотентности;
    - настройки и справочники компании — данные, а не код (у CRM уже есть settings);
    - коннекторы конфигурируются на арендатора (учётные данные 1С, ЭСФ, банка — в секрет-хранилище по tenant).
  - Pool с RLS — отдельное архитектурное решение (ADR) не раньше v3.
  - Модель bridge выглядит так: малые компании — pool, крупные — silo, общий код и контракты.

**Источники к разделу 5**
- Google SRE Book, SLO: https://sre.google/sre-book/service-level-objectives/ ; Error budget policy: https://sre.google/workbook/error-budget-policy/
- OpenTelemetry messaging spans: https://opentelemetry.io/docs/specs/semconv/messaging/messaging-spans/ ; OTEP-0220: https://github.com/open-telemetry/oteps/blob/main/text/trace/0220-messaging-semantic-conventions-span-structure.md
- W3C Trace Context: https://www.w3.org/TR/trace-context/
- AWS DR strategies: https://docs.aws.amazon.com/whitepapers/latest/disaster-recovery-workloads-on-aws/disaster-recovery-options-in-the-cloud.html
- pgBackRest: https://pgbackrest.org/ ; WAL-G: https://github.com/wal-g/wal-g
- AWS SaaS Lens, silo / pool / bridge: https://docs.aws.amazon.com/wellarchitected/latest/saas-lens/silo-pool-and-bridge-models.html ; https://docs.aws.amazon.com/wellarchitected/latest/saas-lens/bridge-model.html ; https://docs.aws.amazon.com/wellarchitected/latest/saas-lens/targeted-isolation.html ; https://docs.aws.amazon.com/solutions/multi-tenant-architectures-on-aws/
- PostgreSQL Row Level Security: https://www.postgresql.org/docs/current/ddl-rowsecurity.html

---

## 6. Эталон → что брать RailTech: 20 рекомендаций

Все рекомендации — [П]: вывод автора из фактов выше с учётом ограничений (маленькая команда агентов, один сервер,
Python, Postgres, CPU v1). Каждая крупная — кандидат в ADR.

| № | Эталон | Что берём | Как конкретно у нас | Версия |
|---|---|---|---|---|
| 1 | SAP Clean Core; Frappe «прямой SQL не порождает событий» | **Граница ядра неприкосновенна** | Внешнее подключается только через опубликованный API или событие из `packages/contracts`. Никаких прямых чтений чужих БД, никаких правок ядра «под 1С» | v1 |
| 2 | MuleSoft API-led | **Три слоя** | System — коннекторы (1С, ЭСФ, банк, таможня), по модулю на систему. Process — процессы и саги. Experience — BFF для SPA сотрудников и портальный API. BFF не содержит бизнес-правил ядра | v1 |
| 3 | 1С:Шина (брокер — «чёрный ящик») | **Собственный интерфейс шины** | Пакет `rt_bus` (Python): `publish`, `subscribe`, конверт, подпись, идемпотентность. Транспорт v1 — Postgres + HTTP, v2 — NATS. Бизнес-код транспорт не видит | v1 |
| 4 | microservices.io, Debezium | **Transactional outbox в каждой системе** | Таблица `outbox` в CRM и ERP (и в модуле EDS), запись в той же транзакции. Ретранслятор — периодическая задача Procrastinate или Celery с `SKIP LOCKED` | v1 |
| 5 | EIP «idempotent receiver»; Stripe | **Inbox и Idempotency-Key** | `inbox(event_id PK)` у каждого потребителя; `Idempotency-Key` на межсистемных POST | v1 |
| 6 | OCA `queue_job` (каналы); Dataverse async jobs | **Очередь и воркер на каждый коннектор (bulkhead)** | Отдельная очередь Procrastinate или Celery и отдельный контейнер с лимитом памяти на каждый внешний коннектор. Коннектор падает — ядро работает | v1 |
| 7 | HubSpot (10 повторов за 24 ч с разбросом); Frappe Integration Request | **Повтор с backoff и jitter, DLQ, журнал и ручной повтор** | Единая таблица журнала интеграций (как журнал вебхуков ERP→CRM) для всех коннекторов. После N попыток — `dead`, в админке кнопка «повторить». Тот же UI для всех коннекторов | v1 |
| 8 | Fowler CircuitBreaker | **Предохранитель на внешнюю систему** | Состояние в Redis на коннектор; при «открытом» — откладываем без вызова; алерт | v1 |
| 9 | CloudEvents | **Единый конверт событий** | `specversion, id, source, type, time, subject, dataschema` + расширения `tenant`, `traceparent`, `correlationid`. Тип: `uz.railtech.<домен>.<сущность>.<действие>.v<N>` | v1 |
| 10 | AsyncAPI + JSON Schema; Confluent compatibility modes | **Контракт событий раньше кода, проверка совместимости в CI** | `packages/contracts/events/` — AsyncAPI 3 и JSON Schema на тип. `make contracts` проверяет: в пределах мажора только добавления (diff схем); для OpenAPI — `oasdiff` breaking-check | v1 |
| 11 | EnterpriseData 1С; Canonical Data Model (EIP); DDD ACL | **Канонические межсистемные сущности и ACL на коннектор** | Словарь: Контрагент (ИНН/ПИНФЛ), Номенклатура, Документ, Сумма+Валюта, Склад. Коннектор 1С переводит EnterpriseData ↔ канон и учитывает версию формата EnterpriseData. Внутренние модели CRM и ERP остаются своими | v1–v2 |
| 12 | microservices.io Saga; Temporal | **Явные процесс-менеджеры, без 2PC** | Сквозные процессы (заявка → КП → договор → счёт → ЭСФ) — таблица состояний и обработчики событий с компенсациями. Temporal (Go, Postgres) рассматривать в v3, когда долгих процессов с таймерами станет много | v1 → v3 |
| 13 | Salesforce EOL policy; HubSpot 18 мес.; RFC 8594/9745 | **Опубликованная политика версий** | Мажор в пути (`/api/v1`) и в типе события. Только аддитивные изменения в мажоре. Старый мажор ≥6 мес. и ≥2 поезда после нового. Заголовки `Deprecation`/`Sunset`; после снятия — 410 | v1 |
| 14 | Salesforce и HubSpot release trains; trunk-based; feature toggles | **Ежемесячный релизный поезд и флаги** | Версия платформы `YYYY.MM` (ансамбль CRM+ERP+Cabinet+contracts вместе), хотфиксы — патчи. Флаги на арендатора и коннектор. LTS — только когда появятся внешние компании | v1–v2 |
| 15 | Fowler ParallelChange | **Expand-contract миграций и событий** | Никаких разрушающих миграций одним шагом. Смена мажора события — двойная публикация `v1`+`v2` на время перехода | v1 |
| 16 | Pact | **Контрактные тесты CRM ↔ ERP** | Pact-файлы (HTTP и message) в `packages/contracts`, проверка поставщиком в `make check-*`. Pact Broker не разворачивать | v2 |
| 17 | OpenTelemetry messaging semconv; W3C Trace Context | **Сквозная трасса через шину** | `traceparent` в конверте и в вебхуках; spans publish и process; метрики «возраст старейшего сообщения» и «размер DLQ» на коннектор. Бэкенд наблюдаемости — без ClickHouse, пока CPU v1 | v1–v2 |
| 18 | Google SRE; AWS DR | **Раздельные SLO ядра и интеграций, RPO/RTO** | Таблица 5.1. WAL-архив (pgBackRest или WAL-G) вне площадки, RPO ≤ 5 мин, RTO ≤ 4 ч, ежемесячная проверка восстановления | v1 |
| 19 | NATS (Go, v1-совместим, малая память) против Kafka/Redpanda | **Путь роста шины** | v1 Postgres+HTTP → v2 NATS JetStream одним узлом → v3 кластер из трёх узлов. Kafka, Redpanda, Debezium, Camel — не брать. Перед v2 — проверить `nats-server` на реальном CPU | v2–v3 |
| 20 | Bitrix24 и HubSpot Marketplace; AWS SaaS Lens | **Коннектор как устанавливаемое «приложение» и готовность к мультиарендности** | Манифест коннектора: версия, подписки на события, нужные права, схема настроек, секреты на арендатора, флаг включения. `tenant` в событиях с первого дня. Сейчас silo (установка на компанию), позже bridge: малые — pool с RLS, крупные — silo | v1 (манифест, tenant) → v3 (pool) |

**Дополнительно, вне таблицы [П]: CPU.** До выбора компонентов v2 попросить хостера включить
`host-model`/`host-passthrough` или сменить тариф.
- Проверка: `/lib64/ld-linux-x86-64.so.2 --help | grep x86-64-v` и `grep -c sse4_2 /proc/cpuinfo`.
- Пока это не решено, правило выбора образов: Debian, Ubuntu или Alpine; не UBI9 и не Wolfi/Chainguard;
  нативные бинарники — сборки GOAMD64=v1 или `-march=compatibility`.
- Добавить в CI или в `make smoke` проверку старта каждого образа под `qemu-x86_64 -cpu qemu64`. Это дешёвый
  способ ловить регрессии CPU до деплоя [П: проверить применимость на Mac с Docker Desktop].

### 6.1. Поэтапная дорожная карта по версиям платформы

| Версия | Цель | Что входит | Критерий перехода к следующей |
|---|---|---|---|
| **v1 «правильно на коленках»** (один VPS + БД) | Нерушимая граница и асинхронные интеграции | Рекомендации 1–11, 13–15, 18; `rt_bus` на Postgres+HTTP; первые коннекторы (ЭСФ через оператора ЭДО, банк, 1С) каждый в своей очереди; единый журнал интеграций в админке | Больше 3–4 потребителей одних событий **или** необходимость replay **или** второй прикладной сервер |
| **v2 «одна шина»** (2 прикладных VPS) | Fan-out и replay без N вебхуков | NATS JetStream одним узлом за `rt_bus`; Pact; OTel-трассы через шину; реплика Postgres; релизный поезд с флагами на арендатора | Требование доступности > 99,5 % **или** вторая компания-клиент |
| **v3 «отказоустойчивость и арендаторы»** | Без единой точки отказа; несколько компаний | NATS-кластер из трёх узлов; Patroni; Temporal для долгих процессов; ADR по pool/RLS для малых компаний; каталог коннекторов с манифестами | Внешние разработчики коннекторов, требования LTS |
| **v4 «экосистема»** | Платформа для партнёров | Публичный портал разработчика (OpenAPI и AsyncAPI), версии по дате (как HubSpot или Stripe), LTS-ветки, sandbox на арендатора | — |

### 6.2. Что осталось непроверенным и что проверить первым

1. Фактический уровень CPU и возможность `host-model` у хостера. От этого зависит половина ограничений.
2. Старт `nats-server`, `temporalio/server` и `rabbitmq` на этом CPU — двухминутный эксперимент
   на каждый образ.
3. Требует ли текущий Langfuse ClickHouse. Если да, нужна альтернатива или версия без ClickHouse.
4. API операторов ЭДО и ЭСФ Узбекистана (Didox и другие; обязательность ЭСФ с 1 января 2020 г. [Ф]).
   Публичной документации API в этом поиске не найдено. Нужен отдельный запрос операторам.
   Готовность коннектора как «приложения» (рекомендация 20) не зависит от выбора оператора.
5. Детали dual-write Dynamics и Operations Hub HubSpot в этом исследовании не проверялись. На выводы
   не влияют.

**Источники к разделу 6** — см. разделы 1–5. Дополнительно:
- oasdiff (обнаружение несовместимых изменений OpenAPI): https://github.com/oasdiff/oasdiff
- glibc-hwcaps и `ld.so --help`: https://www.gnu.org/software/libc/manual/html_node/Dynamic-Linker-Introspection.html ; https://www.phoronix.com/news/RHEL-9-x86-64-v2-Plans
- Patroni: https://patroni.readthedocs.io/
- ЭСФ в Узбекистане: https://gov.uz/ru/soliq/pages/elektron-hisobvaraq-fakturalar ; https://buxgalter.uz/ru/publish/doc/text171838_kak_opredelitsya_s_operatorom_esf_sravnitelnaya_tablica ; https://www.spot.uz/ru/2019/12/30/factures/
