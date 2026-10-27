# CONTRACTS — шов между CRM и ERP (и портальный вход Cabinet, сервис EDS)
Статус: действует · Владелец: архитектор · Обновлено: 2026-10-26

Версия 0 · 2026-10-13 · Источник истины — файлы в `packages/contracts/` (OpenAPI — в том числе `crm.yaml`, который генерирует CRM, — и JSON-схемы);
этот документ объясняет их. Изменение контракта — PR с обеих сторон в одной вехе (ORCHESTRATOR §3.3).

## 0. Общие правила

- Транспорт: HTTPS, JSON, UTF-8. Даты — ISO-8601 с часовым поясом. Деньги — строка с двумя знаками и
  код валюты ISO-4217. Идентификаторы — целые, непрозрачные для другой стороны.
- Ошибки — `{"detail": "<CODE>"}` (формат ERP) и `{"error": {"code": ..., "reason": ...}}` (формат CRM,
  ADR-0017); каждая сторона сохраняет свой формат, клиенты генерируются из OpenAPI.
- Идемпотентность: заголовок `Idempotency-Key` на всех POST; ERP хранит ключ 7 дней.
- Аутентификация машин: `Authorization: Bearer <SERVICE_TOKEN>` (по токену на направление:
  `CRM→ERP`, `ERP→CRM`), ротация без простоя (два активных). Токены выдаёт **сопряжение по одноразовому коду**
  (§2, «Сопряжение»): CRM генерирует их сама, ERP хранит шифрованно в базе; секреты окружения (`.env`) — запасной путь,
  пока сопряжения нет.
- Внешние идентификаторы хранят обе стороны: CRM — `erp_company_id`, `erp_deal_id`, `erp_document_id`;
  ERP — `crm_client_id`, `crm_lead_id`, `crm_contact_id`, `crm_user_id`.
- Никакие вызовы не принимают идентификатор клиента от модели: для агентов — только `X-Agent-Context`.

## 1. Пространства API ERP

| Пространство | Префикс | Кто зовёт | Аутентификация |
|---|---|---|---|
| internal | `/api/v1/` | ERP SPA (сотрудники) | JWT сотрудника |
| portal | `/api/portal/v1/` | Cabinet SPA (клиенты) | сессия портала (Telegram initData / magic-link) |
| integration | `/api/integration/v1/` | CRM | сервисный токен |
| mcp | `/mcp/erp` | агент CRM | `X-Agent-Context` (HMAC) |

Contract-first действует для `portal`, `integration`, событий и `erp-mcp`: их файлы в `packages/contracts` пишутся руками и сверяются с кодом сторожами ERP. **`internal` — наоборот: `openapi/erp-internal.yaml` генерируется из drf-spectacular (срез `/api/v1/` выгрузки `apps/erp/backend/schema.json`; `make -C apps/erp openapi`) и руками не правится.** Дрейф кода и выгрузки ловит `make -C apps/erp openapi-check` (`make ci-local erp`, шаг CI «ERP · check»). Правдивость описания (D2-0, B-011): выгрузка `/api/v1/` строится без предупреждений drf-spectacular (`manage.py openapi_v1_check`, тоже в `openapi-check`), тела отказов описаны общими компонентами `ErrorDetail`/`BadRequest`, а живые ответы операций, которые зовёт BFF, сверяет с выгрузкой `core/tests/test_openapi_*_conformance.py` в тестах ERP. Типы ERP SPA строятся из `backend/schema.json`, отдельного `generated/erp-internal.d.ts` нет.

## 2. Integration API (CRM → ERP)

| Метод и путь | Назначение | Тело / ответ (главное) |
|---|---|---|
| `POST /clients/handoff` | передача клиента из CRM | вход: `crm_client_id`, `crm_lead_id?`, `company{name, inn?, segment?, language}`, `contacts[{crm_contact_id, name, phone?, email?, telegram_user_id?, language, is_primary, preferred_channel}]`, `need{summary, product_interest[], attachments[]?}`, `owner{crm_user_id, name}`, `consent{given_at, version}`, `create_request: bool`, `invite{channels: [telegram, email]}`. Ответ: `erp_company_id`, `erp_request_id?`, `invite{sent_via[], cabinet_url}`. Идемпотентно по `crm_client_id` |
| `PUT /contacts/{crm_contact_id}` | обновление контакта / Telegram-привязки | те же поля контакта |
| `GET /companies/{erp_company_id}/summary` | карточка клиента для CRM | открытые сделки, последний документ, дебиторка, ближайшая поставка |
| `GET /companies/{erp_company_id}/deals` | список сделок | `[{erp_deal_id, number, title, stage, amount, currency, next_step, updated_at}]`; `amount` — сумма последнего КП, отправленного клиенту, `null` — КП ещё не отправлялось (черновик не утекает) |
| `GET /deals/{erp_deal_id}` | сделка | стадия, КП (версия, статус, публичная ссылка), договор, счета, поставки (проекция клиента), акты |
| `GET /deals/{erp_deal_id}/documents` | документы сделки | `[{erp_document_id, kind, number, date, title, status}]` |
| `GET /documents/{erp_document_id}/link` | ссылка на файл | подписанный URL на 10 минут на публичный маршрут ERP (токен проверяется во вьюхе); выдача и скачивание — в журнал ERP с `crm_*` контекстом; без сопоставления компании, черновик или внутренний документ — 404 |
| `GET /catalog/search?q=&mode=lead|client` | опубликованный каталог | в режиме `lead` без цен и остатков; в `client` — с ценой и статусом наличия |
| `POST /users/provision` | сотрудник из CRM | `crm_user_id, email, name, role (admin|backoffice), permissions[]` (коды каталога ERP, `ErpPermission`; чужой код → 422), необязательное `role_codes[]` (системные роли бэк-офиса, `SystemRoleCode`: `CALCULATION, CATALOG_SUPPLY, FULFILLMENT, FINANCE, HEAD, VIEWER`; чужой код → 422; поля нет — системные роли не трогаются; ERP снимает только выданные ранее из CRM; ручные роли не затираются); ответ `erp_user_id`; e-mail занят другим пользователем ERP (другой `crm_user_id` или нет сопоставления) → 409 `EMAIL_CONFLICT` |
| `DELETE /users/{crm_user_id}/sessions` | отзыв сессий и входа | при снятии доступа в CRM: refresh и access-токены гаснут (прежний access → 401), вход закрыт; аудит `sso.revoke` |
| `GET /health` | здоровье для «Состояния системы» CRM и центра внешних сервисов | версия, миграции применены, очередь жива; `externals[]` (M3-ERP-06, необязательно) — внешние сервисы ERP: `code` (`cbu_rates`, `customs_tariff`, `mail`, `litellm`, `s3`, `sentry`), `status` (`ok`/`degraded`/`fail`/`unknown`/`disabled`), `enabled`, `switchable`, `last_success_at`, `last_error_at`, `last_error` (≤ 200 знаков, без секретов), `ok_24h`, `errors_24h` |
| `PUT /externals/{code}/switch` | выключатель внешнего сервиса ERP из центра внешних сервисов CRM (M3-ERP-06) | вход: `enabled`, `reason?`; ответ: `code`, `enabled`, `changed_at`. Идемпотентно; неизвестный `code` → 404, Sentry (`switchable: false`) → 409 `NOT_SWITCHABLE` |
| `POST /pairing/accept` | сопряжение по одноразовому коду (вместо ручного копирования ключей) | вход: `crm_to_erp_token`, `erp_to_crm_token`, `webhook_secret` (CRM генерирует сама); аутентификация — код сопряжения, не сервисный токен. Ответ: `paired`, `paired_at`, `erp_version`. Вместо кода допустим `X-Pairing-Proof` (bootstrap, ниже). Ошибки 401: `PAIRING_CODE_INVALID`/`_EXPIRED`/`_USED`, `PAIRING_PROOF_INVALID`/`_EXPIRED`/`_REPLAYED`; 409 `BOOTSTRAP_CLOSED` |
| `POST /pairing/rotate` | ротация ключей без простоя | вход — новая тройка секретов под действующим токеном CRM→ERP; прежний токен действует ещё `previous_token_valid_until` (два активных), затем 401 |

Сопряжение (M3-ERP-05, M3-CRM-10, §3.13 ORCHESTRATOR): ERP выпускает код (суперпользователь в «Настройки → Интеграция с CRM»
либо `manage.py pairing_code`; 15 минут, один раз, хеш в базе, новый код гасит прежний). Админ в CRM «Подключения → ERP» вводит адрес и
код, CRM генерирует три секрета (токены CRM→ERP и ERP→CRM, секрет вебхуков), вызывает `POST /pairing/accept` с кодом вместо токена,
сохраняет секреты у себя и сразу делает «Проверить связь» (`GET /health`). ERP хранит секреты шифрованно в базе
(Fernet, ключ из `SECRET_KEY`); аутентификация integration берёт токены оттуда, а от секрета вебхуков шина выводит секреты пары CRM ↔ ERP (§9.3); `.env` — только
пока в базе пусто. «Обновить ключи» — `POST /pairing/rotate`: ERP принимает новую тройку по действующему токену, прежний токен CRM→ERP действует
ещё переходный срок (по умолчанию 1 час), прежний секрет вебхуков (а с ним и выведенный из него секрет пары) CRM принимает наравне с новым. Читатель терпимый: новые поля
ответов сопряжения CRM игнорирует.

**Первое сопряжение без кода (bootstrap).** На свежем проде в ERP некому выпустить код, а сотрудники приходят из CRM
провижинингом, который требует сопряжения. Поэтому пока окно открыто, CRM вместо кода присылает `X-Pairing-Proof:
v1.<ts>.<jti>.<hex>` — доказательство владения общим `PLATFORM_SSO_SECRET` (модель доверия: «владение общим секретом платформы =
право первого сопряжения»). Ключ = `HKDF-SHA256(PLATFORM_SSO_SECRET, info="rt-pairing-v1")`, подпись =
`HMAC-SHA256(ключ, "<ts>.<jti>.<sha256-hex тела>")`; окно метки 300 с, `jti` одноразов (10 минут), тело привязано хешем. Окно
закрывается НАВСЕГДА после первого успешного сопряжения любым способом (постоянный флаг ERP): дальше 409 `BOOTSTRAP_CLOSED`, только код
из ERP или «Обновить ключи». Тест-вектор — `packages/contracts/examples/pairing-bootstrap.json`.


`externals[]` в `/health` (M3-ERP-06) строится по журналам и счётчикам ERP без обращений к самим сервисам — ответ быстрый
(< 300 мс). Добавлено аддитивно (необязательное поле, новая операция); читатель CRM терпимый: нет поля — «нет данных»,
неизвестные `code` и `status` пропускаются. Выключенный из CRM сервис ERP не вызывается (курсы и ТН ВЭД — прогон
пропускается, почта — `FAILED` «выключено из CRM», модели — нейтральный отказ, S3 — запись отклоняется).

Передача (`/clients/handoff`): компания ищется по `crm_client_id`, затем по ИНН; сопоставление создаётся **до** сделки, поэтому
`request.created(source=crm)` и `invite.sent` доходят до CRM; ИНН чужого `crm_client_id` — 409 `INN_CONFLICT`; согласие хранится
в ERP как пришло. Стадия `stage` во всех ответах, событиях и инструментах MCP — одна функция сопоставления FSM ERP → шкала
контракта (`DealStage`, 11 кодов). Статусы строк поставки: ERP — `assembling…delivered`, клиент — `accepted`/`disputed`.

## 3. События (ERP → CRM)

> **Вебхук ERP → CRM заменён шиной `rt_bus` (волна 11, B3, ADR-0014).** ERP больше не шлёт `POST {CRM}/api/v1/integrations/erp/events`:
> `CRM_WEBHOOK_URL`, подпись событий `ERP_WEBHOOK_SECRET`, журнал `IntegrationWebhookEvent`, ретраи 1 мин … 24 ч, сигналы Django
> и проверка по `events.schema.json` удалены. Те же 22 события публикуются сервисами ERP в транзакции изменения как
> `uz.railtech.erp.<событие>.v1` (§9): тело события (без `version`, `event`, `occurred_at` — они в конверте) стало полем `data`
> конверта CloudEvents, схемы — `packages/contracts/events/erp/*.v1.json`. Доставка, подпись `X-RT-Signature`, окно 300 с,
> повторы, DLQ и «читатель терпимый» — §9.3–§9.4; публикация и приёмник ERP — §9.7. Подпись по `X-Event-Id`/`X-Timestamp`/
> `X-Signature` и ответ CRM «200 + `rejected`» прежней схемы больше не действуют. Файлы `events.schema.json` и
> `examples/events/*.json` удалены (B4: последних потребителей не осталось).

События ERP CRM принимает по шине `rt_bus` (§9): **`POST {CRM}/bus/v1/events`** — приёмник библиотеки (`rt_bus.fastapi.bus_router`).
Подпись пары `erp → crm` и окно 300 с (§9.3), идемпотентность по `id` конверта (повтор — 200 без действий), ответы 2xx/401/400/422
(§9.4), неизвестный тип и версия выше поддерживаемой — 200 и `skipped`. Приёмник работает только во внутренней сети: Caddy
`/bus/*` наружу не публикует. Прежнего вебхука `POST /api/v1/integrations/erp/events` нет (B4): ни маршрута, ни подписи
`X-Signature`/`X-Event-Id`, ни журнала `erp_incoming_events`, ни настройки `ERP_WEBHOOK_SIGN_LEGACY`.

Тип события — `uz.railtech.erp.<событие>.v1`, поле `data` конверта — прежнее тело без `version`, `event`, `occurred_at`
(время события — `time` конверта); схемы — `packages/contracts/events/erp/*.v1.json`, модели в CRM — `rt_contracts.events.erp`
(ручной копии нет). **Читатель терпимый** (L10): неизвестные поля в `data` игнорируются; `data` известного типа с неверным
значением или без обязательного поля — 422. Обработка в CRM — в очереди, в транзакции записи inbox (§9.8); ошибка — повтор
через 30 с, 2 мин, 10 мин, затем `failed` (видно в центре внешних сервисов, строка «События из ERP»). Код акцепта обрабатывается
inline и до БД не доходит (§9.2).

Поле `data`: `{erp_company_id, crm_client_id, deal{erp_deal_id, number, title, stage, amount, currency}, actor{type: system|staff|client, name?}, payload{...}}`;
`deal.amount` — сумма последнего КП, отправленного клиенту, или `null`.

| Событие | payload | Что делает CRM |
|---|---|---|
| `request.created` | `source: crm|cabinet|erp` | лента лида; зеркало сделки `open` |
| `deal.stage_changed` | `from, to, reason?` | лента; `external_stage` |
| `quote.sent` | `version, public_url, valid_until` | бот: «КП готово» с кнопками |
| `quote.viewed` / `quote.accepted` / `quote.rejected` | `version, reason?, erp_contact_id?, crm_contact_id?` | лента; при accepted — уведомление ответственному |
| `quote.acceptance_code_requested` | `version, erp_contact_id, crm_contact_id, code, expires_at` | бот присылает код контакту в Telegram; `code` не хранится и не логируется (Q-FIX22-1) |
| `contract.signed` | `by: client|company|both` | лента |
| `invoice.issued` / `invoice.paid` / `invoice.overdue` | `number, amount, due_date, link` | бот: «счёт выставлен»; напоминание — только ERP-письмо, бот дублирует по политике |
| `delivery.status_changed` / `delivery.eta_changed` | `line_summary, status, eta, tracking?` | бот: статус/сдвиг по политике «сообщать о сдвигах» |
| `delivery.line_accepted` / `delivery.line_disputed` | `line_no, title, status, remark?, decided_at` (`actor.type=client`; при `disputed` замечание обязательно) | лента; при `disputed` — уведомление ответственному (FIX-37) |
| `act.issued` / `act.accepted` / `act.returned` | `number, reason?` | бот: «акт ждёт подтверждения» |
| `deal.won` / `deal.lost` | `amount, lost_reason?` | зеркало сделки → `won/lost`; стадия лида не меняется (CRM ADR-0022) |
| `document.created` | `erp_document_id, kind, number` | индекс документов клиента в CRM (без файла) |
| `invite.sent` | `channels[]` | лента |

## 4. Portal API (Cabinet → ERP)

| Метод и путь | Назначение |
|---|---|
| `POST /auth/telegram` | `{init_data}` → проверка подписи токеном бота (срок ≤ 5 мин), поиск контакта по `telegram_user_id`; сессия (cookie HttpOnly) |
| `POST /auth/magic-link` | `{email}` → письмо со ссылкой (15 мин, одноразовая); ответ всегда 200 |
| `POST /auth/magic {token}` | обмен токена из ссылки входа на сессию; токен приходит во фрагменте ссылки `/auth/magic#token=…` и не попадает в журналы (FIX-20). `GET /auth/magic/{token}` снят в контракте 0.3.0 (FIX-25), маршрут отвечает 404 |
| `POST /auth/logout`, `GET /me` | сессия и контакт, компания, права (`can_act`) |
| `GET /requests`, `POST /requests` | мои запросы; новый запрос (строки свободным текстом + вложения) → `request.created(source=cabinet)` |
| `GET /quotes`, `GET /quotes/{id}`, `POST /quotes/{id}/request-code`, `POST /quotes/{id}/accept {code}`, `POST /quotes/{id}/reject {reason}` | КП; код акцепта (6 цифр, 15 мин) ERP шлёт контакту в Telegram или на e-mail по запросу — мастер-кода нет |
| `GET /contracts`, `POST /contracts/{id}/sign` | договоры |
| `GET /invoices`, `GET /acts`, `POST /acts/{id}/accept {upload_id?}`, `POST /acts/{id}/return {reason}` | счета и акты; при приёмке можно приложить скан подписанного акта (`Act.scan_document_id`) |
| `GET /deliveries`, `POST /deliveries/{id}/accept`, `POST /deliveries/{id}/dispute {reason}` | поставки по строкам заказа: проекция клиента (статус, ожидаемая дата, трек) и приёмка клиентом по строкам — `accepted` / `disputed` (BUSINESS §9, шаг 9) |
| `GET /documents`, `GET /documents/{id}/file` | документы (поток, аудит) |
| `GET /catalog`, `GET /catalog/{id}` | опубликованный слой с ценой и наличием (решение владельца: только здесь) |
| `GET /company`, `PUT /company`, `GET /team`, `POST /team/invite` | профиль и команда клиента |

Все ответы отфильтрованы по компании сессии; тест на каждый эндпоинт «чужая компания → 404».

Документы портала (FIX-23): `GET /documents` отдаёт только выпущенные документы клиентских видов (КП начиная с `sent`, договор,
счёт, акт, накладная, скан подписанного акта; черновики, КП до отправки и внутренние — никогда; видимость КП, договоров, счетов и актов та же, что в их списках); `document_id` / `pdf_document_id` в договорах, счетах,
актах и КП — id из этого списка или `null`; `GET /documents/{id}/file` — PDF потоком с записью аудита, пока не готов — 202 с
`Retry-After` и рендер в очереди. Приглашение коллеги (`POST /team/invite`) доставляется письмом; канал `telegram` — 422
`INVALID_CHANNEL`. Количество строки запроса (`quantity`) — десятичная строка больше нуля или `null`.

Сделка глазами клиента — `deal: {id, number, title}` в запросах, КП, договорах, счетах, актах, строках поставки и
документах (Q-16); `deal_id` рядом — устаревшее поле до перехода Cabinet (FIX-24). Коды `detail` — перечень `ErrorCode`
в контракте (Q-17); новый код добавляется в перечень в том же PR, что и код ERP. Категория каталога — название +
`category_id`, справочник — `GET /catalog/categories` (Q-15, вариант 2 закреплён).

Защита сессии в cookie (FIX-15): каждый `POST` и `PATCH` обязан нести `Idempotency-Key`
(иначе 400 `IDEMPOTENCY_KEY_REQUIRED`) и тело `application/json` (иначе 415 `UNSUPPORTED_MEDIA_TYPE`; исключение —
`multipart/form-data` на `/uploads`). Cookie — `HttpOnly`, `SameSite=Lax` (веб) или `SameSite=None; Secure` (Telegram
Mini App, настройка `PORTAL_COOKIE_SAMESITE`); CORS разрешает только origin Cabinet. Лимиты частоты — 429
`TOO_MANY_REQUESTS` + `Retry-After`: 120/мин на сессию, 10/мин на IP на вход без сессии, 10/мин на сессию на акцепт КП,
5 в час на e-mail для ссылки входа. Сессия архивной компании или контакта, ушедшего в другую компанию, — 401.

## 5. `erp-mcp` (для агента CRM)

Контекст — заголовок `X-Agent-Context` по образцу CRM SPEC §7.1: `{crm_client_id, erp_company_id,
mode: prospect|customer, language, iat, exp, jti}` с HMAC ключом из окружения. Типы строгие (целые — только
JSON-integer, не `true`), `iat` и `exp` обязательны, `exp − iat ≤ 60` и `exp ≤ now + 60`, `jti` — UUID v4,
одноразовый (приёмник помнит 10 минут; CRM выпускает новый контекст на каждый вызов инструмента).
Ошибка контекста — 401 `INVALID_AGENT_CONTEXT`, невалидные аргументы — 400 `INVALID_ARGUMENTS`, лимит
частоты по компании — 429. Инструменты не принимают идентификаторов клиента аргументами. Проекция клиента:
КП — только отправленные, принятые, отклонённые; количество поставки, которого ERP не хранит, — `null`;
каталог — только ключи опубликованного слоя. Подробности — `packages/contracts/mcp-tools.json`.

Реализация (FIX-36): `erp-mcp` — отдельный процесс на официальном SDK `mcp` (compose-сервис `erp-mcp`, `http://erp-mcp:8104/mcp/erp`, только внутри сети), а не маршрут Django; состав инструментов и схемы аргументов сервер читает из `packages/contracts/mcp-tools.json` при старте. Ошибка протокола (неизвестный метод) — ответ JSON-RPC с кодом ошибки, не 200 с результатом; ошибка инструмента — результат `isError` с общим кодом (`TOOL_NOT_AVAILABLE_IN_MODE`, `TOOL_EXECUTION_ERROR`, `INTERNAL_ERROR`). Режим `prospect` требует `erp_company_id = null`.

| Инструмент | Режим | Возвращает |
|---|---|---|
| `list_client_deals()` | customer | сделки с стадией и следующим шагом |
| `get_deal_status(erp_deal_id)` | customer | стадия, КП, счета, поставки (проекция), акты |
| `get_delivery_status(erp_deal_id)` | customer | строки: статус, ожидаемая дата, трек |
| `list_client_documents(kind?, date_from?, date_to?)` | customer | документы |
| `get_document_link(erp_document_id)` | customer | подписанный URL (бот отправляет файл) |
| `search_catalog(query, top_k)` | prospect, customer | prospect: название, описание, единица; customer: + цена, наличие, срок |
| `create_request(summary, lines[])` | customer | заявка в ERP от имени клиента (код решает, что это «запрос», модель лишь предлагает текст) |

Клиент CRM (M3-CRM-07, Q-FIX36-1 вариант 1; `apps/crm/backend/app/agents/erp_mcp.py`): контракт не менялся. SDK `mcp` не отдаёт код HTTP-ответа (на 401/400/429 вратаря исключение транспорта одно и то же), поэтому клиент берёт статус и `Retry-After` из `event_hooks` HTTP-клиента. Политика: 401 `INVALID_AGENT_CONTEXT` — контекст выпускается заново (новый `jti`) и вызов повторяется один раз; 429 — ждать `Retry-After` (не дольше 5 с и не больше двух раз), иначе отказ; 400 `INVALID_ARGUMENTS` и сетевой сбой — без повтора. Любой отказ — «ERP недоступен» для хода: бот отвечает «сейчас не могу проверить», не называет чисел и заводит запрос менеджеру. Контекст выпускается только в режиме `customer` (`erp_company_id` — из БД CRM по проверенной привязке Telegram, не от модели); лиду `erp-mcp` не открывается. Модели отданы пять инструментов (`list_client_deals`, `get_deal_status`, `get_delivery_status`, `list_client_documents`, `search_catalog`); `get_document_link` и `create_request` не отданы: файл отправляет код через docs-mcp, запрос оформляет `create_service_request` CRM.

## 6. SSO-токен сотрудника

JWT HS256, секрет `PLATFORM_SSO_SECRET` общий. Claims: `iss` (`crm`|`erp`), `aud` (целевая система),
`sub` (`crm_user_id`), `email`, `name`, `role`, `permissions[]`, `iat`, `exp` (= iat + 60 с), `jti`.
Приёмник: проверяет подпись, `aud`, срок, одноразовость `jti` (хранит 10 мин), находит пользователя по `sub`
(не создаёт), выдаёт свою сессию, пишет аудит. Доступом к ERP управляет CRM: `users.platform_access`
(`["crm"]` по умолчанию, `["crm","erp"]` — доступ выдан). Переключатель в шапке CRM и выдача токена
(`POST /api/v1/auth/sso/token`, иначе 403) — только при `erp` в `platform_access`; в шапке ERP — только у
пользователя с сопоставлением `CrmUserMapping`. Выдача доступа → провижининг в ERP, снятие → отзыв сессий
(очередь CRM, ошибки ERP — в центре внешних сервисов). Роль CRM → коды прав ERP: `docs/architecture/sso-token.md`.
Токен для EDS (`aud = eds`, обмен на токен доступа EDS, права — проекция `identity.user.*`) — §10.3 и `sso-token.md`,
«Токен сотрудника для EDS».

## 8. Платформа (SPA → BFF), ADR-0011

Единый интерфейс сотрудников `apps/platform` ходит только в свой BFF; BFF — в CRM и ERP по их API от имени сотрудника.
Контракты Платформы живут рядом с остальными и проверяются `make contracts`:

| Файл | Что | Кто читает |
|---|---|---|
| `openapi/platform-bff.yaml` | API BFF `/api/v1` (0.5.0 — поток подсказок SSE `/events/stream` (B5); 0.3.0 — роли-данные ADR-0012: `RoleRef`, `/admin/roles*` и предпросмотр «что произойдёт», повтор приглашения, передача лидов; 0.2.x — фаза P1: сессия, профиль, очередь, уведомления, поиск, Admin · Оргструктура); растёт минорными версиями до кода экранов | SPA (orval), BFF (тесты ответов по схеме) |
| `platform-rbac.yaml` (+ `.schema.json`) | **каталог возможностей версии 2** (ADR-0012, R-2): разделы с уровнями и отображением в права CRM (casbin) и ERP (`ErpPermission` шва), поля с ограничением, меню, виды работы «Моей очереди», две системные роли и шаблоны; роли — данные в CRM. Единственный каталог ролей в `packages/contracts` (тест в BFF); версия 1 удалена, её снимок — фикстура тестов миграции CRM | CRM (генератор `gen_platform_roles.py`, права и провижининг), BFF и SPA (генератор `apps/platform/scripts/gen_rbac.py`) |
| `client-statuses.yaml` (+ `.schema.json`) | статусы для клиента SPEC-v3 §2.5 на трёх языках | бот CRM, Cabinet, письма ERP, BFF |

Правила: словарь SPEC-v3 §2 — в именах полей и значениях; номера объектов — бизнес-номера; ошибки — `Error` с `source`;
агрегирующие ответы несут `sources`. Разрывы бэкендов, нужные экранам, меняют контракты CRM и ERP в том же PR, что и код
(`docs/architecture/integration-map.md` §7).

## 7. Версионирование

ADR-0016: у каждого файла контракта своя версия по semver; в пределах мажора — только добавления; ломающее — новый
мажор (`/v2` в пути API, `.v2` в типе события) и двойная публикация или обслуживание обоих на переходе; старый мажор
живёт ≥ 6 месяцев и ≥ 2 релизных поездов, помечается `Deprecation`/`Sunset`, после снятия — 410.

- **API** — префикс пространства (`/api/integration/v1`, `/api/portal/v1`, `/api/v1`); мажор в пути и в `info.version`
  совпадают. Ломающие изменения ловит `oasdiff` в `make contracts` и в CI (§7.1).
- **События шины** — мажор в типе и файле: `uz.railtech.<домен>.<сущность>.<действие>.v<N>` ↔
  `events/<домен>/<сущность>.<действие>.v<N>.json` (§9.6). В пределах `vN` — только новые необязательные поля и новые
  типы; всё прочее, в том числе расширение (новое значение enum, снятый `required`, ослабленные ограничения), — файл
  `v(N+1)`, издатель публикует оба типа, пока подписчики не перейдут. Машинная проверка — `scripts/events_compat.py` в
  `make contracts` и в CI (§9.6).
- **Старый вебхук §3** (поле `version` в теле) — в ERP снят (B3), приёмник CRM `/integrations/erp/events` удаляет B4.

### 7.1. Проверки машиной: `oasdiff` и `events_compat`

Обе проверки входят в `make contracts` (цели `openapi-compat` и `compat` в `packages/contracts/Makefile`), в `scripts/ci_local.sh
contracts` и в job «packages · contracts» CI. Сравнивают рабочее дерево с базой `CONTRACTS_BASE_REF` (по умолчанию
`origin/main`; CI и `ci_local.sh` перед этим скачивают её). Файла в базе нет — он новый, не ломающее. Красный результат
обойти нельзя: ни флагом, ни пропуском; можно только сделать изменение совместимым или поднять версию (до 1.0 — минорную,
с 1.0 — мажор).

| Что | Чем | Где правила |
|---|---|---|
| `openapi/*.yaml` — все файлы (с волны 12 их шесть, новый — `eds.yaml`), в том числе сгенерированные `erp-internal.yaml` и `crm.yaml` | `scripts/openapi_compat.py` → `oasdiff breaking`, закреплённая версия (одноразовый контейнер `tufin/oasdiff` с тегом и digest; свой бинарь — `OASDIFF_BIN`) | oasdiff: уровень ERR валит; WARN (например, удалено необязательное свойство запроса) печатается и не валит — решение лида, строже (`--fail-on WARN`) не включено |
| `events/**`, `bus/subscriptions.schema.json` | `scripts/events_compat.py` | §9.6: в пределах `vN` — только новые необязательные поля |

**Что считается ломающим в OpenAPI (ERR).** Удалён путь или операция (без `deprecated: true` и даты `x-sunset` не ближе 180 дней от пометки —
«api-path-removed-without-deprecation», «api-path-removed-before-sunset»); удалено обязательное поле ответа; новое обязательное поле
или параметр запроса; удалено значение enum запроса; сменён тип; ужесточено ограничение. Полный список
с идентификаторами — документация oasdiff («breaking changes»); идентификатор проверки печатается в квадратных скобках.

**Как читать ошибку.**

```
openapi-compat: ломающие изменения относительно origin/main (…):
  - erp-integration.yaml [request-property-became-required] POST /api/integration/v1/handoff: the request property `x` became required
events-compat: ломающие изменения относительно origin/main (L8 — только новым файлом v(N+1)):
  - events/erp/quote.sent.v1.json #/properties/status: сужение enum, убраны ["viewed"]
```

Строка называет файл, идентификатор проверки, метод и путь (для событий — путь внутри схемы) и что изменилось. Код выхода 2
— проверка невозможна (нет базы: `git fetch origin main`; нет Docker и `OASDIFF_BIN`; битый файл исключений) — это не зелёное.

**Что делать с ломающим изменением.**

1. Можно ли сделать совместимо — новое необязательное поле вместо переименования, новый путь рядом со старым? Так и делайте.
2. **До 1.0** (`info.version` файла в head — 0.x; решение архитектора 2026-10-23: семвер до 1.0 разрешает ломать минором)
   ломающее (ERR) допустимо, если минорная версия head выше минорной базы: `0.2.4 → 0.3.0` — зелёный; `0.2.4 → 0.2.5` и
   версия без изменений — красный, в сообщении подсказка «поднимите минорную версию (до 1.0) или новый мажор»;
   понижение версии — ошибка; переход `0.x → 1.0.0` с ломающим допустим (первая стабильная). Правило «контракт раньше
   кода, обе стороны в одном PR» (ORCHESTRATOR §3 п. 3) остаётся: поднятая минорная не отменяет синхронную правку
   потребителей. Схем событий это не касается — для них по-прежнему только `v(N+1)` (§9.6).
3. **С 1.0** — новый мажор: путь `/v2/…` (API) или файл `…v2.json` (событие), `info.version` файла OpenAPI получает мажор 2;
   старый мажор остаётся и обслуживается ≥ 6 месяцев (ADR-0016), помечается `deprecated: true` и `x-sunset: ГГГГ-ММ-ДД`
   (не раньше чем через 180 дней) в схеме. Поднятая версия и пути `/v2` сами по себе ломающее старого мажора **не
   оправдывают** (двойная публикация): ERR допустим только для операции, которая в базе уже помечена `deprecated`, и для
   путей, которых в базе не было; ломка живой операции старого мажора остаётся красной. Сначала PR с `deprecated` и
   `x-sunset`, потом — перенос.
4. Снятие старого мажора после срока — операции уже `deprecated` с `x-sunset` в прошлом: oasdiff такое удаление пропускает.
5. Одноразовый случай без потребителей (например, внутренний вебхук, у которого уже нет вызывающей стороны): запись в
   `packages/contracts/openapi-breaking-exceptions.yaml` — файл, идентификатор проверки, путь, **причина** и срок `until`;
   запись видна в diff и проходит ревью. Исключение с истёкшим сроком — красное; неиспользуемое — предупреждение
   (удалите, когда изменение уже в `origin/main`). Для схем событий исключений нет: ломающее — только `v(N+1)`.

**`crm.yaml`.** OpenAPI CRM — такой же файл контракта, как `erp-internal.yaml`: его **генерирует CRM** (`make -C apps/crm
openapi` → `packages/contracts/openapi/crm.yaml`; руками не правится), он же вход orval CRM, Cabinet (типы формы лида) и
BFF (модели ответов CRM, `make -C apps/platform crm-models`). Свежесть проверяет `crm-lint` (CI) и стадия `crm` в
`ci_local.sh`: после `make openapi` в git нет диффа. Линт — `redocly.crm.yaml` (правила, невыполнимые без правки
бэкенда, выключены только для него). Правило мажора то же, что для остальных файлов (в том числе «поднятый мажор не оправдывает ломку живой операции»): внутренний API CRM `/api/v1`
меняется совместимо либо через `deprecated` и срок, либо записью в файл исключений.

## 9. Шина rt_bus (события v2)

ADR-0014 (шина, правило «интеграции только через шину» — ORCHESTRATOR §3.14), ADR-0015 (владелец поля, домены),
ADR-0016 (версии); runbook `docs/runbooks/wave11-bus-v1.md`. Источник истины — файлы `packages/contracts/events/` и
`packages/contracts/bus/`; библиотека — `packages/rt-bus` (B1). Таблицы библиотеки: `rt_bus_outbox`, `rt_bus_delivery`,
`rt_bus_inbox`, `rt_bus_subscriber_state`.

### 9.1. Конверт (L1)

CloudEvents 1.0, structured mode, JSON; схема — `events/envelope.v1.json`.

| Атрибут | Обязателен | Значение |
|---|---|---|
| `specversion` | да | `"1.0"` |
| `id` | да | UUID события; ключ дедупликации inbox, заголовок `X-RT-Event-Id` |
| `source` | да | `rt://<сервис>`: `rt://crm`, `rt://erp`, `rt://eds`, `rt://platform-bff`; коннекторы — `rt://connector-<имя>` |
| `type` | да | `uz.railtech.<домен>.<сущность>.<действие>.v<N>` |
| `time` | да | момент события, RFC 3339 в UTC (`…Z`) |
| `datacontenttype` | да | `"application/json"` |
| `dataschema` | да | `rt://contracts/events/<домен>/<сущность>.<действие>/v<N>` |
| `tenant` | да | арендатор, v1 — `"railtech"` |
| `correlationid` | да | `X-Request-ID` исходного запроса или UUID; если нет — новый UUID |
| `data` | да | объект по схеме типа |
| `subject` | нет | объект события для человека (номер сделки, `client/42`), без персональных данных |
| `traceparent` | нет | W3C Trace Context |

Отправитель строгий: все обязательные атрибуты, `data` строго по схеме типа (`additionalProperties: false`). Читатель
терпимый: неизвестные атрибуты-расширения CloudEvents (имена `[a-z0-9]{1,20}`, значения — строка, число, булево)
допускаются и игнорируются; неизвестные поля в `data` подписчик игнорирует — при проверке `data` по своей копии схемы
ошибки `additionalProperties` не считаются отказом (модели `rt-contracts` для этого собраны с `extra="ignore"`), иначе
новое необязательное поле издателя ломало бы старого подписчика (L10). Других послаблений у приёмника нет: значение вне
enum, отсутствующее обязательное поле, нарушенное ограничение — 422 и `dead`; поэтому в `vN` разрешены только новые
необязательные поля (§9.6).

### 9.2. Типы и файлы (L2)

- Домены: `crm` (клиент, контакт, лид, обращения), `erp` (заявка, сделка, КП, договор, счёт, поставка, акт, документ),
  `eds`, `identity` (сотрудник; v1 живёт в CRM, `source` = `rt://crm`), `platform`. Сущность и действие — по одному
  сегменту snake_case: `uz.railtech.erp.delivery.line_accepted.v1`, `uz.railtech.erp.quote.acceptance_code_requested.v1`.
- Схема `data` типа — `events/<домен>/<сущность>.<действие>.v<N>.json` (JSON Schema 2020-12, `$id` повторяет путь:
  `https://railtech.uz/contracts/events/…`, поэтому относительные `$ref` разрешаются и по файлам, и по реестру `$id`).
  Общие определения домена — `events/<домен>/_defs.v<N>.json` (не тип).
- Пример полного конверта на каждый тип — `events/<домен>/examples/<сущность>.<действие>.v<N>.json`.
- AsyncAPI 3.0 — `events/asyncapi.yaml`: канал и сообщение на каждый тип, `payload` = конверт + `data` по файлу типа.
- Типы v1:

| Тип | Издатель → подписчики v1 | `data` |
|---|---|---|
| `uz.railtech.erp.<событие>.v1` — 22 события §3 | `rt://erp` → crm | прежнее тело §3 без `version`, `event`, `occurred_at`: `erp_company_id`, `crm_client_id`, `deal?`, `actor`, `payload` (определения — `erp/_defs.v1.json`) |
| `uz.railtech.crm.client.created.v1` / `client.updated.v1` | `rt://crm` → erp (`updated`) | снимок `client`: `crm_client_id`, `erp_company_id?`, `name`, `inn`, `segment`, `is_active`, `owner{crm_user_id, full_name}`, `updated_at`; `changed_fields?`; `actor` |
| `uz.railtech.crm.contact.created.v1` / `contact.updated.v1` | `rt://crm` → erp | снимок `contact`: `crm_contact_id`, `crm_client_id`, `erp_company_id?`, `full_name`, `position`, `phone_e164`, `email`, `telegram_user_id`, `is_primary`, `language?`, `preferred_channel?`, `updated_at` |
| `uz.railtech.crm.contact.deleted.v1` | `rt://crm` → erp | `crm_contact_id`, `crm_client_id`, `erp_company_id?`, `deleted_at`, `actor`; поздний `contact.created/updated` с `updated_at` ≤ `deleted_at` не применяется |
| `uz.railtech.crm.lead.created.v1` / `lead.updated.v1` / `lead.stage_changed.v1` | `rt://crm` → (Платформа, B5) | снимок `lead` без контактов и переписки: `crm_lead_id`, `crm_client_id?`, `display_name`, `company_name`, `stage`, `source`, `language`, `score`, `assigned_user`, `erp_request_id?`, `updated_at`; у `stage_changed` — `from`, `to`, `reason?` |
| `uz.railtech.crm.lead.erased.v1` | `rt://crm` → (Платформа, B5) | только `crm_lead_id`, `crm_client_id`, `erased_at`, `actor`: лид обезличен по запросу, **подписчики обязаны стереть свои копии ПДн по лиду** |
| `uz.railtech.crm.lead.merged.v1` | `rt://crm` → (Платформа, B5) | `lead` — снимок выжившего, `merged_lead_id` — поглощённый лид (в CRM его больше нет), `actor` |
| `uz.railtech.identity.user.created.v1` / `user.updated.v1` | `rt://crm` → platform-bff, eds | снимок `user`: `crm_user_id`, `email`, `full_name`, `position`, `language`, `is_active`, `platform_roles`, `systems`, `erp_role_codes?`, `permissions?` (`{eds: [код EDS]}`, код — строка по шаблону, не перечень; нет поля — доступа к EDS нет; волна 12 — §10.4), `updated_at` |
| `uz.railtech.identity.user.deactivated.v1` | `rt://crm` → platform-bff, eds | `crm_user_id`, `reason?`, `actor` |
| `uz.railtech.erp.quote.ready_for_approval.v1` | `rt://erp` → eds (platform-bff — подсказка) | КП готово к одобрению директором (EDS-03): `erp_company_id`, `crm_client_id` (может быть `null`), `deal`, `actor`, `payload` — снимок КП (`QuoteReadyForApproval`: номер, версия, сумма, валюта, себестоимость, маржа %, порог маржи резолюции, нужные и собранные визы — кто и когда, срок); **CRM не подписана** (себестоимость и маржа) |
| `uz.railtech.eds.*.v1` — 8 типов §10.2 | `rt://eds` → erp (`letter.resolved`, `letter.rejected`, `approval.decided`), platform-bff (все) | письма, документы реестра, маршруты согласования (`events/eds/_defs.v1.json`) |

События CRM и identity — снимки (event-carried state transfer): подписчик заменяет проекцию целиком по внешнему
идентификатору; снимок с `updated_at` старше применённого не применяется (доставка может прийти не по порядку). Только
поля, которыми владеет CRM (ADR-0015), и внешние идентификаторы; паролей, токенов, хэшей и одноразовых кодов нет
(проверяется тестом). Телефоны и e-mail в событиях CRM издатель нормализует до публикации (телефон — E.164,
e-mail — без пробелов, по формату `email`; схема проверяет формат): снимок строит `app/bus/snapshots.py` (B4), значение,
которое не приводится к виду схемы, не публикуется (`null`), а изменение из-за него не падает.

`payload.code` события `uz.railtech.erp.quote.acceptance_code_requested.v1` — секрет и для подписчика, и для издателя:
подписчик не пишет его в ленту, журналы, inbox и логи; у издателя в outbox и журнале доставок он хранится маской
(stash `rt_bus`, B1), открытое значение существует только в момент доставки.

### 9.3. Доставка и подпись (L3, L4)

`POST <endpoint подписчика>` (путь `/bus/v1/events`), `Content-Type: application/cloudevents+json`, тело — конверт.

| Заголовок | Значение |
|---|---|
| `X-RT-Publisher` | имя издателя: `crm`, `erp`, … |
| `X-RT-Event-Id` | `id` конверта |
| `X-RT-Timestamp` | UTC ISO 8601 момента попытки; при каждом повторе подпись пересчитывается |
| `X-RT-Signature` | `sha256=<hex HMAC-SHA256(secret, f"{X-RT-Event-Id}.{X-RT-Timestamp}.{raw_body}")>` |
| `traceparent` | из конверта, если есть |
| `X-Request-ID` | `correlationid` конверта |

Секрет пары «издатель → подписчик» — `RT_BUS_SECRET_<ИЗДАТЕЛЬ>_<ПОДПИСЧИК>` (верхний регистр, `-` → `_`; несколько через
запятую: первым подписывают, принимают любой — ротация без простоя). Сервис может подставить свой поставщик секретов
(сопряжение в БД). Приёмник: окно `|now − X-RT-Timestamp| ≤ 300 с`.

**Секрет пары CRM ↔ ERP без правки сопряжения (L12).** Поставщик секретов сервиса берёт `RT_BUS_SECRET_<ИЗДАТЕЛЬ>_<ПОДПИСЧИК>`
из окружения, если он задан; иначе выводит направленный секрет из секрета вебхуков сопряжения (каждого действующего — для
ротации; первый подписывает, принимается любой): `hex(HMAC-SHA256(webhook_secret, "rt-bus/v1/{издатель}->{подписчик}"))`,
например `"rt-bus/v1/erp->crm"` для событий ERP и `"rt-bus/v1/crm->erp"` для событий CRM. При ротации сопряжения ERP хранит и прежний секрет на переходный срок (как прежний токен CRM→ERP, по умолчанию 1 час): события,
подписанные им, принимаются, без 401. Секрет вебхуков по шине не ходит и в подписи не участвует, обе стороны считают пару сами; ERP берёт его из сопряжения (`ServiceCredential`, шифровано), иначе из
`ERP_WEBHOOK_SECRET`, CRM — из «Подключения → ERP». Остальным парам (platform-bff, заглушки, коннекторы) секрет нужен только в
окружении: пока его нет, доставка откладывается на 5 минут без засчитанной попытки и неподписанной не уходит.

### 9.4. Ответы приёмника и повтор

| Ответ приёмника | Когда | Отправитель |
|---|---|---|
| 2xx | принято; в т. ч. повтор `id` (без обработки) и `skipped` — неизвестный тип или версия выше поддерживаемой | доставлено |
| 401 | нет или неверная подпись, неизвестный издатель, вне окна 300 с | повтор по расписанию |
| 400 | не конверт, битый JSON; домен типа не принадлежит издателю пары (`foreign_type`, §9.5) | сразу `dead` |
| 422 | `data` известного типа не по схеме | сразу `dead` |

Отправитель: 400, 404, 410, 413, 415, 422 — сразу `dead` (повтор не поможет; «повторить» из журнала доступно);
остальное (401, 408, 409, 429, 5xx, сеть, таймаут) — повтор `30 с, 2 мин, 10 мин, 1 ч, 6 ч, 24 ч` с jitter, затем
`dead`; предохранитель на подписчика (5 ошибок подряд — пауза 5 мин).

### 9.5. Подписки (L5)

`packages/contracts/bus/subscriptions.yaml` (схема — `subscriptions.schema.json`); путь у сервисов — `RT_BUS_SUBSCRIPTIONS`.

```yaml
version: 1
subscribers:
  - name: crm                                   # уникальное имя подписчика
    endpoint: http://crm-api:8000/bus/v1/events # адрес во внутренней сети
    endpoint_env: RT_BUS_ENDPOINT_CRM           # необязательно: переопределение адреса из окружения
    enabled: true                               # необязательно, по умолчанию true; false — остановлен, события копятся в ожидании
    drop: false                                 # необязательно, по умолчанию false; с enabled: false — события за время остановки не копить
    types: ["uz.railtech.erp.*.v1"]             # маски fnmatch по полному типу, версия входит в маску
```

Издатель доставляет подписчику только свои события (по `source`) и не доставляет себе. Новый подписчик — строка в файле
и секрет пары в окружении, без правки кода сервисов. `enabled: false` останавливает отправку, но не теряет события (раскладка
создаёт доставки в ожидании, после `enabled: true` они уходят по порядку); `drop: true` вместе с `enabled: false` — для заглушек,
которым прошлое не нужно (строки не создаются; `rt-bus.md` §5).

**Принадлежность типа издателю.** Приёмник принимает событие, только если домен типа `uz.railtech.<домен>.…` принадлежит
издателю пары: `crm` — `crm` и `identity`, `erp` — `erp`, `eds` — `eds`, `platform-bff` — `platform` (таблица —
`BusConfig.publisher_domains`); иначе 400 `foreign_type` (`rt-bus.md` §6). Подписки v1: `crm` ← события ERP по сущностям (`act`, `contract`, `deal`, `delivery`, `document`, `invite`,
`invoice`, `request` — маской `uz.railtech.erp.<сущность>.*.v1`, КП — пять типов поимённо), то есть все типы ERP, кроме
`quote.ready_for_approval` (волна 12: себестоимость и маржа адресованы EDS); `erp` ← `uz.railtech.crm.client.updated.v1`,
`uz.railtech.crm.contact.*.v1` (ERP обновляет проекции компании и контактов, B4) и с волны 12 `uz.railtech.eds.letter.resolved.v1`,
`uz.railtech.eds.letter.rejected.v1`, `uz.railtech.eds.approval.decided.v1`; `eds` — §10.2.
`platform-bff` (B5) ← `uz.railtech.erp.*.v1`, `uz.railtech.crm.lead.*.v1`, `uz.railtech.identity.user.*.v1` и с волны 12
`uz.railtech.eds.*.v1` (обработчика в BFF пока нет — `skipped`; колокольчик и счётчики — этап D): BFF Платформы
превращает события в подсказки инвалидации SSE (`GET /api/v1/events/stream`, `platform-bff.yaml` 0.5.0), данных событий не
хранит; приёмник `http://platform-bff:8000/bus/v1/events` виден только внутри сети compose (Caddy `/bus/*` на домене
Платформы отдаёт 404); секреты пар — `RT_BUS_SECRET_ERP_PLATFORM_BFF`, `RT_BUS_SECRET_CRM_PLATFORM_BFF`, с волны 12
`RT_BUS_SECRET_EDS_PLATFORM_BFF` (только окружение).
Тест проверяет: маска совпадает хотя бы с одним типом, подписчик не подписан на свои события.

### 9.6. Совместимость (L8) и генерация (L6)

В пределах `vN` — только новые необязательные поля (в `properties`), новые типы (файлы) и новые определения `$defs`;
аннотации (`title`, `description`, `examples`, `x-*`) не сравниваются. Всё прочее — ломающее, в обе стороны:

- сужение: удаление или переименование поля, новое обязательное поле, сужение enum/const/`type`/`format`/`pattern`/
  границ, ужесточение `additionalProperties`, новые условия `allOf`/`if`/`not`, удаление файла типа или определения;
- расширение: новое значение enum или смена const, снятый `required`, расширенный `type` (в т. ч. `null`), ослабленные
  или снятые `minimum`/`maximum`/`minLength`/`maxLength`/`pattern`/`format`, новая ветка `oneOf`/`anyOf`, ослабленный
  `additionalProperties` — приёмник терпим только к лишним полям (L10), старый подписчик ответит 422 → `dead`.

Ломающее — только новым файлом `v(N+1)` с двойной публикацией на переходе.

`scripts/events_compat.py` сравнивает каждую схему `events/**` (кроме примеров) и `bus/subscriptions.schema.json` с
базой `CONTRACTS_BASE_REF` (по умолчанию `origin/main`; `git show <ref>:<путь>`, `$ref` разворачиваются в обеих
версиях); файла в базе нет — новое. Обхода нет: красный `make contracts` — значит нужен `v(N+1)`.

Модели — один генератор (`datamodel-code-generator`, Pydantic v2) → пакет `rt-contracts` в
`packages/contracts/generated/python` (`from rt_contracts.events import TYPES, Envelope`), ставится по пути. `rt-bus`
от него не зависит: проверяет `data` по JSON Schema из каталога `RT_BUS_CONTRACTS_DIR` (= `packages/contracts/events`).

### 9.7. ERP на шине (B3)

**Публикация.** События публикует сервисный слой ERP (`integration/services/events.py`, `document_events.py`) в той же
`transaction.atomic()`, что и изменение: откат транзакции — события нет; ошибка публикации (шина, кэш секрета, `data` не по
схеме типа) — исключение наружу и откат изменения; `except Exception` вокруг публикации нет (тест `test_bus_publish.py`).
Сигналов Django для событий нет. Где какое событие рождается:

| События | Сервис |
|---|---|
| `request.created` | заявка из Cabinet (`portal/services/requests.py`, `source=cabinet`), передача клиента из CRM (`integration/services/handoff.py` и инструмент `create_request` `erp-mcp`, `source=crm`), сделка сотрудника (`register_new_deal`, `source=erp`) |
| `deal.stage_changed`, `deal.won`, `deal.lost` | `transition_deal_stage` (смена стадии FSM; стадию контракта даёт `stages.py`) |
| `quote.sent`, `quote.viewed`, `quote.accepted`, `quote.rejected`, `quote.acceptance_code_requested` | отправка КП, просмотр публичной страницы, акцепт и отказ (`lifecycle_accept`, принудительное одобрение), код акцепта для Telegram (`portal/services/acceptance.py`) |
| `contract.signed` | `sign_contract_by_client` / `sign_contract_by_manager` |
| `invoice.issued`, `invoice.paid`, `invoice.overdue` | `issue_invoice`, `record_payment`, ежедневное напоминание об оплате (`send_payment_reminders`: одно `invoice.overdue` на просроченный счёт — статуса «просрочен» нет) |
| `act.issued`, `act.accepted`, `act.returned` | `generate_act` и `reissue_act`, `sign_act`, `reject_act` |
| `delivery.status_changed`, `delivery.eta_changed` | `ensure_fulfillment` (создание исполнения), `update_fulfillment_status` |
| `delivery.line_accepted`, `delivery.line_disputed` | `accept_delivery_line`, `dispute_delivery_line` |
| `document.created` | переход «не выпущен → выпущен» у КП, договора, счёта, акта, накладной, `GeneratedDocument` (правило `portal.services.documents.is_issued`) |
| `invite.sent` | `invite_contact_to_portal` |

Компания без `CrmClientMapping` событий не порождает. `correlationid` по умолчанию — `X-Request-ID` входящего запроса
(`RequestIDMiddleware` принимает только безопасную строку `A-Za-z0-9._-` до 128 знаков, иначе новый UUID), вне запроса
(Celery) — новый UUID. Код акцепта: в outbox маска `***`, значение — кэш Redis на 20 минут (`DjangoCacheStash`; в ERP запись идёт fail-closed — `integration.bus.FailClosedCacheStash`: кэш недоступен при публикации — `CacheUnavailable`, публикация и изменение откатываются, S0-2) до доставки;
истёк — доставка `dead` с `SECRET_EXPIRED`, клиент запрашивает код заново.

**Приёмник.** `POST /bus/v1/events` в `erp-backend` (JWT и сессия не нужны — подпись §9.3). Только внутри сети compose:
Caddy отдаёт `/bus` и `/bus/*` на ERP-домене 404, другие домены до `erp-backend` не доводят. Неверный `endpoint` у издателя
(404/410) уходит в `dead` сразу — runbook `docs/runbooks/rt-bus-erp.md`.

**Подписки ERP (L13).** `uz.railtech.crm.client.updated.v1`, `uz.railtech.crm.contact.{created,updated,deleted}.v1` —
проекции (`integration/services/crm_projections.py`, состояние применённых снимков — `CrmProjectionState`). ERP обновляет
только поля, которыми владеет CRM (ADR-0015 п. 5, ORCHESTRATOR §3 п. 16): название и ИНН компании (`Company.name`, `Company.inn`;
ИНН, занятый другой компанией ERP, не применяется — запись в журнал) и данные контакта (ФИО, должность, телефон, e-mail,
Telegram, язык, канал, признак основного); сегмент, `is_active` и ответственный полей в ERP не имеют. Финансы, прочие
реквизиты (адрес, банк, МФО — в схеме `client.*.v1` их нет) и права контакта в Cabinet (`can_act`) снимок не трогает; контакт,
созданный по событию, получает `can_act=false`. **В ERP название и ИНН компании, связанной с CRM, только для чтения:** API ERP
отклоняет их правку — internal `PATCH /accounts/companies/{id}/` 400, portal `PUT /company` 422, код
`REQUISITES_MANAGED_BY_CRM` (контракт портала 0.3.1; несвязанная компания правится как раньше). Снимок старее применённого
(`updated_at`; `deleted_at` у удаления) не применяется; `contact.deleted` **архивирует** контакт (`Contact.archived_at`, не
удаляет: каскад стёр бы коды акцепта КП — след): `can_act=false`, Telegram отвязан, сессии портала и ссылки входа сняты, вход и
приглашение закрыты, запись и связи остаются; более новый снимок возвращает контакт из архива (права — заново). Контакт,
переехавший к другому клиенту CRM, переносится в компанию нового клиента, если она известна ERP, иначе остаётся с записью в
журнал. Неизвестный клиент (нет `CrmClientMapping`) — пропуск с записью в журнал, не ошибка.

### 9.8. CRM на шине (B4)

**Публикация.** CRM — издатель `rt://crm`; события публикуются из сервисного слоя (`app/bus/events.py`) в транзакции изменения:
строка outbox пишется тем же `COMMIT`, что и данные; откат — события нет; вне транзакции и при ошибке схемы публикация бросает
исключение и изменение откатывается (никакого «сообщить потом»). Раскладку по подписчикам и доставку делает периодическая
задача `rt_bus.pump` (Procrastinate: сразу после коммита транзакции с публикацией и каждые 5 с как страховка).

| Тип | Когда публикуется (сервис) |
|---|---|
| `crm.client.created.v1` | клиент создан вручную, «Сделать клиентом» с новым клиентом (`ClientService`) |
| `crm.client.updated.v1` | изменены название, ИНН, сегмент, ответственный, активность; передача записала `erp_company_id` (`ClientService`, `ErpHandoffService`, обработчик событий ERP) |
| `crm.contact.created.v1` / `updated.v1` / `deleted.v1` | `ClientContactService` (в т. ч. `updated` для контактов, потерявших признак основного); основной контакт, созданный передачей в бэк-офис (`ErpHandoffService`); `deleted_at` — время базы |
| `crm.lead.created.v1` | лид из бота, формы сайта, «Новый лид» вручную |
| `crm.lead.stage_changed.v1` | любой переход стадии (`stages.transition`: менеджер, квалификатор, таймеры, склейка лидов); `reason` — только код из справочника CRM (`app/bus/reasons.py`), свободный текст остаётся в CRM |
| `crm.lead.updated.v1` | смена ответственного (в т. ч. массовая передача дел уходящего сотрудника — событие на каждый лид и клиента), привязка к клиенту, изменение `score`, заявка ERP (`erp_request_id`) |
| `crm.lead.erased.v1` | лид обезличен по `/delete` бота (без данных, только идентификаторы) |
| `crm.lead.merged.v1` | склейка Telegram-лида и лида с тем же телефоном |
| `identity.user.created.v1` / `updated.v1` / `deactivated.v1` | `UserService`: создание, смена имени, должности, языка, ролей Платформы и доступа, отключение; первый администратор; смена имени при входе по SSO (`SsoService`) |

Диалоги песочницы (`source = sandbox`) на шину не уходят. Контактов лида и переписки в событиях нет. `correlationid` — `X-Request-ID`
запроса (middleware `BusCorrelationMiddleware` после `CorrelationIdMiddleware`), для задач очереди — новый UUID; `traceparent` —
из заголовка запроса. Передача клиента в бэк-офис (`POST /clients/handoff`) остаётся REST (§2): синхронный вызов с ответом.

**Приёмник и обработчики.** События ERP (`erp_types()`: все `uz.railtech.erp.*.v1`, кроме кода акцепта и типов для EDS —
`NOT_FOR_CRM`, сейчас `quote.ready_for_approval`) — `ErpEventsService.apply` в транзакции inbox: зеркало
сделки (порядок по `time`), индекс документов, лента лида, служебные уведомления; сообщения Telegram записываются в
`erp_event_notices` и уходят после коммита (задача после обработки, сборщик раз в минуту, не позже суток; ушедшим адресатам
повторно не шлются). Клиента нет или `erp_company_id` не совпадает — ошибка обработки (повтор, затем `failed`).
`quote.acceptance_code_requested` — inline-обработчик: код доставляется в Telegram контакту из памяти запроса, в inbox лежит маска.

**Секрет пары `erp ↔ crm`** (L12): `RT_BUS_SECRET_ERP_CRM` / `RT_BUS_SECRET_CRM_ERP`, если заданы; иначе
`hex(HMAC-SHA256(webhook_secret, "rt-bus/v1/<издатель>-><подписчик>"))` из каждого действующего секрета вебхуков сопряжения
(текущего и предыдущего, «Подключения» → ERP); перечитывается при каждом приёме и доставке, поэтому смена и ротация действуют
без перезапуска. Прочие подписчики — только окружение. Эксплуатация (журнал, DLQ, повтор, метрики) — runbook `docs/runbooks/rt-bus-crm.md`.

## 10. EDS (волна 12, этап C1)

ADR-0015 (EDS — отдельный сервис, владелец реестра и маршрутов согласования), runbook
[`wave12-eds-c1.md`](../runbooks/wave12-eds-c1.md) §2 (нормативка), карта интеграции §7 (EDS-01, EDS-02, EDS-03). Источник
истины — файлы `packages/contracts/`; здесь — объяснение.

| Файл | Что | Версия |
|---|---|---|
| `openapi/eds.yaml` | API EDS `/api/v1` для BFF Платформы: обмен токена, `/me`, письма и резолюции, документы, маршруты согласования, реестр и экспорт, файлы с версиями; `/health` | 0.2.0 |
| `events/eds/*.v1.json` (+ `_defs.v1.json`, `examples/`) | 8 типов `uz.railtech.eds.*.v1` | v1 |
| `events/erp/quote.ready_for_approval.v1.json` | КП готово к одобрению (определения — `QuoteReadyForApproval`, `QuoteVisa` в `erp/_defs.v1.json`) | v1 |
| `events/identity/_defs.v1.json` | `User.permissions.eds` — необязательное, аддитивно в v1 | v1 |
| `bus/subscriptions.yaml` | подписчик `eds`; новые типы `erp` и `platform-bff`; `crm` без `quote.ready_for_approval` | — |
| `platform-rbac.yaml` (+ схема) | `backend.eds` разделов EDS → коды прав EDS | каталог v2 |

### 10.1. API (`eds.yaml` 0.2.0)

- **Кто зовёт.** Только BFF во внутренней сети (`http://eds-api:8000`); внешнего маршрута в Caddy нет, своей формы входа нет.
- **Пути.** `/api/v1/letters` (список, регистрация), `/letters/{letter_id}` (карточка), `…/resolution` `{text, assignees[{crm_user_id,
  zone}], due, min_margin_pct}`, `…/return` `{comment}`, `…/reject` `{reason}`, `…/submit` (повторная подача возвращённого); `/documents` (типы `memo`, `application`, `report`,
  `letter_out`; поля `ServiceMemo` SPEC-v3 §10.4), `/documents/{document_id}`, `…/submit`; `/approvals?mine=1`,
  `/approvals/{approval_id}` (шаги маршрута, чек-лист и снимок КП для показа), `…/decision` `{decision: approve|return|reject,
  comment, channels?}` — `comment` обязателен для `return` и `reject`; `/registry` (фильтры «Все документы» SPEC-v3 §7.3: тип,
  статус, период, ответственный, клиент, номер, поиск), `/registry/export` (xlsx, csv); `/files` (multipart, `version_of` — новая
  версия), `/files/{file_id}` (поток), `/files/{file_id}/versions`.
- **Идентификатор в пути — UUID объекта, не номер** (решение E1, принято лидом; для архитектора — уточнить формулировку runbook
  §2.3 `/letters/{no}`): номер реестра содержит `/`, `%2F` в пути прокси и фреймворки декодируют по-разному. Номер — поле объекта
  и фильтр `GET /api/v1/registry?number=ВХ-104/26`.
- **Входящее письмо.** Регистрация сразу даёт `awaiting_resolution` (`letter.registered`); резолюция → `resolved`, отказ →
  `rejected` (конечные); возврат → `returned`: письмо у регистратора (`letters.register`), повторная подача `POST …/submit` →
  снова `awaiting_resolution`, номер прежний. Таблица переходов — `info.description` файла.
- **Служебная записка, заявление, отчёт.** `draft` → `submit` → `on_approval`; директор `approve`: без суммы → `approved`, с суммой
  → `to_accountant`, затем бухгалтер (`payments.confirm`) `approve` → `paid`; `return` → `returned` (автор правит, новая версия,
  новый круг); `reject` → `rejected`. Исходящее письмо: `draft` → `submit` → `sent` (ИСХ). Таблица — `DocumentStatus`.
- **Архив без операции.** `document.archived` EDS публикует сама, когда маршрут документа завершён окончательно (одобрен на
  последнем шаге — `approved`/`paid` — или отклонён) и при отправке исходящего письма; документ сохраняет итоговый статус и
  получает `archived_at`.
- **Чек-лист КП** сверяет маржу с порогом **резолюции EDS** (владелец поля — EDS); `min_margin_pct` в
  `erp.quote.ready_for_approval` — снимок для показа. Снимок КП в `Approval.quote` повторяет `QuoteReadyForApproval` события.
  Строки визы и маржи — **блокирующие** (`ChecklistItem.blocking = true`): красная → `approve` 409 `checklist_not_green`.
  Строка «срок» — **предупреждение** (`blocking = false`, решение архитектора 2026-10-26, C1-G-1): КП, готовое позже срока
  резолюции, директор одобряет, осознанно приняв опоздание; маршрут получает `Approval.approved_late = true`, журнал —
  строку `approval.approved_late`, событие `approval.decided` — `approved_late: true`. Срок резолюции раньше сегодняшней
  даты (`Asia/Tashkent`) — 422 (`details.fields.due`). С 0.2.0 (аддитивно).
- **Отправитель письма** (`IncomingLetterSender`, 0.2.0): `LetterSender` (название, ИНН) и контактное лицо (`contact`);
  письмо по заявке ERP берёт их из `erp.request.created` (`payload.company_name`, `company_inn`, `contact_name`), менеджера —
  из `payload.manager_crm_user_id` (C1-G-7). Адресат исходящего письма и клиент в реестре — `LetterSender`, как раньше.
- **Номера** (§2.1 runbook): `ВХ-NNN/ГГ`, `ИСХ-NNN/ГГ` (одобрение КП, отправка письма), `СЗ-ГГГГ/NNN`, `ЗЯ-ГГГГ/NNN`, `ОТ-ГГГГ/NNN`;
  счётчик на тип и год (`Asia/Tashkent`) под `SELECT … FOR UPDATE`, без пропусков; номер не возвращается. ЗВ/ПР/КП/ДОГ/СЧ/АКТ —
  у ERP, EDS хранит ссылки (`ErpLinks`).
- **Ошибки** — `Error {code, message, source: "eds", details}`, как у BFF (§8); коды — в `info.description` файла.
- **Пагинация** — `cursor` + `limit` (1–100), ответ `{items, next_cursor}`.
- **Право на каждую операцию** — расширение `x-rt-permissions`: список кодов EDS, любого из которых достаточно (пустой — любой
  активный сотрудник проекции, только `/me`). Публичны только `/health` и обмен токена. Тест контракта
  (`tests/test_platform_rbac.py`) проверяет, что расширение есть у каждой защищённой операции; сервис сверяет с ним свою
  таблицу маршрутов.

### 10.2. События и подписки

| Тип | Когда | Подписчики v1 |
|---|---|---|
| `uz.railtech.eds.letter.registered.v1` | письмо получило ВХ-номер: вручную или по `erp.request.created` | platform-bff |
| `uz.railtech.eds.letter.resolved.v1` | резолюция: исполнители (`crm_user_id`, `zone`: `goods`, `services`, `payment_terms`), срок, `min_margin_pct`, `links` (`erp_request_id`, `erp_deal_id`, `deal_number`) | erp (задание расчёта, стадия `CALCULATION` — FSM ERP `CALCULATING`; §10.6), platform-bff |
| `uz.railtech.eds.letter.returned.v1` | возврат регистратору с комментарием (повторная подача — `POST …/submit`, без события) | platform-bff |
| `uz.railtech.eds.letter.rejected.v1` | отказ с причиной | erp (сделка → `LOST` с причиной), platform-bff |
| `uz.railtech.eds.document.registered.v1` | номер документа (СЗ, ЗЯ, ОТ — при создании; ИСХ — при отправке письма) | platform-bff |
| `uz.railtech.eds.document.archived.v1` | автоматически: маршрут документа завершён окончательно (одобрен на последнем шаге или отклонён), исходящее письмо отправлено | platform-bff |
| `uz.railtech.eds.approval.requested.v1` | шаг стал текущим: маршрут (круг) открыт — первый шаг; решение передало маршрут дальше — следующий шаг (`step.index`); кто решает | platform-bff |
| `uz.railtech.eds.approval.decided.v1` | решение на шаге: `decision`, `comment`, `route_status`, для одобренного КП — `outgoing_number` (ИСХ), `channels` и `approved_late` (одобрено с опозданием; необязательное, с 2026-10-26) | erp (EDS-03 для `object.kind = quote` и закрытого маршрута), platform-bff |

ERP публикует `uz.railtech.erp.quote.ready_for_approval.v1` (EDS-03) — EDS открывает маршрут «КП» с чек-листом. Подписка `eds` ←
`uz.railtech.identity.user.*.v1` (проекция сотрудников с `permissions.eds`), `uz.railtech.erp.request.created.v1` (письмо по
заявке; отправитель и менеджер — необязательные поля `payload` с 2026-10-26, C1-G-7: `company_name`, `company_inn`,
`contact_name`, `manager_crm_user_id`; ERP берёт менеджера из ответственного передачи CRM, иначе из ответственного сделки с
сопоставлением CRM), `uz.railtech.erp.quote.ready_for_approval.v1`. Объект маршрута для ERP — `approval.object` (`erp_quote_id`,
`quote_version`, `erp_deal_id`): решение применяется к той версии КП, для которой открыт маршрут. Секреты пар (только окружение):
`RT_BUS_SECRET_CRM_EDS`, `RT_BUS_SECRET_ERP_EDS`, `RT_BUS_SECRET_EDS_ERP`, `RT_BUS_SECRET_EDS_PLATFORM_BFF`.

ERP применяет события EDS (E5) — §10.6.

### 10.3. Вход и права

Сотрудник — только через BFF: CRM выдаёт токен сотрудника `aud = eds` (`POST /api/v1/auth/sso/token {"aud": "eds"}`, только
активному с непустым `permissions.eds`, иначе 403 `eds_access_denied`), EDS обменивает его на свой токен доступа
(`iss = eds`, `aud = eds-api`, 15 минут, без refresh) — `sso-token.md`, «Токен сотрудника для EDS» (решение лида L-C1-1).
Обмен проверяет `iss = crm` и `aud = eds`; API принимает только `aud = eds-api`. Право проверяется по проекции сотрудников на
момент запроса; отзыв действует сразу. Нет поля `permissions` (или `permissions.eds`) в снимке сотрудника — доступа к EDS нет
(CRM до задачи E4 публикует снимок без поля).

### 10.4. Права EDS из каталога ролей

Коды v1 (`EdsPermission`): `letters.read`, `letters.register`, `letters.resolve`, `memos.create`, `memos.approve`,
`approvals.decide`, `registry.read`, `registry.export`, `payments.confirm` (решение архитектора: шаг «бухгалтер» служебной
записки с суммой) и с eds.yaml 0.3.0 `bus.manage` — журнал шины EDS в Admin · Журнал интеграций (W13-A2). Перечень — в `eds.yaml` и схеме каталога; в событиях шины (`identity`, `eds`) код — строка по шаблону
`^[a-z_]+\.[a-z_]+$`, не перечень, поэтому новый код не ломает события v1. CRM вычисляет их из ролей Платформы так же, как права ERP (объединение по
разделам; `full` включает `read`), и публикует в `identity.user.*` как `user.permissions.eds`. Отображение (`platform-rbac.yaml`,
`backend.eds`):

| Раздел | `read` | `full` |
|---|---|---|
| `eds.inbox` | `letters.read`, `registry.read` | + `letters.register`, `letters.resolve` |
| `eds.drafts` | — | `approvals.decide` |
| `eds.projects` | `registry.read` | `registry.read` |
| `eds.payments` | `registry.read` | `registry.read`, `registry.export` (ERP `data.export` этого раздела), `payments.confirm` |
| `eds.memo.create` | — | `memos.create` |
| `eds.memo.approve` | — | `memos.approve` |
| `admin` | — | `bus.manage` (журнал шины, W13-A2) |

Итог по ролям (тест `packages/contracts/tests/test_platform_rbac.py`): «Директор» — все девять кодов документов (без
`bus.manage`: у директора `admin` — только чтение); «Менеджер» — `letters.read`,
`registry.read`, `memos.create`; «Снабженец», «Гл. инженер» — `registry.read`, `memos.create`; «Бухгалтер» — `letters.read`,
`registry.read`, `registry.export`, `payments.confirm`, `memos.create`; «Менеджер и бухгалтер» гейта R-3 (лиды и «Счета и
оплаты» — полный доступ) — `registry.read`, `registry.export`, `payments.confirm`; «Администратор» — `memos.create` (свои
служебные записки; писем, реестра и маршрутов не видит — R3-D-2; допустимо, решено архитектором) и `bus.manage` (метаданные
доставок шины без тел событий). Шаг «бухгалтер» маршрута
служебной записки с суммой решает любой с `payments.confirm` (решение архитектора; `registry.export` для этого не используется).

### 10.5. Версии

`eds.yaml` до 1.0 растёт минорными версиями (§7.1); события — правила §9.6 (`v(N+1)` для ломающего). Поле
`identity.User.permissions` и тип `erp.quote.ready_for_approval.v1` — аддитивные изменения v1. Коды прав в событиях — шаблон,
а не перечень: новый код EDS — не новая версия событий.

### 10.6. ERP ↔ EDS (E5): как ERP применяет события и когда публикует КП

- **`eds.letter.resolved` (EDS-01).** Сделка — `links.erp_deal_id`, иначе `links.erp_request_id` (заявка ERP и есть сделка).
  ERP заводит задание расчёта (`CalcTask`, одно на `eds_letter_id`; новая резолюция того же письма его обновляет):
  исполнители (`crm_user_id` → пользователь ERP через `CrmUserMapping`, зона `goods`/`services`/`payment_terms`), срок,
  `min_margin_pct` — проекция резолюции, владелец полей — EDS. Сделка переходит в FSM `CALCULATING` (`quoting` контракта)
  обычным переходом (из `DRAFT` — через `SOURCING`, как отправка КП), событие `deal.stage_changed` — в той же транзакции.
  Неизвестный сотрудник — исполнитель без пользователя и запись WARNING в журнале сделки; нет ссылки или сделки — пропуск с
  записью в журнал; сделка дальше расчёта (КП отправлено, договор) — стадия не меняется, запись в журнал.
  Резолюция не переоткрывает закрытую сделку (`CLOSED_LOST`, `CLOSED_WON`) — WARNING в журнал. События не по порядку: более
  старая резолюция (`resolution.decided_at` раньше действующей) после новой не применяется — WARNING в журнал.
- **`eds.letter.rejected`.** Сделка → `CLOSED_LOST` с причиной (`deal.lost` несёт `lost_reason` из события) — только до
  отправки КП клиенту (FSM до `CALCULATING` включительно); позже (КП у клиента, договор, сделка выиграна) — WARNING в журнал,
  сделка не закрывается. Уже проиграна — без изменений.
- **Визы КП в ERP** (решение лида по ревью E5, Б1): шаги виз строятся из исполнителей задания расчёта в зонах `goods` и
  `services`, у которых есть пользователь ERP (исполнитель, заведённый позже резолюции, привязывается при отправке по
  `CrmUserMapping`); визирует назначенный исполнитель шага — право `quote.review` для визы не нужно. Директор и прочие
  держатели `quote.review` шагов виз в ERP не получают — одобрение директора только в EDS. Автор КП, если он исполнитель
  зоны, визирует её самой отправкой. КП без задания расчёта виз не ждёт (`required_zones` пусто). Визирует исполнитель с
  действующим членством в компании-владельце КП; зона резолюции, которую визировать некому (исполнитель не заведён в ERP или
  не в компании), блокирует отправку на согласование — 409 `VISA_ASSIGNEE_NOT_IN_ERP` (в EDS не уходит КП с заведомо красным
  чек-листом). Превью цепочки только читает и привязку исполнителя не записывает.
- **`erp.quote.ready_for_approval` (EDS-03).** Публикуется в транзакции, когда виз больше не ждём: последняя виза исполнителя
  или отправка на согласование без шагов виз. КП получает номер ERP (КП-…) при передаче директору, а не при отправке клиенту
  (номер не меняется при отправке; у отклонённых директором КП пропуски номеров допустимы — счётчик ERP без возврата), `version`
  события — редакция `Quote.eds_revision` (растёт с каждой отправкой директору, в том числе после возврата); `visas` — визы
  по зонам задания (в типичном сценарии — `goods` автора-снабженца и `services` инженера, покрывают `required_zones`);
  `required_zones`, `min_margin_pct`, `due`, `eds_letter_id` — из задания расчёта. После передачи директору автор КП в ERP
  не отзывает (409 `QUOTE_AWAITING_DIRECTOR`; событие отзыва для EDS — вопрос Q-C1-E5-1). Компания без клиента CRM — `crm_client_id: null`; КП без
  компании клиента (черновик-калькулятор) на согласование не уходит (`QUOTE_CLIENT_REQUIRED`).
- **`eds.approval.decided` по КП** (закрытый маршрут; решения по документам EDS ERP не касаются): `approve` — ИСХ-номер
  (`outgoing_number`) и `channels` на КП, статус «Готово к отправке» (отправка клиенту разблокирована; `approved_late` —
  отметка «одобрено с опозданием» в журнале КП); `return` — черновик с
  комментарием директора; `reject` — КП отклонено (статус `REJECTED`; от отказа клиента его отличает
  `Quote.director_decision = reject` — КП клиенту не уходило, в портале и в сумме сделки его нет). Решение по `quote_version`, отличной от текущей редакции, или по КП, которое
  уже не ждёт одобрения, не применяется — запись в журнал КП; повтор применённого решения — без изменений.
- **Права.** Своей цепочки одобрения директором у ERP нет: код финального утверждения КП удалён из `ErpPermission`
  (`erp-integration.yaml` 0.7.0, ломающее до 1.0 — минором, ADR-0016) и из `platform-rbac.yaml` (`eds.drafts` → ERP
  `quote.review`); данные ролей ERP чистят миграции `accounts/0010`, `integration/0010`. **Отправить одобренное КП клиенту**
  (`quote.send`, `POST /crm/quotes/{id}/send-to-client/`) могут менеджер заявки и директор: с 2026-10-26 код отделён от
  `eds.drafts` и дан разделу `crm.clients` full (решение архитектора, C1-G-4); снабженец-автор, гл. инженер и бухгалтер — 403.
  Объектной проверки «своя заявка» нет: в пути C1 у сделки из CRM нет ответственного в ERP.
- **API КП** (`erp-internal.yaml`, `QuoteSerializer`, C1-G-5): `outgoing_number`, `director_decision`, `director_comment`,
  `send_channels` — только чтение; решение, комментарий и каналы видят сотрудники своей компании, не покупатель.
