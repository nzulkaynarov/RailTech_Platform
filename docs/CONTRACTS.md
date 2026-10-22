# CONTRACTS — шов между CRM и ERP (и портальный вход Cabinet)

Версия 0 · 2026-10-13 · Источник истины — файлы в `packages/contracts/` (OpenAPI и JSON-схемы);
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

Contract-first действует для `portal`, `integration`, событий и `erp-mcp`: их файлы в `packages/contracts` пишутся руками и сверяются с кодом сторожами ERP. **`internal` — наоборот: `openapi/erp-internal.yaml` генерируется из drf-spectacular (срез `/api/v1/` выгрузки `apps/erp/backend/schema.json`; `make -C apps/erp openapi`) и руками не правится.** Дрейф кода и выгрузки ловит `make -C apps/erp openapi-check` (`make ci-local erp`, шаг CI «ERP · check»). Типы ERP SPA строятся из `backend/schema.json`, отдельного `generated/erp-internal.d.ts` нет.

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
(Fernet, ключ из `SECRET_KEY`); аутентификация integration и подпись вебхуков берут их оттуда, `.env` — только пока в базе
пусто. «Обновить ключи» — `POST /pairing/rotate`: ERP принимает новую тройку по действующему токену, прежний токен CRM→ERP действует
ещё переходный срок (по умолчанию 1 час), прежний секрет вебхуков CRM принимает наравне с новым. Читатель терпимый: новые поля
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

> **Устаревает (волна 11, ADR-0014).** Вебхук ниже заменяется шиной `rt_bus` (§9): те же 22 события публикуются как
> `uz.railtech.erp.<событие>.v1`, тело события (без `version`, `event`, `occurred_at`) становится полем `data` конверта
> CloudEvents, схемы — `packages/contracts/events/erp/*.v1.json`. `events.schema.json` и `examples/events/*.json`
> остаются до перехода сторон: удаляют B3 (ERP, монтирование в `infra/deploy`) и B4 (ручная копия CRM и сами файлы).

`POST {CRM}/api/v1/integrations/erp/events`. Заголовки: `X-Event-Id` (UUID), `X-Event-Type`,
`X-Timestamp` (UTC ISO 8601), `X-Signature: sha256=<HMAC(WEBHOOK_SECRET, f"{X-Event-Id}.{X-Timestamp}.{body}")>` — схема v2
(FIX-61, Q-FIX35-2); переход: CRM принимает и старую подпись только тела, пока `ERP_WEBHOOK_SIGN_LEGACY=true`, затем
настройка выключается. ERP при ретрае подписывает заново с актуальным `X-Timestamp`; `occurred_at` в теле — время события.
CRM отвечает 200 быстро, обрабатывает асинхронно; повтор с тем же `X-Event-Id` — 200 без действий. Неверная подпись —
401. **Постоянный отказ — 200 и запись `rejected` в журнале CRM** (Q-FIX33-1): `|now − X-Timestamp| > 300 с`, повтор того же
тела под другим `X-Event-Id`, сломанный JSON, тело не по схеме известного события — ретраи не помогут. **Читатель
терпимый** (Q-FIX35-4): неизвестные поля игнорируются, неизвестный `event` — 200 и `skipped`; отправитель соблюдает схему
строго; новое необязательное поле или новый тип события не меняют `version` и не требуют одновременной выкладки CRM.
Ретраи ERP: 1, 5, 30 мин, 2, 6, 24 ч; после — журнал с ручным повтором.

Тело: `{event, occurred_at, erp_company_id, crm_client_id, deal{erp_deal_id, number, title, stage, amount, currency}, actor{type: system|staff|client, name?}, payload{...}}`;
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
(очередь CRM, ошибки ERP — в центре внешних сервисов). Роль CRM → коды прав ERP: `packages/contracts/sso-token.md`.

## 8. Платформа (SPA → BFF), ADR-0011

Единый интерфейс сотрудников `apps/platform` ходит только в свой BFF; BFF — в CRM и ERP по их API от имени сотрудника.
Контракты Платформы живут рядом с остальными и проверяются `make contracts`:

| Файл | Что | Кто читает |
|---|---|---|
| `openapi/platform-bff.yaml` | API BFF `/api/v1` (0.2.0 — фаза P1: сессия и смена пароля, профиль, очередь, уведомления, поиск, Admin · Оргструктура); растёт минорными версиями до кода экранов | SPA (orval), BFF (тесты ответов по схеме) |
| `platform-rbac.yaml` (+ `.schema.json`) | роли Платформы, ролевая матрица SPEC-v3 §4.2, поля с ограничением, карта ролей в CRM и ERP (`role_codes` шва 0.5.0) | BFF и SPA генерируют проверки; CRM-01 — провижининг |
| `client-statuses.yaml` (+ `.schema.json`) | статусы для клиента SPEC-v3 §2.5 на трёх языках | бот CRM, Cabinet, письма ERP, BFF |

Правила: словарь SPEC-v3 §2 — в именах полей и значениях; номера объектов — бизнес-номера; ошибки — `Error` с `source`;
агрегирующие ответы несут `sources`. Разрывы бэкендов, нужные экранам, меняют контракты CRM и ERP в том же PR, что и код
(`apps/platform/docs/04-integration-map.md` §7).

## 7. Версионирование

ADR-0016: у каждого файла контракта своя версия по semver; в пределах мажора — только добавления; ломающее — новый
мажор (`/v2` в пути API, `.v2` в типе события) и двойная публикация или обслуживание обоих на переходе; старый мажор
живёт ≥ 6 месяцев и ≥ 2 релизных поездов, помечается `Deprecation`/`Sunset`, после снятия — 410.

- **API** — префикс пространства (`/api/integration/v1`, `/api/portal/v1`, `/api/v1`). Проверка ломающих изменений
  OpenAPI (`oasdiff` против `origin/main`) — задача B6.
- **События шины** — мажор в типе и файле: `uz.railtech.<домен>.<сущность>.<действие>.v<N>` ↔
  `events/<домен>/<сущность>.<действие>.v<N>.json` (§9.6). В пределах `vN` — новое необязательное поле, новый тип,
  расширение enum; иначе — файл `v(N+1)`, издатель публикует оба типа, пока подписчики не перейдут. Машинная проверка —
  `scripts/events_compat.py` в `make contracts` и в CI (§9.6).
- **Старый вебхук §3** (поле `version` в теле) — до удаления в B3/B4 не меняется.

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
новое необязательное поле издателя ломало бы старого подписчика.

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
| `uz.railtech.crm.contact.deleted.v1` | `rt://crm` → erp | `crm_contact_id`, `crm_client_id`, `erp_company_id?`, `actor` |
| `uz.railtech.crm.lead.created.v1` / `lead.updated.v1` / `lead.stage_changed.v1` | `rt://crm` → (Платформа, B5) | снимок `lead` без контактов и переписки: `crm_lead_id`, `crm_client_id?`, `display_name`, `company_name`, `stage`, `source`, `language`, `score`, `assigned_user`, `erp_request_id?`, `updated_at`; у `stage_changed` — `from`, `to`, `reason?` |
| `uz.railtech.identity.user.created.v1` / `user.updated.v1` | `rt://crm` → (ERP, Платформа — позже) | снимок `user`: `crm_user_id`, `email`, `full_name`, `position`, `language`, `is_active`, `platform_roles`, `systems`, `erp_role_codes?`, `updated_at` |
| `uz.railtech.identity.user.deactivated.v1` | `rt://crm` → (ERP, Платформа — позже) | `crm_user_id`, `reason?`, `actor` |

События CRM и identity — снимки (event-carried state transfer): подписчик заменяет проекцию целиком по внешнему
идентификатору; снимок с `updated_at` старше применённого не применяется (доставка может прийти не по порядку). Только
поля, которыми владеет CRM (ADR-0015), и внешние идентификаторы; паролей, токенов, хэшей и одноразовых кодов нет
(проверяется тестом). `payload.code` события `uz.railtech.erp.quote.acceptance_code_requested.v1` — секрет: подписчик
не пишет его в ленту, журналы, inbox и логи.

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

### 9.4. Ответы приёмника и повтор

| Ответ приёмника | Когда | Отправитель |
|---|---|---|
| 2xx | принято; в т. ч. повтор `id` (без обработки) и `skipped` — неизвестный тип или версия выше поддерживаемой | доставлено |
| 401 | нет или неверная подпись, неизвестный издатель, вне окна 300 с | повтор по расписанию |
| 400 | не конверт, битый JSON | сразу `dead` |
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
    enabled: true                               # необязательно, по умолчанию true
    types: ["uz.railtech.erp.*.v1"]             # маски fnmatch по полному типу, версия входит в маску
```

Издатель доставляет подписчику только свои события (по `source`) и не доставляет себе. Новый подписчик — строка в файле
и секрет пары в окружении, без правки кода сервисов. Подписки v1: `crm` ← `uz.railtech.erp.*.v1`; `erp` ←
`uz.railtech.crm.client.updated.v1`, `uz.railtech.crm.contact.*.v1` (ERP обновляет проекции компании и контактов, B4).
`platform-bff` добавляется в B5. Тест проверяет: маска совпадает хотя бы с одним типом, подписчик не подписан на свои
события.

### 9.6. Совместимость (L8) и генерация (L6)

В пределах `vN` — только добавление необязательных полей и новых типов (и расширение: enum, `type` до надмножества,
снятие ограничений). Ломающее: удаление или переименование поля, смена типа, новое обязательное поле, сужение
enum/const/формата/шаблона/границ, ужесточение `additionalProperties`, удаление файла типа или определения `$defs`, новые
условия `allOf`/`if`/`not`. Ломающее — только новым файлом `v(N+1)` с двойной публикацией на переходе.

`scripts/events_compat.py` сравнивает каждую схему `events/**` (кроме примеров) и `bus/subscriptions.schema.json` с
базой `CONTRACTS_BASE_REF` (по умолчанию `origin/main`; `git show <ref>:<путь>`, `$ref` разворачиваются в обеих
версиях); файла в базе нет — новое. Обхода нет: красный `make contracts` — значит нужен `v(N+1)`.

Модели — один генератор (`datamodel-code-generator`, Pydantic v2) → пакет `rt-contracts` в
`packages/contracts/generated/python` (`from rt_contracts.events import TYPES, Envelope`), ставится по пути. `rt-bus`
от него не зависит: проверяет `data` по JSON Schema из каталога `RT_BUS_CONTRACTS_DIR` (= `packages/contracts/events`).
