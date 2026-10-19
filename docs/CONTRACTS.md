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
  `CRM→ERP`, `ERP→CRM`), токены — секреты окружения, ротация без простоя (два активных).
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

## 2. Integration API (CRM → ERP)

| Метод и путь | Назначение | Тело / ответ (главное) |
|---|---|---|
| `POST /clients/handoff` | передача клиента из CRM | вход: `crm_client_id`, `crm_lead_id?`, `company{name, inn?, segment?, language}`, `contacts[{crm_contact_id, name, phone?, email?, telegram_user_id?, language, is_primary, preferred_channel}]`, `need{summary, product_interest[], attachments[]?}`, `owner{crm_user_id, name}`, `consent{given_at, version}`, `create_request: bool`, `invite{channels: [telegram, email]}`. Ответ: `erp_company_id`, `erp_request_id?`, `invite{sent_via[], cabinet_url}`. Идемпотентно по `crm_client_id` |
| `PUT /contacts/{crm_contact_id}` | обновление контакта / Telegram-привязки | те же поля контакта |
| `GET /companies/{erp_company_id}/summary` | карточка клиента для CRM | открытые сделки, последний документ, дебиторка, ближайшая поставка |
| `GET /companies/{erp_company_id}/deals` | список сделок | `[{erp_deal_id, number, title, stage, amount, currency, next_step, updated_at}]` |
| `GET /deals/{erp_deal_id}` | сделка | стадия, КП (версия, статус, публичная ссылка), договор, счета, поставки (проекция клиента), акты |
| `GET /deals/{erp_deal_id}/documents` | документы сделки | `[{erp_document_id, kind, number, date, title, status}]` |
| `GET /documents/{erp_document_id}/link` | ссылка на файл | подписанный URL на 10 минут; факт выдачи — в аудит ERP с `crm_*` контекстом |
| `GET /catalog/search?q=&mode=lead|client` | опубликованный каталог | в режиме `lead` без цен и остатков; в `client` — с ценой и статусом наличия |
| `POST /users/provision` | сотрудник из CRM | `crm_user_id, email, name, role (admin|backoffice), permissions[]` (коды каталога ERP, `ErpPermission`; чужой код → 422); ответ `erp_user_id`; e-mail занят другим пользователем ERP (другой `crm_user_id` или нет сопоставления) → 409 `EMAIL_CONFLICT` |
| `DELETE /users/{crm_user_id}/sessions` | отзыв сессий и входа | при снятии доступа в CRM: refresh и access-токены гаснут (прежний access → 401), вход закрыт; аудит `sso.revoke` |
| `GET /health` | здоровье для «Состояния системы» CRM | версия, миграции применены, очередь жива |

## 3. События (ERP → CRM)

`POST {CRM}/api/v1/integrations/erp/events`. Заголовки: `X-Event-Id` (UUID), `X-Event-Type`,
`X-Timestamp`, `X-Signature: sha256=<HMAC(body, WEBHOOK_SECRET)>`. CRM отвечает 200 быстро, обрабатывает
асинхронно; повтор с тем же `X-Event-Id` — 200 без действий. Ретраи ERP: 1, 5, 30 мин, 2, 6, 24 ч; после — журнал
с ручным повтором.

Тело: `{event, occurred_at, erp_company_id, crm_client_id, deal{erp_deal_id, number, title, stage, amount, currency}, actor{type: system|staff|client, name?}, payload{...}}`.

| Событие | payload | Что делает CRM |
|---|---|---|
| `request.created` | `source: crm|cabinet|erp` | лента лида; зеркало сделки `open` |
| `deal.stage_changed` | `from, to, reason?` | лента; `external_stage` |
| `quote.sent` | `version, public_url, valid_until` | бот: «КП готово» с кнопками |
| `quote.viewed` / `quote.accepted` / `quote.rejected` | `version, reason?` | лента; при accepted — уведомление ответственному |
| `contract.signed` | `by: client|company|both` | лента |
| `invoice.issued` / `invoice.paid` / `invoice.overdue` | `number, amount, due_date, link` | бот: «счёт выставлен»; напоминание — только ERP-письмо, бот дублирует по политике |
| `delivery.status_changed` / `delivery.eta_changed` | `line_summary, status, eta, tracking?` | бот: статус/сдвиг по политике «сообщать о сдвигах» |
| `act.issued` / `act.accepted` / `act.returned` | `number, reason?` | бот: «акт ждёт подтверждения» |
| `deal.won` / `deal.lost` | `amount, lost_reason?` | зеркало сделки → `won/lost`; стадия лида не меняется (CRM ADR-0022) |
| `document.created` | `erp_document_id, kind, number` | индекс документов клиента в CRM (без файла) |
| `invite.sent` | `channels[]` | лента |

## 4. Portal API (Cabinet → ERP)

| Метод и путь | Назначение |
|---|---|
| `POST /auth/telegram` | `{init_data}` → проверка подписи токеном бота (срок ≤ 5 мин), поиск контакта по `telegram_user_id`; сессия (cookie HttpOnly) |
| `POST /auth/magic-link` | `{email}` → письмо со ссылкой (15 мин, одноразовая); ответ всегда 200 |
| `POST /auth/magic {token}` | обмен токена из ссылки входа на сессию; токен приходит во фрагменте ссылки `/auth/magic#token=…` и не попадает в журналы (FIX-20). `GET /auth/magic/{token}` — устарел, снимается после FIX-24 |
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
счёт, акт, накладная; черновики, аннулированные и внутренние — никогда); `document_id` / `pdf_document_id` в договорах, счетах,
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

| Инструмент | Режим | Возвращает |
|---|---|---|
| `list_client_deals()` | customer | сделки с стадией и следующим шагом |
| `get_deal_status(erp_deal_id)` | customer | стадия, КП, счета, поставки (проекция), акты |
| `get_delivery_status(erp_deal_id)` | customer | строки: статус, ожидаемая дата, трек |
| `list_client_documents(kind?, date_from?, date_to?)` | customer | документы |
| `get_document_link(erp_document_id)` | customer | подписанный URL (бот отправляет файл) |
| `search_catalog(query, top_k)` | prospect, customer | prospect: название, описание, единица; customer: + цена, наличие, срок |
| `create_request(summary, lines[])` | customer | заявка в ERP от имени клиента (код решает, что это «запрос», модель лишь предлагает текст) |

## 6. SSO-токен сотрудника

JWT HS256, секрет `PLATFORM_SSO_SECRET` общий. Claims: `iss` (`crm`|`erp`), `aud` (целевая система),
`sub` (`crm_user_id`), `email`, `name`, `role`, `permissions[]`, `iat`, `exp` (= iat + 60 с), `jti`.
Приёмник: проверяет подпись, `aud`, срок, одноразовость `jti` (хранит 10 мин), находит пользователя по `sub`
(не создаёт), выдаёт свою сессию, пишет аудит. Доступом к ERP управляет CRM: `users.platform_access`
(`["crm"]` по умолчанию, `["crm","erp"]` — доступ выдан). Переключатель в шапке CRM и выдача токена
(`POST /api/v1/auth/sso/token`, иначе 403) — только при `erp` в `platform_access`; в шапке ERP — только у
пользователя с сопоставлением `CrmUserMapping`. Выдача доступа → провижининг в ERP, снятие → отзыв сессий
(очередь CRM, ошибки ERP — в центре внешних сервисов). Роль CRM → коды прав ERP: `packages/contracts/sso-token.md`.

## 7. Версионирование

Пространства версионируются префиксом (`v1`). Несовместимое изменение — новый префикс и период
совместимости в одну веху. События — поле `version` в теле (сейчас 1); новые поля добавляются без
смены версии, удаление или смена смысла — со сменой.
