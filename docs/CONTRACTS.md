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
| `POST /users/provision` | сотрудник из CRM | `crm_user_id, email, name, role (admin|backoffice), permissions[]`; ответ `erp_user_id`; e-mail занят другим пользователем ERP (другой `crm_user_id` или нет сопоставления) → 409 `EMAIL_CONFLICT` |
| `DELETE /users/{crm_user_id}/sessions` | отзыв сессий | при снятии доступа в CRM |
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
| `GET /auth/magic/{token}` | обмен на сессию |
| `POST /auth/logout`, `GET /me` | сессия и контакт, компания, права (`can_act`) |
| `GET /requests`, `POST /requests` | мои запросы; новый запрос (строки свободным текстом + вложения) → `request.created(source=cabinet)` |
| `GET /quotes`, `GET /quotes/{id}`, `POST /quotes/{id}/accept {code}`, `POST /quotes/{id}/reject {reason}` | КП |
| `GET /contracts`, `POST /contracts/{id}/sign` | договоры |
| `GET /invoices`, `GET /acts`, `POST /acts/{id}/accept`, `POST /acts/{id}/return {reason}` | счета и акты |
| `GET /deliveries` | поставки по строкам: проекция клиента (статус, ожидаемая дата, трек) |
| `GET /documents`, `GET /documents/{id}/file` | документы (поток, аудит) |
| `GET /catalog`, `GET /catalog/{id}` | опубликованный слой с ценой и наличием (решение владельца: только здесь) |
| `GET /company`, `PUT /company`, `GET /team`, `POST /team/invite` | профиль и команда клиента |

Все ответы отфильтрованы по компании сессии; тест на каждый эндпоинт «чужая компания → 404».

## 5. `erp-mcp` (для агента CRM)

Контекст — заголовок `X-Agent-Context` по образцу CRM SPEC §7.1: `{crm_client_id, erp_company_id,
mode: prospect|customer, language, exp}` с HMAC ключом из окружения, срок 60 с. Инструменты не принимают
идентификаторов клиента аргументами.

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
Приёмник: проверяет подпись, `aud`, срок, одноразовость `jti` (хранит 10 мин), находит/обновляет
пользователя, выдаёт свою сессию, пишет аудит. Переключатель показывается, если в CRM у пользователя
`platform_access` содержит обе системы; ERP узнаёт об этом при провижининге.

## 7. Версионирование

Пространства версионируются префиксом (`v1`). Несовместимое изменение — новый префикс и период
совместимости в одну веху. События — поле `version` в теле (сейчас 1); новые поля добавляются без
смены версии, удаление или смена смысла — со сменой.
