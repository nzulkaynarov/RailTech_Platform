# Карта интеграции: экраны → BFF → домены (CRM, EDS, ERP)
Статус: действует · Владелец: архитектор · Обновлено: 2026-10-26

Версия 1.0 · 2026-10-22 · Сверено с `main @ fb3a3928`: CRM — OpenAPI CRM (тогда `apps/crm/docs/api/openapi.json`, теперь `packages/contracts/openapi/crm.yaml`) (109 путей), ERP —
`packages/contracts/openapi/erp-internal.yaml` (251 путь), шов — `erp-integration.yaml` 0.5.0, портал —
`erp-portal.yaml` 0.3.0.

> **Поправки стратегии 2026-10-23 (действуют поверх текста ниже).** Сущности EDS — письма, резолюции, служебные записки,
> маршруты согласования и реестр документов — живут в **сервисе EDS** (ADR-0015), а не в приложении `eds` внутри ERP:
> разрывы ERP-01 и ERP-05 стали **EDS-01** и **EDS-02** (§7), одобрение КП директором — маршрут согласования EDS
> (`approval.requested/decided`, **EDS-03**). ERP-08 (чаты) из ERP уходит: по ADR-0015 чаты — домен коммуникаций CRM,
> окончательно — на этапе D. ERP-10 (события для BFF) — шина `rt_bus` (ADR-0014, этап B), не Redis Streams. Колонка
> «Фаза» (P2–P4) читается как этапы C–D стратегии; перенаправления §6 — этап C2 (старые фронты удаляются).

Обозначения: **✓** — операция есть; **Δ** — нужна доработка бэкенда (номер разрыва из §7); BFF-эндпоинты
описываются контрактом `packages/contracts/openapi/platform-bff.yaml` (создаётся в задаче PLT-02).

## 1. Эндпоинты BFF и откуда они берут данные

Префикс BFF — `/api/v1`. Все вызовы бэкендов — с токеном сотрудника (`docs/architecture/platform-bff.md` §3).

### 1.1. Сессия, профиль, поиск, уведомления

| BFF | CRM | ERP | Статус |
|---|---|---|---|
| `POST /auth/login`, `POST /auth/logout`, `GET /auth/session` | `POST /auth/login`, `/auth/refresh`, `/auth/logout`, `GET /me`, `POST /auth/sso/token` | `POST /auth/sso/exchange/`, `/auth/token/refresh/`, `/auth/logout/` | ✓ |
| `GET /me` (имя, роли Платформы, язык, модули) | `GET /me`, `GET /me/permissions` | — | Δ CRM-01, R-1 (`platform_role_refs`) |
| `GET /search?q=` | `GET /leads?q=`, `GET /clients?q=` | `GET /crm/analytics/search-documents/`; сделки по номеру и названию — **нет** (`DealViewSet` без `search_fields`) | частично; сделки — Δ ERP-09, чаты — Δ ERP-08 |
| `GET /notifications`, `POST /notifications/read-all`, `POST /notifications/{id}/read` | Δ CRM-04 (уведомления сотрудникам из CRM) | `GET /notifications/`, `PATCH /notifications/mark_all_read/`, `PATCH /notifications/{id}/mark_read/` | ✓ ERP, Δ CRM |
| `GET /events` (SSE, фаза P4) | `GET /stream` | Δ ERP-10 (шина `rt_bus`, этап B) | Δ |
| `GET /menu-counters` (бейджи подменю всех модулей) | `GET /inbox`, `GET /service-requests` | счётчики по §1.2–1.5 | агрегат |

### 1.2. Dashboard

| BFF | Источники | Статус |
|---|---|---|
| `GET /queue` — строки «Что сделать сейчас» для всех ролей сотрудника | MANAGER: CRM `GET /inbox`, `GET /leads?stage=…`, `GET /service-requests`. DIRECTOR: письма без резолюции (Δ EDS-01), `GET /crm/quotes/my-approval-queue/`, служебки на согласовании (Δ EDS-02), проблемные проекты (вывод BFF). SUPPLY, ENGINEER: задания на расчёт по резолюции (Δ EDS-01, ERP-02). ACCOUNTANT: платёжки на подтверждение (Δ ERP-04), `GET /crm/invoices/?status=DRAFT`, договоры к выставлению (Δ ERP-03), служебки к оплате (Δ EDS-02), просроченные счета (Δ ERP-06). ADMIN: тикеты (Δ CRM-05), CRM `GET /admin/external-services` с проблемами | частично ✓ |
| `GET /queue/counters` | то же, только числа | частично ✓ |
| `GET /activity/today` (вкладка «Сегодня») | ERP `GET /crm/activity-logs/`, `GET /crm/timeline/`; CRM `GET /audit` | ✓ |
| `GET /summary` (воронка, застрявшие, дебиторка, причины отказов) | CRM `GET /dashboard`, `GET /deals/summary`; ERP `GET /crm/analytics/dashboard/`, `GET /crm/analytics/time-to-first-quote/` | ✓ (застрявшие по 7 шагам — вывод BFF) |

### 1.3. CRM

| Экран / действие | BFF | CRM | ERP | Статус |
|---|---|---|---|---|
| Все лиды, вкладки и фильтры | `GET /leads` | `GET /leads` | — | ✓; статусы Платформы — §3.1, Δ CRM-02 для «Просит КП» |
| Карточка лида в боковом окне | `GET /leads/{L-NNNN}` | `GET /leads/{id}`, `/messages`, `/notes`, `/decisions` | — | ✓ |
| Забрать, Ответить, Вернуть боту, Отказ | `POST /leads/{no}/take` и т. п. | `POST /leads/{id}/actions/take|return_to_bot|close_lost`, `POST /leads/{id}/messages` | — | ✓ |
| **Создать заявку** | `POST /leads/{no}/request {company{name,inn}, contact{…channels}, summary, letter_file?, urgency}` | `POST /leads/{id}/actions/make_customer` → передача в ERP (`POST /clients/handoff` шва) | handoff создаёт компанию, контакты, `Deal`; **плюс** письмо ВХ, чат проекта, `process = v3`, номер ЗВ | Δ CRM-03, Δ EDS-01, ERP-07, ERP-09, контракт шва |
| Все сообщения (передачи от бота с запиской, SLA) | `GET /inbox` | `GET /inbox`, `GET /leads/{id}/decisions` | — | ✓ (записка handoff — Δ CRM-06) |
| Все клиенты, карточка 360° | `GET /clients`, `GET /clients/{id}` | `GET /clients`, `/clients/{id}`, `/contacts`, `/erp-receivables`, `/documents` | шов: `GET /companies/{id}/summary`, `/companies/{id}/deals`, `/deals/{id}/documents` | ✓ |
| Новая заявка для клиента | `POST /clients/{id}/request` | `POST /leads/{id}/actions/new_deal` | handoff с `create_request` | Δ CRM-03 |
| Все заявки (ЗВ/ПР, 7 шагов) | `GET /requests` | — | `GET /crm/deals/` + документы | ✓, шаг — §2 |
| Каналы связи | `GET /channels` | `GET /integrations/telegram`, `GET /settings` (тексты), `GET /integrations/smtp` | — | ✓ |
| База знаний | `/kb/*` | `/kb/documents*`, `/kb/gaps*`, `/kb/products*`, `/reply-templates*` | — | ✓ |

### 1.4. EDS

| Экран / действие | BFF | ERP (если не указано) | Статус |
|---|---|---|---|
| Входящие, карточка письма | `GET /letters`, `GET /letters/{ВХ}` | сервис EDS | Δ EDS-01 |
| **Утвердить резолюцию** / Вернуть менеджеру / Отклонить | `POST /requests/{ЗВ}/resolution {text, assignees[], due, min_margin}`; `/return`; `/reject {reason}` | сервис EDS; отклонение — `POST /crm/deals/{id}/change-stage/` в `CLOSED_LOST` | Δ EDS-01 |
| Черновик КП, карточка | `GET /quotes/{КП}` (себестоимость и маржа — только DIRECTOR, SUPPLY) | `GET /crm/quotes/{id}/`, `/approval-preview/`, `/download-pdf/` | ✓ |
| **Одобрить КП → Исходящие** (каналы) | `POST /quotes/{КП}/approve {channels[]}` | сейчас два шага: `POST /crm/quotes/{id}/approval-act/` + `POST /crm/quotes/{id}/send-to-client/`; нужно атомарно с ИСХ-номером и выбором каналов | Δ ERP-11 |
| Вернуть на доработку | `POST /quotes/{КП}/return {comment}` | `POST /crm/quotes/{id}/approval-act/` (reject) → `DRAFT`, новая версия | ✓ |
| Исходящие, «Напомнить клиенту» | `GET /outbox`, `POST /quotes/{КП}/remind` | `GET /crm/quotes/?status=SENT…`; напоминание — событие для бота | Δ ERP-12 |
| Все проекты, карточка проекта | `GET /projects`, `GET /projects/{ПР}` | `GET /crm/deals/{id}/`, `/documents/`, `GET /crm/contracts|invoices|acts|fulfillments/?deal=` | ✓ |
| Договор: на согласование редакции, выставлен у оператора, прикрепить скан | `POST /contracts/{ДОГ}/status {status, scan_upload_id?}` | `upload-signed/` есть; статусы и журнал — новое | Δ ERP-03, портал Δ CAB-02 |
| Счета и оплаты, вкладки | `GET /invoices?tab=` | `GET /crm/invoices/`, `GET /crm/payments/` | ✓ (платёжки — Δ ERP-04, просрочка — Δ ERP-06) |
| **Подтвердить оплату** / Частичная / Запросить платёжку | `POST /invoices/{СЧ}/confirm-payment {amount, date}`; `POST /invoices/{СЧ}/request-payment-doc` | `POST /crm/invoices/{id}/record-payment/` ✓; связь с платёжкой и запрос платёжки — новое | Δ ERP-04 |
| Акт: выпустить, прикрепить скан, возврат | `POST /acts/{АКТ}/…` | `POST /crm/invoices/{id}/generate-act/`, `/acts/{id}/reissue/`, `/remind/`; загрузка скана сотрудником — новое; событие `act.returned` — FIX-62 | Δ ERP-13 |
| На согласовании, служебная записка | `GET/POST /memos`, `POST /memos/{СЗ}/decision` | сервис EDS | Δ EDS-02 |
| Создать документ (служебка, заявление, отчёт, письмо) | `POST /documents {type,…}` | сервис EDS; шаблоны — `GET /crm/document-templates/` | Δ EDS-02 |
| Все документы | `GET /documents?type=&status=` | `GET /crm/generated-documents/`, КП, договоры, счета, акты + EDS | агрегат |

### 1.5. ERP

| Экран / действие | BFF | ERP | Статус |
|---|---|---|---|
| Все запросы | `GET /calc` | `GET /crm/deals/?stage=…` + визы | Δ ERP-02 (визы) |
| Расчёт по заявке, строки | `GET /calc/{ЗВ}` | `GET /crm/quotes/{id}/`, `GET /crm/quote-items/?quote=`, `GET /catalog/offers/`, `/quote-items/{id}/match-candidates/`, `/quotes/{id}/pricing-assist/` | ✓ (склад — Δ ERP-14) |
| Изменить строку, добавить, ИИ-разбор | `PUT /calc/{ЗВ}/lines/{id}`, `POST /calc/{ЗВ}/lines`, `POST /calc/{ЗВ}/parse` | `PATCH /crm/quote-items/{id}/`, `/bulk-create/`, `POST /crm/deals/{id}/generate-draft-quote/` | ✓ |
| **Подтвердить** (виза строки по роли) | `POST /calc/{ЗВ}/lines/{id}/approve` | новое `LineApproval` | Δ ERP-02 |
| Запросить цену у поставщика | `POST /calc/{ЗВ}/lines/{id}/rfq` | служебка/задача снабженцу; заказы поставщикам — бывшая M4 | Δ ERP-14 |
| **Расчёт готов → черновик КП директору** | `POST /calc/{ЗВ}/complete` | `POST /crm/quotes/{id}/submit-for-review/` при всех визах | ✓ + проверка виз Δ ERP-02 |
| Склад | `GET /stock` | остатки, резервы, заказы поставщикам, приёмка — **нет** (`supply`, `inventory` — заглушки) | Δ ERP-14 (бывшая M4) |
| Справочники | `GET /catalog/*` | `GET /catalog/products/`, `/catalog/offers/`, `/master-data/*`; бригады — новое | ✓ / Δ ERP-15 |
| Документация (ТЗ, чертежи) | `GET /files?scope=` | `GET /crm/generated-documents/`; файлы номенклатуры — новое | Δ ERP-15 |

### 1.6. Chats и Admin

| Экран / действие | BFF | CRM | ERP | Статус |
|---|---|---|---|---|
| Чаты проектов и команды, сообщения | `GET /chats`, `GET/POST /chats/{id}/messages` | — | новое `chats` | Δ ERP-08 |
| Внешний чат клиента (Telegram, почта) | `GET /chats/external`, `POST /chats/external/{lead}/messages {as: SELF|BOT|NOTE}` | `GET/POST /leads/{id}/messages`, `POST /leads/{id}/actions/note`, `POST /leads/{id}/assist` | — | ✓ (`as: BOT` — Δ CRM-07) |
| Сделать служебку из сообщения | `POST /chats/{id}/messages/{msg}/memo` | — | сервис EDS + чаты | Δ EDS-02, ERP-08 |
| Контакты | `GET /contacts` | `GET /team`, `GET /clients/{id}/contacts` | — | ✓ |
| Ролевая матрица | `GET /admin/roles` | — (матрица — файл `platform-rbac.yaml`) | — | ✓, редактирование — вопрос 8 |
| Оргструктура, карточка сотрудника, пригласить | `GET/PUT /admin/users/{id}`, `POST /admin/users/invite` | `GET/POST/PATCH /users`, `/users/{id}/invite` (провижининг в ERP с `role_codes` — FIX-63) | провижининг ✓ | Δ CRM-01 |
| Внешние интеграции (обзор «Требует внимания», карточки со статусом пятью уровнями) | `GET /admin/integrations` — сводит реестр `/admin/external-services`, `/system/status`, `/integrations/erp` и `/integrations/telegram`, `/models`, `/system/backups`, `/spend` | как в следующих строках | `/health` `externals[]` (M3-ERP-06, PR #129) | ✓ (BFF 0.7.0, W13-A1) |
| Внешние интеграции: ERP, Telegram, почта, реестр сервисов, модели ИИ, расходы, бэкапы, состояние | `/admin/integrations/{erp,telegram,smtp,services,models,spend,ai-spend,backups,system}*` — прокси с токеном сотрудника; чтение `admin: read`, изменения и пробы `admin: full` | `/integrations/{erp,telegram,smtp}*` (check, pair, rotate, token, channels, profile, test-send, log), `/admin/external-services*`, `/models*`, `/spend`, `/admin/ai-spend`, `/system/{status,backups}` | — | ✓ (BFF 0.7.0, W13-A1); разрывы CRM — `QUESTIONS.md` Q-W13-A1-2 |
| Журнал интеграций: подписчики шины, доставки и DLQ, входящие с ошибками, повторы | `GET /admin/bus`, `/admin/bus/deliveries`, `/admin/bus/inbox` (слияние трёх доменов, `sources`), `POST /admin/bus/{domain}/…/retry*`; только `admin: full` | `/api/v1/bus/*` (`integrations:read`, `integrations:write`) | `/api/v1/integration/bus/*/` (`team.manage`); EDS `/api/v1/bus/*` (`bus.manage`, вход — SSO `aud=eds`) | ✓ (BFF 0.9.0, W13-A2) |
| Тикеты от команды | `GET/POST /admin/tickets` | новое `tickets` | — | Δ CRM-05 |
| Компания (W13-A3, BFF 0.8.0): реквизиты и логотип, бланк и бренд, нумерация, условия КП, статьи расхода, шаблоны документов и писем, справочники, категории и запросы, НДС | `/admin/company*` (раздел `company.settings`; `GET`/предпросмотры — чтение, изменения — полный) | — | `accounts/companies/{id}/` (+ `upload-logo`, `delete-logo`, `document-profile/` + `preview`, `upload-logo`, `settings/`), `crm/numbering-scheme/` (+ `preview`), `crm/charge-templates/`, `crm/charge-types/`, `crm/document-templates/*`, `settings/email-templates/`, `master-data/{countries,currencies,units,delivery-basis}/`, `catalog/categories/`, `catalog/category-requests/` (+ `approve`, `reject`), `system-settings/`; id компании — `setup/status/` (`own_company_id`) | ✓, разрывы — Q-W13A3-1 |

## 2. Шкала 7 шагов: как BFF выводит шаг

До T5 FSM ERP не переименовывается. BFF вычисляет шаг из сделки и её документов; правило одно для заявок
процесса v3 и заявок, начатых до Платформы.

| Шаг | Условие (проверяется сверху вниз, первое истинное) |
|---|---|
| Отказ `LOST` | `Deal.stage = CLOSED_LOST` |
| Выполнено `DONE` | акт в статусе «Подписан» и все невыставленные/неотменённые счета оплачены; для старых заявок — стадия шва `won` (`integration/services/stages.py`) |
| Оплата `PAYMENT` | договор «Подписан» (v3 — журнал договора; старые — `Contract.is_fully_signed`) |
| Договор `CONTRACT` | КП принято клиентом (`Quote.status = APPROVED`, сделка `CONTRACT_SIGNED`) |
| КП `QUOTE` (подстатусы) | КП в `PENDING_TRADE_REVIEW`/`PENDING_APPROVAL`/`READY_TO_SEND` → `DRAFT`; `SENT` → `SENT` |
| Расчёт `CALCULATION` | v3 — резолюция утверждена; старые — сделка `SOURCING`/`CALCULATING` или КП `DRAFT` |
| Резолюция `RESOLUTION` | v3 — письмо зарегистрировано, резолюции нет; старые — шаг пропущен, отмечается «до Платформы» |
| Заявка `REQUEST` | иначе (`DRAFT`, `RFQ_OPEN`) |

Отличие от FSM ERP, которое BFF скрывает: ERP ставит `CONTRACT_SIGNED` при принятии КП и `CLOSED_WON` при подписи
договора; Платформа показывает «Договор» и «Оплата» по документам. Автосчёт на `CLOSED_WON`
(`auto_invoice_on_closed_won`) для процесса v3 должен срабатывать по подписи договора, а не по стадии — Δ ERP-03.

## 3. Статусы

### 3.1. Лид (CRM → Платформа)

| Платформа | CRM |
|---|---|
| Новый | `new` |
| В диалоге | `engaged`, `qualified` при `owner_mode = bot` |
| Просит КП | `handoff`/`in_progress` с причиной эскалации `price_or_contract_asked` или фактом квалификации «просит цену» — Δ CRM-02 (вычисляемое поле `platform_status` в CRM) |
| Без ответа | `unresponsive` или истёк SLA передачи |
| Клиент | `customer` |
| (Отказ) | `lost` — во вкладке «Все» с тегом |

### 3.2. Документы (ERP → Платформа, SPEC-v3 §2.4)

| Документ | ERP сейчас | Платформа |
|---|---|---|
| КП | `DRAFT`, `PENDING_TRADE_REVIEW`, `PENDING_APPROVAL`, `READY_TO_SEND`, `SENT`, `APPROVED`, `REJECTED`, `EXPIRED` | Черновик (отправка заблокирована) ← DRAFT…READY_TO_SEND; На доработке ← возврат директором; Одобрено ← одобрено до отправки (ИСХ-номер); Отправлено ← SENT; Принято клиентом ← APPROVED; Отклонено клиентом ← REJECTED; Срок истёк ← EXPIRED |
| Договор | `DRAFT`, `PENDING_CLIENT`, `PENDING_MANAGER`, `SIGNED`, `CANCELLED` | Проект → Согласован клиентом → Выставлен у оператора → Подписан (скан) / Отклонён — из нового журнала договора (Δ ERP-03); старые договоры: `SIGNED` → «Подписан», остальное → «Проект» |
| Счёт | `DRAFT`, `ISSUED`, `PARTIAL`, `PAID`, `OVERDUE`, `CANCELLED` | Выставлен ← ISSUED; Платёжка получена ← есть неподтверждённая `PaymentConfirmation` (Δ ERP-04); Частично оплачен ← PARTIAL; Оплачен ← PAID; Просрочен ← OVERDUE (Δ ERP-06 — сейчас не ставится) |
| Акт | `DRAFT`, `ISSUED`, `SIGNED`, `CANCELLED` | Проект ← DRAFT; Выпущен ← ISSUED; Подписан (скан) ← SIGNED; Возвращён с причиной ← DRAFT + `rejection_reason` (FIX-62) |
| Входящее письмо, служебная записка | — | новые статусы SPEC-v3 §2.4 в сервисе EDS |

### 3.3. Для клиента

Тексты SPEC-v3 §2.5 — один файл шаблонов на трёх языках для бота (CRM `settings.texts`), кабинета (i18n Cabinet)
и писем (шаблоны ERP). Источник ключей — `packages/contracts/client-statuses.yaml` (новый, PLT-02); проверка
равенства ключей в трёх системах — тест, как у `docs/kb`.

## 4. Роли

> **ADR-0012:** таблица ниже — предустановки фазы P1. С волны 9 роли — данные: права ERP и CRM вычисляются из матрицы
> роли по каталогу `platform-rbac.yaml` (у каждого раздела — отображение в права бэкендов), `role_codes` для сотрудников
> Платформы не используются.

| Роль Платформы | CRM | ERP `role_codes` (FIX-63) | Дополнительные права ERP | Примечание |
|---|---|---|---|---|
| `MANAGER` | `manager` | `VIEWER` | `deal.manage` (создание заявки через шов) | не видит себестоимость и маржу (в ERP нет `quote.view_cost_margin`) |
| `DIRECTOR` | `viewer` | `HEAD` | — | одобрение КП (маршрут EDS, EDS-03; в ERP — визы `quote.review`), резолюции, служебки |
| `SUPPLY` | `viewer` | `CATALOG_SUPPLY`, `FULFILLMENT` | `quote.build`, `quote.edit_pricing` | расчёт товаров, склад, отгрузки |
| `ENGINEER` | `viewer` | `FULFILLMENT` | `quote.build` (без `quote.view_cost_margin`) | расчёт услуг, этапы, акты к подготовке |
| `ACCOUNTANT` | `manager` (ответы клиенту во внешнем чате; разделы CRM скрывает матрица) | `FINANCE` | `contract.manage`, `fulfillment.act` | договоры, счета, оплаты, акты |
| `ADMIN` | `admin` | — (суперпользователь ERP только для настроек бизнеса) | — | не ведёт процессы |

`CALCULATION` (Расчёт) для новых сотрудников не выдаётся. Каждый сотрудник — пользователь CRM с
`platform_access = ["crm","erp"]` (CRM — источник истины по людям); при нескольких ролях базовая роль CRM — старшая
(`admin` > `manager` > `viewer`). С R-1 (ADR-0012) роли Платформы — данные CRM, права CRM сотрудника — политики casbin его ролей (`pr:<id>`),
базовые роли для проверки прав не используются — и у системной «Администратор» тоже (R3-D-2, R-1c): её права CRM — раздел `admin`
каталога, лиды, клиенты и сделки — второй ролью; базовая `admin` остаётся признаком «последний админ»; суперпользователь ERP — только системная роль с кодом `ADMIN` (до C2), пользовательской роли с `admin: full` — права разделов (Q-R1c-1 п. 5). **Источник истины карты — `packages/contracts/platform-rbac.yaml`**; изменения — PR с тестом матрицы.

## 5. Номера

| Номер | Где формируется | Статус |
|---|---|---|
| L-NNNN | BFF из `leads.id` | ✓ |
| ЗВ-ГГГГ-NNN / ПР-ГГГГ-NNN | ERP: новое поле `Deal.number` (NNN общий, префикс по шагу) | Δ ERP-09 |
| ВХ-NNN/ГГ, ИСХ-NNN/ГГ, СЗ-ГГГГ/NNN | ERP `DocumentNumberingScheme` с новыми типами | Δ ERP-09 |
| КП-ГГГГ/NNN vN, ДОГ-, СЧ-, АКТ- | ERP `next_document_number` — схема компании задаётся шаблонами SPEC-v3 §2.2 | ✓ настройкой нумерации |
| ЗП-ГГГГ-NNN | ERP — вместе с заказами поставщикам | Δ ERP-14 |

## 6. Перенаправления старых адресов (T4)

| Старый адрес | Новый |
|---|---|
| `crm.railtech.uz/inbox` | `/crm/messages` |
| `crm.railtech.uz/leads`, `/leads/:id` | `/crm/leads`, `/crm/leads/L-:id` |
| `crm.railtech.uz/clients`, `/clients/:id` | `/crm/clients`, `/crm/clients/:id` |
| `crm.railtech.uz/kb`, `/gaps`, `/templates` | `/crm/kb` |
| `crm.railtech.uz/users`, `/integrations`, `/models`, `/system`, `/external-services`, `/backups`, `/audit` | `/admin/org`, `/admin/integrations` |
| `crm.railtech.uz/dashboard`, `/spend` | `/dashboard/summary` |
| `erp.railtech.uz/crm-deals`, `/request-detail/:id` | `/crm/requests`, `/eds/projects/:номер` (BFF находит номер по id) |
| `erp.railtech.uz/deal-quote/:id` | `/erp/calc/:номер` |
| `erp.railtech.uz/contracts`, `/invoices`, `/payments`, `/acts`, `/fulfillments` | `/eds/documents?type=…`, `/eds/payments`, `/erp/stock` |
| `erp.railtech.uz/products…`, `/catalog-…` | `/erp/catalog` |
| `erp.railtech.uz/settings` | `/admin/integrations` (бизнес-настройки компании — раздел Admin «Компания», `/admin/company`, W13-A3) |
| остальное | `/dashboard/queue` |

## 7. Разрывы в бэкендах (что нужно добавить)

Каждый разрыв — отдельная задача с контрактом в том же PR. Фаза — из `docs/history/platform/05-plan.md`.

### ERP

| ID | Что | Фаза |
|---|---|---|
| ERP-02 | `LineApproval` (строка, роль, сотрудник, время, заметка); правило «расчёт готов только при всех визах» в `submit_for_review` для процесса v3 | P2 |
| ERP-03 | статусы и журнал договора (Проект → Согласован клиентом → Выставлен у оператора → Подписан (скан) / Отклонён), скан — файл; «подпись кликом» для процесса v3 выключена; автосчёт на предоплату по подписи договора | P3 |
| ERP-04 | `PaymentConfirmation` (файл, источник CABINET/BOT/MANUAL, сумма, дата, кто подтвердил); связь с `record-payment`; «запросить платёжку» — событие для бота и письмо | P3 |
| ERP-06 | задача по расписанию: `OVERDUE` по сроку, событие `invoice.overdue`; включить `crm.send_payment_reminders` в расписание | P3 |
| ERP-07 | признак `Deal.process = v3`; запрет переходов в обход резолюции, виз и одобрения для таких заявок в сервисном слое | P2 |
| ERP-09 | `Deal.number` (ЗВ/ПР), типы нумерации ВХ, ИСХ, СЗ; поиск сделки по номеру и названию (`search_fields` у списка сделок) | P2 |
| ERP-16 | уведомления сотрудника: `unread_count` и признак прочитанного в выдаче (для колокольчика без перебора страниц); лента «Сегодня» для сотрудника — события компании по правам, а не `activity-logs` только администратору | P2 |
| ERP-17 | часовой пояс компании в API (сейчас BFF берёт `Asia/Tashkent` константой) | P2 |
| ERP-10 | публикация доменных событий для BFF — через шину `rt_bus` (ADR-0014; задачи B1–B8 стратегии), не Redis Streams | B |
| ERP-11 | атомарное «одобрить и отправить» КП: виза директора, ИСХ-номер, каналы (бот, кабинет, почта), одна транзакция | P2 |
| ERP-12 | «Напомнить клиенту» по КП и напоминание за 2 дня до истечения срока — событие для бота | P3 |
| ERP-13 | загрузка подписанного скана акта сотрудником; статусы акта SPEC-v3 §2.4 (вместе с FIX-62) | P3 |
| ERP-14 | склад и закупки (бывшая веха M4): остатки как сумма движений, резерв под проект, заказы поставщикам ЗП, приёмка, отгрузки по строкам, ожидаемые даты; до этого Расчёт показывает наличие из предложений поставщиков | P4 (минимум резерва — P3, вопрос 9) |
| ERP-15 | бригады и исполнители услуг; файлы номенклатуры и проектов (ТЗ, чертежи, сертификаты) | P4 |

### EDS (сервис `apps/eds`, ADR-0015; создаётся на этапе C1)

Статус контракта (волна 12, задача E1): **контракт есть** — `packages/contracts/openapi/eds.yaml` 0.1.0, события
`packages/contracts/events/eds/*.v1.json` и `events/erp/quote.ready_for_approval.v1.json`, подписки `bus/subscriptions.yaml`,
права `platform-rbac.yaml` (`backend.eds`); объяснение — [`CONTRACTS.md`](CONTRACTS.md) §10. Код — задачи E2–E5
[`wave12-eds-c1.md`](../runbooks/wave12-eds-c1.md); сторона ERP (EDS-01, EDS-03) реализована задачей E5 — CONTRACTS §10.6.

| ID | Что | Фаза | Контракт |
|---|---|---|---|
| EDS-01 (бывш. ERP-01) | сервис EDS: `Letter`, `Resolution` (исполнители, срок, мин. маржа), статусы письма; эндпоинты списка, карточки, резолюции, возврата, отклонения; задание исполнителям; события `letter.registered`, `letter.resolved` | P2 | есть: `eds.yaml` `/api/v1/letters*`; `eds.letter.registered/resolved/returned/rejected.v1` (ERP ← `resolved`, `rejected`); **реализовано в ERP (E5):** задание расчёта `CalcTask`, стадия `CALCULATING`, отказ → `CLOSED_LOST` с причиной |
| EDS-02 (бывш. ERP-05) | `ServiceMemo` и решения, маршрут «директор → бухгалтер, если сумма», создание из сообщения чата; документы «Заявление», «Отчёт», «Письмо» как типы документов EDS | P3 | есть: `eds.yaml` `/api/v1/documents*`, `/approvals*`, `/registry*`, `/files*`; `eds.document.registered/archived.v1`, `eds.approval.requested/decided.v1`; **ERP не участвует** (решения по документам EDS ERP не применяет, E5) |
| EDS-03 | маршрут согласования КП: ERP публикует `quote.ready_for_approval`, EDS ведёт маршрут и публикует `approval.decided`; ERP применяет решение (вместо своей цепочки виз директора) | C–D | есть: `erp.quote.ready_for_approval.v1` → EDS; `eds.approval.decided.v1` (`outgoing_number`, `channels`) → ERP; чек-лист и снимок КП — `eds.yaml` `Approval`; **реализовано в ERP (E5):** публикация после виз, решение на КП (ИСХ-номер, на доработку, отклонено); своей цепочки одобрения директором и права финального утверждения КП в ERP нет |

### Чаты (домен уточняется на этапе D)

| ID | Что | Фаза |
|---|---|---|
| ERP-08 | чаты (домен — коммуникации CRM по ADR-0015, окончательно — этап D): чат проекта (создаётся с заявкой, архивируется на «Выполнено»/«Отказ»), командные и личные чаты, сообщения, вложения, системные сообщения о событиях проекта, поиск по тексту | P3 |

### CRM

| ID | Что | Фаза |
|---|---|---|
| CRM-01 → R-1/R-1b | роли Платформы как данные (`platform_roles`, `user_platform_roles`, `version`), выдача `platform_role_ids`, провижининг ERP вычисленными правами; `GET /me` отдаёт `platform_role_refs` | P1 → волна 9 |
| CRM-02 | вычисляемый статус лида для Платформы (`platform_status`: new, dialog, wants_quote, no_answer, client) и фильтр по нему | P2 |
| CRM-03 | действие «Создать заявку»: из любой активной стадии лида и из клиента, без требования e-mail, с полями письма и срочности; передача в ERP с `letter`, `process = v3`; приглашение в канал контакта (`invite.requested`, бывшая FIX-68) и кнопка «Открыть кабинет» в боте | P2 |
| CRM-04 | уведомления сотрудникам из событий CRM (SLA лида, сбой интеграции, новое обращение) — хранение и API чтения | P3 |
| CRM-05 | тикеты от команды | P4 |
| CRM-06 | записка handoff (запрос, факты, причина, рекомендуемый шаг) в выдаче `GET /inbox` | P2 |
| CRM-07 | ответ «как бот» из внешнего чата (сообщение уходит от имени бота, в журнале — сотрудник) | P3 |
| CRM-01c | право читать сотрудников (`users:read`) по ролям Платформы: DIRECTOR — да, SUPPLY/ENGINEER — нет (базовая роль `viewer` его не даёт) | P1 (волна 8) |
| CRM-08 | `GET /inbox` с фильтром «мои» (`taken_by`, отложенные) на стороне CRM, вместо фильтрации в BFF | P2 |
| CRM-09 | итог провижининга в ERP в выдаче пользователя (`erp_sync`: ok/pending/error), повторная отправка приглашения без смены пароля | P2 |
| CRM-10 | канал администратора для системных оповещений (никогда в канал команды), подавление «мигания» сервиса | по решению владельца |

### Cabinet и портал ERP

| ID | Что | Фаза |
|---|---|---|
| CAB-01 | страница счёта: реквизиты, QR, «Я оплатил» + файл платёжки (портал: `POST /invoices/{id}/payment-doc`) | P3 |
| CAB-02 | проект договора: «Согласовать редакцию» / «Замечания» вместо «Подписать» для процесса v3 | P3 |
| CAB-03 | статусы для клиента из `client-statuses.yaml`; токены ui-tokens 0.2 | P3 |
| CAB-04 | уведомления в кабинете (колокольчик, непрочитанное) | P4 |
