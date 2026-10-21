# Сверка отчёта as-is с кодом (main @ cc9a0a44, 2026-10-21)

Пути — относительно `/Users/nurbekgbm5/Downloads/My Apps/RailTech_Platform/`. Только чтение; тесты и docker не запускались.
Вердикты: **Подтверждено** — код совпадает с отчётом; **Опровергнуто** — код говорит обратное; **Уточнение** — отчёт верен по сути, но неточен в деталях или неполон.

## 1. ERP: стадии сделки, FSM, статусы документов

| Утверждение отчёта | Вердикт | Факт из кода (file:line) |
|---|---|---|
| Словарь стадий `DealStage`: DRAFT … CLOSED_WON (сверить) | Уточнение | 9 кодов FSM: DRAFT, KYC_PENDING, RFQ_OPEN, SOURCING, CALCULATING, QUOTE_SENT, CONTRACT_SIGNED, CLOSED_WON, CLOSED_LOST — `apps/erp/backend/crm/constants.py:13-22`; KYC_PENDING «выведен из эксплуатации», входа в него нет — `crm/services/deals.py:45-49` |
| Заявка начинается с `DRAFT` (`stages.initial_fsm_stage`) | Подтверждено | `integration/services/handoff.py:12,182`; `integration/services/stages.py:14`; MCP-инструмент — `integration/mcp/tools.py:203` |
| Переходы FSM (файл stages.py) | Уточнение | FSM живёт не в `stages.py`, а в `crm/services/deals.py:44-58` (`ALLOWED_STAGE_TRANSITIONS`): DRAFT→RFQ_OPEN/SOURCING/LOST; RFQ_OPEN→SOURCING/CALCULATING; SOURCING→CALCULATING; CALCULATING→QUOTE_SENT/SOURCING; QUOTE_SENT→CONTRACT_SIGNED/CALCULATING; CONTRACT_SIGNED→CLOSED_WON/LOST; CLOSED_WON→CONTRACT_SIGNED (переоткрытие); CLOSED_LOST→CALCULATING/SOURCING. `integration/services/stages.py` — только проекция FSM в 11 стадий контракта CRM |
| `CONTRACT_SIGNED` ставится при подписи договора | Опровергнуто | `CONTRACT_SIGNED` ставится при **акцепте КП**, договор ещё не подписан — `integration/services/stages.py:17` |
| `CLOSED_WON` — при подписи договора обеими сторонами (`_finalize_if_signed`) | Подтверждено | `crm/services/contracts.py:413-425`: при `status == SIGNED` → `transition_deal_stage(CLOSED_WON, reason="Контракт подписан обеими сторонами")`; гейт `STAGE_REQUIRES_SIGNED_CONTRACT` — `crm/services/deals.py:63,180-184` |
| Сделку закрывает подпись договора, а не акт | Уточнение | Два пути в CLOSED_WON: подпись договора (`contracts.py:425`) **и** приёмка отгрузки клиентом — `crm/services/fulfillment.py:175-176` (`Fulfillment.ACCEPTED` → CLOSED_WON, reason «Приёмка клиентом»). При этом в CRM стадия `won` уходит **не** по FSM, а когда исполнение закрыто целиком (счета оплачены, акты подписаны, поставка принята) — `integration/services/stages.py:27-28,170`; `deal.won` выпускается сигналом смены FSM — `integration/signals.py:110,127` |
| На CLOSED_WON автоматически создаётся счёт и отгрузка | Подтверждено (не было в отчёте) | `crm/services/deals.py:218-223` → `crm/tasks.py:70-74` (invoice draft + fulfillment) |
| Статусы КП: `SENT/APPROVED/REJECTED` | Уточнение | `QuoteStatusCode`: DRAFT, PENDING_TRADE_REVIEW, PENDING_APPROVAL, READY_TO_SEND, SENT, APPROVED, REJECTED — `crm/constants.py:43-50`; плюс сид `EXPIRED` — `core/seeds/sales.py:23`, ставится задачей `crm.expire_stale_quotes` — `crm/tasks.py:150-167`, в beat — `core/seeds/beat.py:54-57` |
| Договор: `PENDING_CLIENT / PENDING_MANAGER / SIGNED` | Подтверждено | + DRAFT, CANCELLED — `crm/constants.py:61-66` |
| Счёт: есть `OVERDUE` | Подтверждено | DRAFT, ISSUED, PARTIAL, PAID, OVERDUE, CANCELLED — `crm/constants.py:69-75` |
| `OVERDUE` не проставляется | Подтверждено | Ни одна задача/сервис не присваивает `OVERDUE` (grep по `finance/`, `crm/tasks.py`, `crm/services/billing.py` — только чтение статуса: `billing.py:349`, `portal/projections.py:289`). Задача `crm.send_payment_reminders` (`crm/tasks.py:467-520`) шлёт письмо-напоминание по ISSUED/PARTIAL с `due_date` старше 3 дней, статус **не меняет**; в сид beat (`core/seeds/beat.py`) её нет — только `crm.check_overdue_deliveries` (`beat.py:73-76`, `crm/tasks.py:16-50`) |
| Акт: статусы и «возврат» | Уточнение | `ActStatusCode`: DRAFT, ISSUED, SIGNED, CANCELLED — `crm/constants.py:78-82`; статуса RETURNED нет. Возврат клиентом (`reject_act`) переводит акт в **DRAFT** с `rejection_reason` — `crm/services/billing.py:753,766-769`; портал — `portal/views.py:567-583` |

## 2. ERP: строки КП, политика исполнения, финансы, снабжение/склад

| Утверждение отчёта | Вердикт | Факт из кода (file:line) |
|---|---|---|
| Строки КП: позиции, разделы, заметки, этапы (тип строки сверить) | Уточнение | `QuoteItem.display_type` ∈ {ITEM, SECTION, NOTE} — `sales/models/quotes.py:353-356,370-374`; «этапов» в модели нет. Контракт портала допускает `kind: stage` (`portal/serializers.py:273`), но проекция отдаёт только item/section/note — `portal/projections.py:189-191`; Cabinet рисует бейдж «этап» для `stage` (`apps/cabinet/src/pages/quotes.tsx:336`) — мёртвая ветка |
| `promised_date: null` (Q-FIX55-1) | Подтверждено | Жёстко `"promised_date": None` — `portal/projections.py:201`; Cabinet показывает поле — `apps/cabinet/src/pages/quotes.tsx:242,305-308` |
| `fulfillment_policy` у услуг: fixed / milestones / time | Подтверждено | `catalog/constants.py:23-31`; поле `Product.fulfillment_policy` — `catalog/models/products.py:164-166`; у товара очищается — `products.py:263-276`; в портал не отдаётся (в `portal/` упоминаний нет) |
| Политики выставления счёта «предоплата / по факту / по этапам» в finance нет (сверить) | Подтверждено | В `finance/` и `crm/services/billing.py` нет prepayment/milestones; есть только срок оплаты `CompanySettings.payment_terms_days` (`crm/services/billing.py:143-155`, умолчание `DEFAULT_INVOICE_DUE_DAYS`) и текстовое поле бланка `default_payment_terms` (`crm/services/documents/blank.py:146`) |
| `supply`, `inventory` — M4, не начата | Подтверждено | Оба приложения — заглушки: `supply/models.py` и `inventory/models.py` по одной строке-докстрингу; `migrations/` содержат только `__init__.py`. Реальные офферы поставщиков — в `sourcing/` (`sourcing/models.py`, 144 строки) |
| Исполнение: `Fulfillment` + `sales.DeliveryLine`, статусы `assembling…delivered` | Подтверждено | `DeliveryLineStatus`: assembling, in_transit, ready_to_ship, shipped, delivered, accepted, disputed — `sales/models/delivery.py:5-14`; `FulfillmentStatusCode`: PENDING…DISPUTED — `crm/constants.py:85-91` |

## 3. ERP integration: реально выпускаемые события

| Утверждение отчёта | Вердикт | Факт из кода (file:line) |
|---|---|---|
| Список событий ERP → CRM | Уточнение (полный список) | `request.created` (`integration/signals.py:99`), `deal.stage_changed` (:119), `deal.won`/`deal.lost` (:127-129), `quote.sent` (:174), `quote.accepted`/`quote.rejected` (:176-178), `contract.signed` (:238), `invoice.issued/paid/overdue` (:277-281), `act.issued/accepted/returned` (:320-324), `delivery.status_changed`/`delivery.eta_changed` (:364-372), `document.created` (:470), `invite.sent` (`integration/services/webhooks.py:633`), `delivery.line_accepted/disputed` (`webhooks.py:668-700`), `quote.viewed` (эмиттер в `webhooks.py`, тип в реестре). Единая точка — `emit_event` `webhooks.py:209` |
| `act.returned` боевым кодом не выпускается | Подтверждено | Сигнал ждёт статус RETURNED/DISPUTED/REJECTED (`integration/signals.py:323-324`), а возврат ставит DRAFT (`crm/services/billing.py:766`) → ветка недостижима. В CRM обработчик есть (`apps/crm/backend/app/services/erp_bot_messages.py:143`) |
| `invoice.overdue` — чем выпускается, сверить | Подтверждено (не выпускается) | Только при смене статуса на OVERDUE — `integration/signals.py:280-281`; статус никто не ставит (§1) → событие фактически мёртвое |
| `delivery.eta_changed` — «ETA нечем считать» | Уточнение | Событие **выпускается** при ручной смене `Fulfillment.expected_delivery_date` сотрудником — `integration/signals.py:368-374` (`prev_eta != curr_eta`), через `update_fulfillment_status(extra=expected_delivery_date)` `crm/services/fulfillment.py:170-172`. Автоматического расчёта ETA нет — верно |

## 4. ERP portal: маршруты, приглашение, код акцепта

| Утверждение отчёта | Вердикт | Факт из кода (file:line) |
|---|---|---|
| Маршруты портала | Подтверждено (полный список) | `portal/urls.py:39-115`: `auth/telegram`, `auth/magic-link`, `auth/magic`, `auth/logout`, `me`, `requests[/{id}]`, `quotes[/{id}]`, `quotes/{id}/request-code|accept|reject`, `contracts`, `contracts/{id}/sign`, `invoices`, `acts`, `acts/{id}/accept|return`, `deliveries`, `deliveries/{id}/accept|dispute`, `documents`, `documents/{id}/file`, `uploads`, `catalog[/categories|/{id}]`, `company`, `team`, `team/invite` |
| Мутирующие | Подтверждено | request-code / accept / reject КП, sign договора, accept / return акта, accept / dispute строки поставки, uploads, PUT company, team/invite, POST requests. Входа по паролю нет; `GET /invoices/{id}` и `GET /deals/{id}` нет |
| `POST /team/invite channels: telegram` → 422 `INVALID_CHANNEL` | Подтверждено | `portal/serializers.py:117-119` (choices email|telegram), `portal/services/invitation.py:44-60,134-140`; `DELIVERABLE_CHANNELS` = только email; нет e-mail → `CONTACT_EMAIL_REQUIRED` |
| Handoff: приглашение только письмом; Telegram ERP не шлёт | Подтверждено | `integration/services/handoff.py:198-208` (`_invite`: `both`→письмо, `telegram`→`INVALID_CHANNEL`, `sent_via` — реально ушедшее); CRM вычисляет `channels` по контактам, по умолчанию `["telegram"]` — `apps/crm/backend/app/services/erp_handoff.py:218-225`, `app/integrations/erp.py:280` → контакт без e-mail приглашения не получает |
| Контакт «по ИНН» — `can_act=false`, без приглашения | Подтверждено | `integration/services/handoff.py:211-227` (`_log_linked_by_inn`) |
| Код акцепта: письмом; в Telegram прямым Bot API за флагом `PORTAL_ACCEPT_CODE_TELEGRAM` | Подтверждено | `portal/services/acceptance.py:6-9,36-37,50-58` (`httpx.post api.telegram.org/bot<TOKEN>/sendMessage`); нет канала → 422 `CONTACT_CHANNEL_REQUIRED` — `portal/views.py:392-397`; флаг — `core/settings/base.py:81-83` (по умолчанию выключен) |

## 5. ERP accounts: роли, права, провижининг из CRM

| Утверждение отчёта | Вердикт | Факт из кода (file:line) |
|---|---|---|
| 22 кода прав | Подтверждено | `accounts/constants.py:38-70` (`Permission`), группы `PERMISSION_GROUPS` :74-91 |
| Роли `CALCULATION, CATALOG_SUPPLY, FULFILLMENT, FINANCE, HEAD, VIEWER` | Подтверждено | `accounts/constants.py:101-106`; шаблоны прав `ROLE_TEMPLATES` :110-137 — CALCULATION: deal.manage, quote.build, quote.edit_pricing, quote.view_cost_margin, quote.send, quote.review, contract.manage; CATALOG_SUPPLY: catalog.manage, catalog.publish, supply.manage, quote.view_cost_margin; FULFILLMENT: fulfillment.manage, fulfillment.act; FINANCE: finance.invoice, finance.payment, finance.rates, quote.view_cost_margin, data.export; HEAD: все; VIEWER: [] |
| Есть ещё «должности» | Уточнение (не было в отчёте) | `WorkspaceRoleCode` (OWNER, SALES_MANAGER, DIRECTOR, FOREIGN_TRADE_SPECIALIST, LOGIST, CONTRACT_MANAGER, PROCUREMENT_MANAGER, BUYER_MANAGER, MEMBER) — `accounts/constants.py:15-24`; доступ определяют не они, а роли бэк-офиса (`integration/services/provision.py:105-109`) |
| Администратор = `is_superuser`, роли «Администратор компании» нет | Подтверждено | `accounts/constants.py:30,140-143` (`SystemRoleCode.ADMIN` — операторская плоскость удалена) |
| Провижининг из CRM: `admin → is_superuser`; `manager → deal.manage, quote.build, quote.edit_pricing, quote.send`; `viewer → нет прав` | Уточнение | ERP принимает `role ∈ {admin, backoffice}` и **произвольный** список `permissions` из каталога — `integration/services/provision.py:49-50,89-93,116-127`; создаёт/обновляет роль «CRM Sync: <e-mail>» (`managed_by_crm=True`). Ограничение «только 4 права менеджеру» — на стороне CRM: `apps/crm/backend/app/domain/erp_permissions.py:7-10,49-…` (`MANAGER_PERMISSIONS`). То есть «роли бэк-офиса из CRM выдать нельзя» — ограничение CRM-UI/карты, а не API ERP |
| `platform_access` в приёмке | Уточнение | ERP в SSO-payload жёстко отдаёт `"platform_access": ["crm","erp"]` — `accounts/services/sso.py:99`; в токене ERP→CRM `role = admin|manager` по `is_superuser` — `sso.py:133`; `role_codes` в приёмке нет, роли — только провижинингом (`sso.py:214`). В CRM `platform_access` — CHECK-ограничение `["crm"] ⊆ x ⊆ ["crm","erp"]` — `apps/crm/backend/app/models/auth.py:27-40` |

## 6. ERP settings: переменные окружения и первый запуск

| Утверждение отчёта | Вердикт | Факт из кода (file:line) |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` в `.env` ERP (сверить имя) | Подтверждено | `core/settings/base.py:49`: `TELEGRAM_BOT_TOKEN` или `ERP_TELEGRAM_BOT_TOKEN`; `TELEGRAM_BOT_USERNAME` :50; `CABINET_URL` :51; `CABINET_ORIGIN` :63; `PORTAL_COOKIE_SAMESITE` :70; `PORTAL_ACCEPT_CODE_TELEGRAM` :83. compose отдаёт тот же `${TELEGRAM_BOT_TOKEN}` и CRM, и ERP — `infra/compose/base.yml:39,386` |
| `EMAIL_*` ERP в `.env` | Уточнение | Читаются в `core/settings/ai.py:130-137` (`EMAIL_BACKEND, EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, EMAIL_USE_TLS, DEFAULT_FROM_EMAIL`), не в `base.py`; на проде маппятся из `SMTP_*` — `infra/compose/prod.yml:60-65`; `EMAIL_MKT_FROM`, `EMAIL_SYS_FROM` — `observability.py:45,50` |
| `LITELLM_BASE_URL`, `LITELLM_API_KEY`, бюджет | Подтверждено | `core/settings/ai.py:15-16`; `AI_DAILY_BUDGET_USD` :46 (compose: `ERP_AI_DAILY_BUDGET_USD` → `base.yml:365`); `AI_IMPORT_ENABLED` :18 |
| `SENTRY_DSN` | Уточнение | Читается `observability.py:72` (+ `SENTRY_ENVIRONMENT` :82, `SENTRY_TRACES_SAMPLE_RATE` :85), но **не прокинут** ни в `infra/compose/*.yml`, ни в `.env.example`/`infra/.env.prod.example` → на проде Sentry выключен по умолчанию |
| `OWN_COMPANY_ID` | Подтверждено | `core/settings/project.py:87`; правило выбора — `core/tenant.py:9,29-40` (ошибка, если >1 компании-продавца с активными участниками) |
| `SERVICE_TOKEN_*`, `WEBHOOK_SECRET`, `PLATFORM_SSO_*` | Уточнение (имена) | `SERVICE_TOKEN_CRM_TO_ERP` `api.py:175`; `ERP_WEBHOOK_SECRET` `api.py:186` (compose собирает из `WEBHOOK_SECRET[,WEBHOOK_SECRET_PREVIOUS]` — `base.yml:371`); `PLATFORM_SSO_SECRET` `api.py:200`; `PLATFORM_SSO_ENABLED` `api.py:221`; `ERP_MCP_CONTEXT_KEY` `api.py:194`; `CRM_BASE_URL` :179, `CRM_FRONTEND_URL` :218 |
| `PLATFORM_NAME`, `SUPPORT_EMAIL` из `.env` | Уточнение | `PLATFORM_NAME` — только заголовок Django Unfold (`core/settings/apps.py:75-76`), compose его ERP **не передаёт**; `SUPPORT_EMAIL` — `observability.py:59`, в compose `base.yml:357` |
| Прочие env ERP | Справочно | `DJANGO_DEBUG`, `DJANGO_SECRET_KEY` `base.py:27,30`; `DATABASE_URL`/`POSTGRES_*`/`DB_*` `database.py:32-71`; `REDIS_URL`, `CELERY_*` `infra.py:11-18`; `MINIO_*` `project.py:66-77`; `FX_RATE_MAX_AGE_DAYS` `project.py:93`; `FRONTEND_URL` `observability.py:55`; `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`, `PRODUCTION`, HSTS `web.py:57-136`; лимиты `INTEGRATION_RATE`, `PORTAL_*_RATE`, `LOGIN_LOCKOUT_*` `api.py:35-129` |
| Мастер первого запуска ERP: `core_seed`/`ensure_default_company_roles`/`OWN_COMPANY_ID` вручную | Уточнение | Есть мастер создания компании в Django-админке: `accounts/wizard.py:1-9` (4 шага: реквизиты, контакты, тип, владелец), маршрут `/admin/accounts/company/wizard/` — `core/urls.py:164`; суперадмин — `manage.py init_superadmin` из `SUPERADMIN_EMAIL/PASSWORD` (`accounts/management/commands/init_superadmin.py:9-23`); `core_seed` — `core/management/commands/core_seed.py`; entrypoint делает только `migrate` (`entrypoint.sh:18`). Мастера в SPA ERP нет |

## 7. CRM: стадии, режимы, handoff, события ERP, консоль админа

| Утверждение отчёта | Вердикт | Факт из кода (file:line) |
|---|---|---|
| Стадии лида `new → engaged → qualified → handoff → in_progress → won/customer` | Уточнение | `Stage`: new, engaged, qualified, handoff, in_progress, won, customer, lost, unresponsive — `apps/crm/backend/app/domain/stages.py:6-15`; событие ERP стадию лида не меняет — `stages.py:24-25` |
| Режим `local`/`erp` = факт настройки коннектора | Подтверждено | `app/domain/backoffice.py:21-28` (`backoffice_mode(erp_connector_configured)`) |
| Кнопка «Передать» из `in_progress/won/customer` в `erp`, из `won/customer` в `local` | Подтверждено | `HANDOFF_FROM` — `backoffice.py:33-37`; повторная передача/resync — :52-56,85-91; «Сделка заключена» только в `local` — `may_close_locally` :95-103 |
| Handoff: что уходит в ERP | Подтверждено | Контакты `email` + `telegram_user_id` (`app/services/erp_handoff.py:277-295`), `invite.channels` по наличию каналов (:218-225), согласие; ответ — `invite_sent_via`, `cabinet_url` (`app/integrations/erp.py:300-301,443-444`) |
| Бот пишет `client_access_granted` без ссылки на кабинет (сверить) | Подтверждено | Текст: «Теперь вам доступны документы и запросы менеджеру: /docs — …, /request — …, /help — все команды» ×3 языка — `app/schemas/settings_client.py:48-52`; отправка один раз при привязке — `app/services/clients.py:338-346`; `cabinet_url` из ответа ERP в сообщение не подставляется |
| События ERP → сообщение клиенту: `quote.sent`, `invoice.issued/paid/overdue`, `delivery.status_changed/eta_changed`, `act.issued` | Уточнение | Клиенту в Telegram: `quote.sent`, `invoice.issued`, `invoice.paid`, `delivery.status_changed`, `delivery.eta_changed`, `act.issued` — `app/services/erp_bot_messages.py:69-116`; **`invoice.overdue` клиенту не шлётся** (ветка `else: return None` :116), только запись в ленту (`erp_event_handlers.py:148`). Кнопка «Кабинет» добавляется ко всем сообщениям, если есть `cabinet_url` — `erp_bot_messages.py:118-120`. Сотруднику (ЛС): `quote.accepted`, `act.returned`, `delivery.line_disputed` — :134-160 |
| Консоль админа: Подключения, Модели ИИ, Почта, Пользователи, Внешние сервисы, Состояние системы, Расходы, Аудит, `/setup` | Уточнение | Ресурсы `apps/crm/frontend/src/app/App.tsx:59-82`: inbox, leads, clients, deals, dashboard, spend, kb, gaps, sandbox, settings, templates, users, integrations, models, system, external-services, backups, audit, profile; маршруты `/setup`, `/login`, `/sso/exchange`, `/change-password` — :268-271. «Почта» — не отдельный раздел, а карточка внутри «Подключений» (`src/pages/integrations/SmtpCard.tsx`, `MailLog.tsx`); «Бэкапы» (`/backups`) в отчёте не упомянут |

## 8. CRM бот

| Утверждение отчёта | Вердикт | Факт из кода (file:line) |
|---|---|---|
| Клиентское меню `/docs`, `/request`, `/status`, `/human` | Подтверждено | `app/bot/client_handlers.py:48,81,106`; `/human`, `/help`, `/lang`, `/delete` — `app/bot/handlers.py:129-154`; меню по статусу — `app/bot/commands.py:1-28`, `app/domain/bot_menu.py` |
| `/status` — заглушка | Уточнение | Не заглушка: отдаёт последний **открытый сервисный запрос CRM** (`ServiceRequest.status == "open"`) текстом `request_status_open/none` — `app/services/client_bot.py:281-303`. Статуса сделки/счёта из ERP не даёт — в этом смысле отчёт прав |
| Бот не разбирает `/start deal_<id>` / `quote_<id>` | Подтверждено | `on_start` передаёт в `conversation.start` только `"/start"` без аргументов — `app/bot/handlers.py:112-117`; `conversation.py:123` — «/start: приветствие»; grep `start_param|deal_|quote_` по `app/bot` — пусто |
| `dialog_customer.md` и инструменты erp-mcp в агенте не реализованы | Уточнение | Промпт **есть**: `apps/crm/backend/prompts/dialog_customer.md`, подключён `PROMPTS["customer"]` — `app/agents/dialog/nodes.py:29`, режим `customer` активен (:55-57,161). Инструментов ERP **нет**: `CUSTOMER_TOOLS` = только `create_service_request` — `app/agents/dialog/customer.py:17-29`; MCP-клиент знает серверы `kb | crm | docs` — `app/agents/mcp_client.py:19`, `erp` отсутствует |

## 9. CRM роли и политика

| Утверждение отчёта | Вердикт | Факт из кода (file:line) |
|---|---|---|
| Роли `admin`, `manager`, `viewer`; casbin (сверить) | Подтверждено | Политика — `apps/crm/infra/casbin/policy.seed.csv` (+ `model.conf`), путь — `app/config.py:17-20`; загрузка в БД `CasbinRule` — `app/security/rbac.py:62-70` |
| Объекты | Подтверждено (полный список) | `rbac.py:26-44`: leads(read,take,work,reply,note,assist,create), stream, dashboard, clients(r/w), deals(r/w), documents(r/w), users, settings, kb, audit, backups, spend, models(read,test,write), integrations, system, sandbox(use), reply_templates, export, external_services |
| Права manager / viewer | Подтверждено | `policy.seed.csv`: admin `*`; manager — leads ×7, stream, dashboard, clients r/w, deals r/w, documents r/w, kb read, reply_templates read; viewer — leads/stream/dashboard/clients/deals read |

## 10. Cabinet

| Утверждение отчёта | Вердикт | Факт из кода (file:line) |
|---|---|---|
| Маршруты | Подтверждено (полный список) | `apps/cabinet/src/app/routes.tsx:34-63`: `/login`, `/login/sent`, `/new-client` (только веб), `/auth/magic`, `/`, `/requests`, `/requests/new`, `/requests/:id`, `/quotes`, `/quotes/:id`, `/contracts`, `/invoices`, `/acts`, `/deliveries`, `/documents`, `/catalog`, `/catalog/:id`, `/company`, `/team`, `/deals/:id`, `/profile` |
| Страницы счёта `/invoices/:id` нет | Подтверждено | Только список `/invoices` (`routes.tsx:53`, `src/pages/billing.tsx:139-149`); ссылка бота `{CABINET_URL}/invoices/<id>` → `NotFoundPage` |
| Входа по паролю нет | Подтверждено | В `src/pages` слово `password` не встречается; API портала — только magic-link и Telegram (`portal/urls.py:39-46`) |
| Уведомлений в приложении нет | Подтверждено | Только тосты sonner (`src/components/ui/sonner.tsx`); центра уведомлений/опроса событий нет |
| `/deals/<id>` собирается из списков | Подтверждено | `src/pages/deal.tsx`; `GET /deals/{id}` в `portal/urls.py` отсутствует; «Написать менеджеру» → `t.me/<бот>?start=deal_<id>` — `deal.tsx:24`, имя бота — `VITE_BOT_USERNAME` (`apps/cabinet/.env.example`) |

## 11. .env и compose

| Утверждение отчёта | Вердикт | Факт из кода (file:line) |
|---|---|---|
| `.env.example` корня — группы | Справочно | `/.env.example`: приложение (APP_ENV, LOG_*); Postgres; Redis; S3 (RustFS); LiteLLM (`LITELLM_MASTER_KEY`, `LITELLM_SALT_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`); docling; CRM (`CRM_JWT_SECRET`, `CRM_SECRETS_KEY`, `CRM_AGENT_CONTEXT_KEY`, `CRM_LANGFUSE_*`); Telegram (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`, `TELEGRAM_MODE`, `TELEGRAM_WEBHOOK_*`); Cabinet↔CRM (`CABINET_CRM_URL`, `CABINET_ORIGIN`, `PORTAL_COOKIE_SAMESITE`); шов (`SERVICE_TOKEN_CRM_TO_ERP`, `SERVICE_TOKEN_ERP_TO_CRM`, `WEBHOOK_SECRET[_PREVIOUS]`, `PLATFORM_SSO_SECRET`, `PLATFORM_SSO_ENABLED`, `ERP_MCP_CONTEXT_KEY`); бренд (`PLATFORM_NAME`, `SUPPORT_EMAIL`); ERP (`OWN_COMPANY_ID`, `ERP_SECRET_KEY`, `ERP_DEBUG`, `ERP_EMAIL_BACKEND`, `ERP_LITELLM_API_KEY`, `ERP_AI_DAILY_BUDGET_USD`, `ERP_LANGFUSE_*`); адреса/порты; домены и ACME; Langfuse/ClickHouse |
| `infra/.env.prod.example` | Справочно | То же плюс: раскладка серверов (`APP_INTERNAL_IP`, `DB_INTERNAL_IP`, `RT_DB_DIR`, `RT_BACKUP_DIR`, `RT_PROFILES`); пароли ролей БД (`DB_CRM_PASSWORD`, `DB_ERP_PASSWORD`, …); бэкапы (`BACKUP_*`, внешнее S3, `BACKUP_ENC_PASSPHRASE`); SMTP ERP (`SMTP_HOST/PORT/USER/PASSWORD/USE_TLS/FROM` → `EMAIL_*`, `prod.yml:60-65`); `ERP_AI_ENABLED`. `SENTRY_DSN` отсутствует |
| Два набора SMTP (CRM коннектор + ERP `.env`) | Подтверждено | ERP — `SMTP_*`/`EMAIL_*` (выше); CRM — коннектор «Почта» в БД (`SmtpCard.tsx`), в `apps/crm/.env.example` есть свои `SMTP_HOST … SMTP_FROM_NAME` как резерв |
| Сервисы compose | Справочно | `infra/compose/base.yml`: postgres, db-init, redis, rustfs, s3-init, litellm, litellm-seed, docling, crm-migrate, crm-api, crm-worker, crm-mcp-kb, crm-mcp-crm, crm-mcp-docs, crm-web, erp-backend, erp-mcp, erp-worker, erp-worker-ai, erp-beat, erp-ai-gateway, erp-web, cabinet-web, caddy, clickhouse, langfuse-worker, langfuse-web (строки 60-622) |
| Профили | Уточнение | base.yml: `observability` (clickhouse, langfuse-*) — :551,570,622. prod.yml: `local-db` (postgres, db-init) :81-83; `kb-ingest` (docling) :121; **`mcp` (erp-mcp) :239** — на проде erp-mcp не стартует без профиля (согласуется с «M3-CRM-07 не сделан»); `RT_PROFILES` — `infra/.env.prod.example:18-19` |
| «FIX-65…71 в репозитории отсутствуют» | Уточнение | В `main` их нет (git log — пусто), но есть ветки/worktree: `origin/fix/all-65-first-run`, `origin/fix/crm-66-telegram-webhook-url`, `fix/all-66b-log-secrets`, `fix/erp-67-quote-from-request`, `fix/all-71-erp-login-via-crm`; `.claude/worktrees/fix-61, fix-62, fix-63, fix-66b, fix-67, fix-71, m3-05, m3-06, docs-w6` — волна 6 в работе, не влита |

## Итог: главные расхождения с отчётом

1. **`CONTRACT_SIGNED` ставится при акцепте КП**, а не при подписи договора (`integration/services/stages.py:17`) — в отчёте таблица шага 7 вводит в заблуждение.
2. **`CLOSED_WON` достигается двумя путями**: подпись договора обеими сторонами и приёмка отгрузки клиентом (`crm/services/fulfillment.py:175-176`); в CRM же `won` уходит только при полном исполнении (`stages.py:27-28,170`) — «сделку закрывает подпись, а не акт» верно лишь для внутреннего FSM.
3. **`act.returned` недостижим по конструкции**: сигнал ждёт RETURNED/DISPUTED/REJECTED, а `reject_act` ставит DRAFT (`signals.py:323`, `billing.py:766`) — отчёт прав, но причина — несогласованность статусов, а не «не реализовано».
4. **`delivery.eta_changed` выпускается** при ручной смене срока (`signals.py:368-374`) — отчёт сомневался.
5. **`invoice.overdue` клиенту в Telegram не шлётся** (`erp_bot_messages.py:116`) — отчёт включал его в список бот-сообщений; и само событие мёртвое, потому что OVERDUE никто не ставит.
6. **`/status` в боте — не заглушка**, а статус открытого сервисного запроса CRM (`client_bot.py:281-303`); `dialog_customer.md` существует и используется, нет только ERP-инструментов (`customer.py:17-29`, `mcp_client.py:19`).
7. **ERP принимает произвольный список прав при провижининге** (`provision.py:50,124`); ограничение «только 4 права менеджеру» — карта на стороне CRM (`erp_permissions.py:49`). D-10 — вопрос CRM-UI, не API ERP.
8. **Строк-«этапов» в КП нет** (`QuoteItem.display_type` = ITEM/SECTION/NOTE), `kind: stage` и `promised_date` в контракте портала не заполняются никогда (`projections.py:189-201`).
9. **`SENTRY_DSN` и `PLATFORM_NAME` ERP читает, но compose/`.env.example` их ERP не передают** — Sentry на проде выключен; бренд в ERP берётся из умолчания.
10. **Задача напоминаний по счетам есть** (`crm.send_payment_reminders`, `crm/tasks.py:467-520`), но в сид beat не включена; в ERP есть мастер создания компании в Django-админке (`accounts/wizard.py`) — отчёт говорил «вручную». FIX-65…71 — не «отсутствуют», а в незалитых ветках/worktree.
