# Карта интеграции: экраны → BFF → домены (CRM, EDS, ERP)
Статус: действует · Владелец: архитектор · Обновлено: 2026-10-28

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
| `GET /search?q=` | `GET /leads?q=`, `GET /clients?q=` | `GET /crm/analytics/search-documents/`; сделки — `GET /crm/deals/?search=` по номеру ЗВ/ПР (любой префикс, латиница), названию и компании (ERP-09 ✓, W16-D1-2) | частично; чаты — Δ ERP-08 |
| `GET /notifications`, `POST /notifications/read-all`, `POST /notifications/{id}/read` | Δ CRM-04 (уведомления сотрудникам из CRM) | `GET /notifications/`, `PATCH /notifications/mark_all_read/`, `PATCH /notifications/{id}/mark_read/` | ✓ ERP, Δ CRM |
| `GET /events` (SSE, фаза P4) | `GET /stream` | Δ ERP-10 (шина `rt_bus`, этап B) | Δ |
| `GET /menu-counters` (бейджи подменю всех модулей) | `GET /inbox`, `GET /service-requests` | счётчики по §1.2–1.5 | агрегат |

### 1.2. Dashboard

| BFF | Источники | Статус |
|---|---|---|
| `GET /queue` — строки «Что сделать сейчас» для всех ролей сотрудника | MANAGER: CRM `GET /inbox`, `GET /leads?stage=…`, `GET /service-requests`. DIRECTOR: письма без резолюции — **EDS `GET /letters?status=awaiting_resolution` ✓ (D1-6, BFF 0.25.0)**, `GET /crm/quotes/my-approval-queue/`, служебки, заявления и отчёты на моём шаге — **EDS `GET /approvals?mine=true&status=open&template=memo|application|report` ✓ (D1-6)**, проблемные проекты (вывод BFF). SUPPLY, ENGINEER: задания на расчёт по резолюции (Δ EDS-01, ERP-02). ACCOUNTANT: платёжки на подтверждение (Δ ERP-04), `GET /crm/invoices/?status=DRAFT`, договоры к выставлению (Δ ERP-03), служебки к оплате — **EDS `GET /approvals` на шаге бухгалтера ✓ (D1-6)**, просроченные счета (Δ ERP-06). ADMIN: тикеты (Δ CRM-05), CRM `GET /admin/external-services` с проблемами | частично ✓ |
| `GET /queue` — строка «Доработать» (`rework_document`, D1-6b) автору документа | EDS `GET /documents?mine=true&status=returned&kind=memo&kind=application&kind=report` (свои возвращённые документы) и карточка `GET /documents/{id}` (последнее решение «Вернуть»: кто и комментарий) — по токену `aud=eds`; EDS решает, чьи документы; без раздела `eds.memo.create` EDS не вызывается; EDS не ответил — `sources.eds = unavailable`, остальная очередь на месте. Строка ведёт в `/eds/new?draft=<id>` («Продолжить» D1-5), исчезает после повторной отправки; подсказка SSE — `approval.decided` → `queue` | ✓ |
| `GET /queue/counters` | то же, только числа | частично ✓ |
| `GET /activity/today` (вкладка «Сегодня») | ERP `GET /crm/activity-logs/`, `GET /crm/timeline/`; CRM `GET /audit` | ✓ |
| `GET /summary` (воронка, застрявшие, дебиторка, причины отказов) | CRM `GET /dashboard`, `GET /deals/summary`; ERP `GET /crm/analytics/dashboard/`, `GET /crm/analytics/time-to-first-quote/` | ✓ (застрявшие по 7 шагам — вывод BFF) |

**EDS в очереди, счётчиках и поиске (D1-6, BFF 0.25.0).** `Feed` читает EDS тем же обменом токена `aud=eds`, что экраны D1-3…D1-5: по виду работы
секции `queue` каталога (`resolve_letter` — `eds.inbox` full, `approve_memo` — `eds.memo.approve` full, `pay_memo` — `eds.payments` full) и только у ролей с разделами EDS
(`EDS_SECTIONS`); что вернул EDS по токену сотрудника, то и строки — BFF прав EDS не вычисляет. Карточки `letters_without_resolution` и `memos_to_approve` и бейджи
`eds.inbox`, `eds.approvals` показываются, только если EDS ответил. `Sources.eds` — необязательное: `unavailable` — плашка «Не загрузились письма и документы: раздел
«Документы» не ответил», остальное показано; `not_applicable` — EDS не пустил сотрудника (403 обмена или запроса). Поиск ⌘K: реестр EDS `GET /registry?q=` (номера ВХ, ИСХ,
КП, СЗ, ЗЯ, ОТ и тема), запись показывается, если раздел каталога роли открывает её вид (ВХ — `eds.inbox`, КП — `eds.drafts`, СЗ/ЗЯ/ОТ — `eds.memo.approve` или `eds.memo.create`).
События EDS (`uz.railtech.eds.*`) дают подсказки `queue`, `counters`, `notifications`: письмо, поступившее в EDS, видно директору в «Моей очереди» без перезагрузки. Своих возвращённых
документов (автору) в очереди нет — отдельная задача D1-6b; колокольчика по событиям EDS нет — B-D16-1; колокольчик по КП из ERP открывает сделку — B-D16-2.

**Ссылки объектов (`ObjectRef.path`) в очереди, поиске и уведомлениях (D1-6, без изменения контракта).** Строка очереди «ждут ответа клиенту»
(`answer_lead`, `take_lead`: передача бота, новое сообщение, лид без менеджера) ведёт в диалог «Клиенты · Ждут ответа» —
`/crm/messages?lead=L-NNNN`; тот же лид в поиске — карточка в «Все лиды» (`/crm/leads?lead=…&panel=open&tab=card`). Письмо, КП на одобрении и служебка —
`/eds/inbox|drafts|approvals/<номер или id>?panel=open&tab=resolution|approve|agree`; если BFF прислал адрес короче, Платформа достраивает окно и вкладку
(`modules/objectLinks.ts`). Договор, счёт, акт и расчёт остаются разделами-заглушками («Где сделать», мост H1).

### 1.3. CRM

| Экран / действие | BFF | CRM | ERP | Статус |
|---|---|---|---|---|
| Все лиды, вкладки и фильтры | `GET /leads` | `GET /leads` (`platform_status` в ответе; фильтры `platform_status=`, `overdue=`) | — | ✓; статусы Платформы — §3.1, CRM-02 ✓ (W16-D1-2) |
| Карточка лида в боковом окне | `GET /leads/{L-NNNN}` | `GET /leads/{id}`, `/messages`, `/notes`, `/decisions` | — | ✓ |
| Забрать, Ответить, Вернуть боту, Отказ | `POST /leads/{no}/take` и т. п. | `POST /leads/{id}/actions/take|return_to_bot|close_lost`, `POST /leads/{id}/messages` | — | ✓ |
| **Создать заявку** | `POST /leads/{no}/request {company{name,inn}, contact{…channels}, summary, letter_file?, urgency}` (D1-2b) | `POST /leads/{id}/actions/create_request {client_id \| company{name, inn}, contact{contact_id \| full_name, phone?, email?, use_lead_telegram}, summary, urgency, letter_file_id?, consent?}` — из любой активной стадии, e-mail не обязателен; задача после коммита → `POST /clients/handoff` (клиента ещё нет в ERP) и `POST /clients/{id}/requests` шва 0.9.0 | сделка процесса `v3` с номером ЗВ, срочностью, менеджером заявки (B-008); `request.created` → EDS: письмо ВХ директору со срочностью и файлом письма (файл — EDS `POST /files` до заявки) | ✓ бэкенды (W16-D1-2: CRM-03, ERP-09); BFF и экран — D1-2b; чат проекта — Δ ERP-08 |
| Все сообщения / «Ждут ответа» (передачи от бота с запиской, SLA, «Забрать», лента, ответ «От себя / Заметка команде», шаблоны, подсказка, вложения, живые обновления) | `GET /crm/messages`, `GET /crm/messages/{lead}`, `/thread`, `/attachments/{m}/{i}`, `POST /crm/messages/{lead}/take|reply|note|assist|return-to-bot`, `GET /crm/reply-templates`; подсказка SSE `messages` | `GET /inbox` (с `handoff_note`), `GET /leads/{id}`, `/messages`, `/notes`, `/team`, `/leads/{id}/messages/{m}/attachments/{i}`, `POST /leads/{id}/messages` (`client_message_id`), `/actions/take|note|return_to_bot`, `/assist`, `GET /reply-templates`; событие `lead.message_added` | — | ✓ (D1-1, BFF 0.22.0; CRM-06 закрыт) |
| Все клиенты, карточка 360° | `GET /clients`, `GET /clients/{id}` | `GET /clients`, `/clients/{id}`, `/contacts`, `/erp-receivables`, `/documents` | шов: `GET /companies/{id}/summary`, `/companies/{id}/deals`, `/deals/{id}/documents` | ✓ |
| Новая заявка для клиента | `POST /clients/{id}/request` (D1-2b) | `POST /clients/{id}/actions/create_request` (то же тело) | `POST /clients/{crm_client_id}/requests` шва 0.9.0 | ✓ бэкенды (W16-D1-2) |
| Все заявки (ЗВ/ПР, 7 шагов) | `GET /requests` | — | `GET /crm/deals/` + документы | ✓, шаг — §2 |
| Каналы связи | `GET /channels` | `GET /integrations/telegram`, `GET /settings` (тексты), `GET /integrations/smtp` | — | ✓ |
| База знаний: документы, поиск «Что найдёт бот», карточка и фрагменты | `GET /crm/kb/documents`, `GET /crm/kb/documents/{id}[/chunks]`, `POST /crm/kb/search`; изменения — `PATCH /crm/kb/documents/{id}`, `POST /crm/kb/documents/{id}/reingest`, `POST /crm/kb/documents` (multipart, тело CRM не разбирается), `POST /crm/kb/documents/manual` | `/kb/documents*`, `/kb/search` | — | ✓ (BFF 0.11.0, W13-A5); чтение — `crm.leads` или `admin`, правка — `admin: full` |
| База знаний: пробелы, продукты | `GET /crm/kb/gaps`, `POST /crm/kb/gaps/{id}/{resolve,ignore,reopen}`, `GET /crm/kb/products` | `/kb/gaps*`, `/kb/products` (чтение требует `leads:read`) | — | ✓ (W13-A5); разрыв CRM-11 |
| Песочница бота | `POST /crm/sandbox/messages`, `POST /crm/sandbox/reset` | `/sandbox/messages`, `/sandbox/reset` (`sandbox:use`; платно, в «Расходах» с пометкой «тест») | — | ✓ (W13-A5), `admin: full` |

### 1.4. EDS

| Экран / действие | BFF | ERP (если не указано) | Статус |
|---|---|---|---|
| Входящие, карточка письма | `GET /eds/letters`, `GET /eds/letters/{id или ВХ}`, вложение `GET /eds/letter-files/{id}` (BFF 0.16.0) | сервис EDS (`GET /letters`, `GET /letters/{id}`, по номеру — `GET /registry?number=`, файлы `GET /files/{id}`); шаг и название заявки — ERP `GET /crm/deals/{erp_deal_id}/` по ссылке письма, ERP не ответил — `sources.erp = unavailable` | ✓ **D1-3 (волна 16)** |
| **Утвердить резолюцию** / Вернуть менеджеру / Отклонить | `POST /eds/letters/{id}/resolution {text, assignees[{id, zone}], due, min_margin_pct}`; `/return {comment}`; `/reject {reason}`; кандидаты — `GET /eds/resolution/assignees` (по разделам каталога, не по кодам ролей) | сервис EDS (`POST /letters/{id}/resolution|return|reject`); ERP узнаёт о решении по шине (`letter.resolved/rejected` → задание расчёта, `CLOSED_LOST`); BFF в ERP за решением не ходит | ✓ **D1-3 (волна 16)**; кандидаты — CRM `GET /team?section=&level=full` по вызову на зону, зону исполнителя проверяет EDS (`assignee_zone_mismatch`) — D1-8, Q-D1-3-1 п. 1 закрыт |
| Черновик КП, карточка | `GET /eds/quotes` (список: «на моём шаге» / все), `GET /eds/quotes/{id маршрута или КП-2026/115}` (шаги, чек-лист с датой и автором, состав и итоги, заявка, письмо, каналы; внутренний блок `internal` — себестоимость, маржа, порог, сроки — только с группой `cost_margin`) (BFF 0.24.0) | маршрут «КП» EDS (`GET /approvals?template=quote`, `GET /approvals/{id}`, номер — `GET /registry?number=&kind=quote`); состав и итоги — ERP `GET /crm/quotes/{id}/`, заявка — `GET /crm/deals/{id}/`, контакт клиента — `GET /accounts/contacts/{id}/`; письмо — EDS `GET /letters?q=`; ERP не ответил — `sources.erp = unavailable`, карточка без строк | ✓ **D1-4 (волна 16)**; условия оплаты и срок цены поставщика — B-076, состав КП не из снимка — B-077 |
| **Одобрить КП → отправить клиенту** (каналы) | `POST /eds/quotes/{id}/decision {decision: approve, channels[]}` — раздел `eds.drafts` full; без выбранных каналов кнопка «Одобрить КП → в Исходящие»; неактивна с подписью, какой пункт чек-листа не зелёный или что нет данных КП из ERP | EDS `POST /approvals/{id}/decision`: чек-лист проверяет EDS (визы и маржа блокируют — 409 `checklist_not_green`; «срок» — предупреждение, КП одобряется с отметкой «с опозданием», C1-G-1), присваивает ИСХ-номер; ERP по `approval.decided` сама отправляет КП клиенту по доступным из выбранных каналов (ERP-11: проверка канала на сервере, недоступные и сбои — в `send_report` с причиной и уведомлением менеджеру); без каналов — «Готово к отправке», отправляет менеджер заявки (`quote.send`, C1-G-4) | ✓ экран D1-4 (BFF 0.24.0); ✓ ERP-11 (W16-D1-2) |
| Вернуть на доработку | `POST /eds/quotes/{id}/decision {decision: return, comment}` (комментарий обязателен — 422 в BFF до EDS) | EDS `POST /approvals/{id}/decision`; новая версия КП — новое событие ERP | ✓ **D1-4 (волна 16)** |
| Исходящие, «Напомнить клиенту» | `GET /outbox`, `POST /quotes/{КП}/remind` | `GET /crm/quotes/?status=SENT…`; напоминание — событие для бота | Δ ERP-12 |
| Все проекты, карточка проекта | `GET /projects`, `GET /projects/{ПР}` | `GET /crm/deals/{id}/`, `/documents/`, `GET /crm/contracts|invoices|acts|fulfillments/?deal=` | ✓ |
| Договор: на согласование редакции, выставлен у оператора, прикрепить скан | `POST /contracts/{ДОГ}/status {status, scan_upload_id?}` | `upload-signed/` есть; статусы и журнал — новое | Δ ERP-03, портал Δ CAB-02 |
| Счета и оплаты, вкладки | `GET /invoices?tab=` | `GET /crm/invoices/`, `GET /crm/payments/` | ✓ (платёжки — Δ ERP-04, просрочка — Δ ERP-06) |
| **Подтвердить оплату** / Частичная / Запросить платёжку | `POST /invoices/{СЧ}/confirm-payment {amount, date}`; `POST /invoices/{СЧ}/request-payment-doc` | `POST /crm/invoices/{id}/record-payment/` ✓; связь с платёжкой и запрос платёжки — новое | Δ ERP-04 |
| Акт: выпустить, прикрепить скан, возврат | `POST /acts/{АКТ}/…` | `POST /crm/invoices/{id}/generate-act/`, `/acts/{id}/reissue/`, `/remind/`; загрузка скана сотрудником — новое; событие `act.returned` — FIX-62 | Δ ERP-13 |
| На согласовании, служебная записка | `GET /eds/memo-approvals` (на моём шаге / все), `GET /eds/memo-approvals/{id или СЗ-2026/014}`, `POST /eds/memo-approvals/{id}/decision {decision: approve\|return\|reject, comment}` — раздел `eds.memo.approve` full, чтение также у `eds.memo.create` (автор видит свой документ) | EDS `GET /approvals?template=memo,application,report`, `GET /documents/{id}`, `POST /approvals/{id}/decision`; маршрут «директор → бухгалтер, если сумма» ведёт EDS; вложения — `GET /eds/document-files/{id}` | ✓ **D1-4 (волна 16)** (EDS-02); шаг бухгалтера (`payments.confirm`) решает держатель `eds.payments` full — «Принять к оплате» / «Вернуть» |
| Создать документ (служебка, заявление, отчёт, письмо) | `POST /eds/documents {kind, subject, text, amount?, due_date?, file_ids, erp_deal_id?, recipient?, submit}`; сохранить черновик — `PUT /eds/documents/{id}`; вложения — `POST /eds/document-files`, `GET /eds/document-files/{id}`; связь с проектом — `GET /eds/deal-options?q=` | EDS `POST /documents`, `PATCH /documents/{id}` (eds.yaml 0.4.0), `POST /documents/{id}/submit`, `POST /files`; поиск заявки — сделки ERP (как сквозной поиск); бланк, PDF и шаблоны (`GET /crm/document-templates/`) — волна D-DOC | ✓ (BFF 0.17.0, D1-5): простой текст; письмо — `letter_out`, нужен `eds.inbox: full`; «Кому» — директор, выбор адресата — Q-D15-1 |
| Все документы | `GET /eds/documents?scope=mine\|all&kind=&status=&cursor=`; карточка — `GET /eds/documents/{id}` (шаги маршрута из `GET /approvals/{id}`) | «Мои» — EDS `GET /documents?mine=1`; «Все» — EDS `GET /registry` (письма — только при `letters.read`, КП, служебные, заявления, отчёты; чужие черновики не видны — D1-10, реестр не шире прав на вид документа; вкладка без прав — пусто, не ошибка); договоры, счета и акты — когда EDS начнёт вести их проекции | ✓ частично (BFF 0.17.0, D1-5): «Мои» и реестр EDS; договоры, счета, акты — позже |

### 1.5. ERP

| Экран / действие | BFF | ERP | Статус |
|---|---|---|---|
| Заявки в расчёте, Мои расчёты | `GET /erp/calc/requests?mine=` | `GET /calc/tasks/?mine=&scope=` (D2-1): заявки с заданием расчёта, три индикатора виз, исполнители резолюции | ✓ (BFF 0.24.0, D2-1) |
| Расчёт по заявке, строки | `GET /erp/calc/{ЗВ}` (заявку по номеру BFF находит в лёгком справочнике `GET /calc/deals/?number=`, номер — `Deal.number`) | `GET /calc/{deal_id}/`: задание (проекция резолюции), КП расчёта, строки с зоной, складом (своё предложение) и лучшим поставщиком, итоги без НДС, готовность | ✓ (D2-1; ячейка и резерв — Δ ERP-14) |
| Начать расчёт, добавить, изменить, удалить строку | `POST /erp/calc/{ЗВ}/start`, `POST …/lines`, `PATCH\|DELETE …/lines/{id}` | `POST /calc/{deal_id}/start/`, `/lines/`, `/lines/{item_id}/` — правит держатель права зоны строки (`quote.visa_goods`, `quote.visa_services`), правка снимает визу | ✓ (D2-1) |
| Сопоставить с каталогом, ИИ-разбор (предложение) | `GET /erp/calc/catalog?q=`, `POST /erp/calc/{ЗВ}/parse` + `GET /erp/calc-jobs/{job}` | `GET /calc/catalog/`, `POST /calc/{deal_id}/parse/` (очередь ИИ, без записи) + `GET /sourcing/ai-status/{task}/` | ✓ (D2-1) |
| **Подтвердить** (виза строки по зоне) | `POST /erp/calc/{ЗВ}/lines/{id}/visa` | `POST /calc/{deal_id}/lines/{item_id}/visa/`, `CalcLine` (виза: кто, зона, время) | ✓ (D2-1) |
| Запросить цену у поставщика | `POST /calc/{ЗВ}/lines/{id}/rfq` | служебка/задача снабженцу; заказы поставщикам — бывшая M4 | Δ ERP-14 |
| **Расчёт готов → черновик КП директору** | `POST /erp/calc/{ЗВ}/ready` | `POST /calc/{deal_id}/ready/`: только со всеми визами строк (409 `VISAS_MISSING`), затем гейты отправки и `quote.ready_for_approval` в EDS (визы — подписи строк) | ✓ (D2-1) |
| Склад | `GET /stock` | остатки, резервы, заказы поставщикам, приёмка — **нет** (`supply`, `inventory` — заглушки) | Δ ERP-14 (бывшая M4) |
| Справочники | `GET /catalog/*` | `GET /catalog/products/`, `/catalog/offers/`, `/master-data/*`; бригады — новое | ✓ / Δ ERP-15 |
| Документация (ТЗ, чертежи) | `GET /files?scope=` | `GET /crm/generated-documents/`; файлы номенклатуры — новое | Δ ERP-15 |

### 1.6. Chats и Admin

| Экран / действие | BFF | CRM | ERP | Статус |
|---|---|---|---|---|
| Чаты проектов и команды, сообщения | `GET /chats`, `GET/POST /chats/{id}/messages` | — | новое `chats` | Δ ERP-08 |
| Внешний чат клиента (Telegram, почта) | `GET /chats/external`, `POST /chats/external/{lead}/messages {as: SELF|BOT|NOTE}` | `GET/POST /leads/{id}/messages`, `POST /leads/{id}/actions/note`, `POST /leads/{id}/assist` | — | переписка с клиентом «От себя / Заметка команде» — в «Клиенты · Ждут ответа» (D1-1, `/crm/messages*`); экран Chats · «С клиентами» — позже, поверх тех же маршрутов; `as: BOT` — Δ CRM-07 |
| Сделать служебку из сообщения | `POST /chats/{id}/messages/{msg}/memo` | — | сервис EDS + чаты | Δ EDS-02, ERP-08 |
| Контакты | `GET /contacts` | `GET /team`, `GET /clients/{id}/contacts` | — | ✓ |
| Сотрудники по разделу каталога (исполнители зон резолюции, позже визы D2) | `GET /eds/resolution/assignees` | `GET /team?section=<раздел>&level=full|read` (`users:read`; id, имя, инициалы, должность) | — | ✓ (D1-8; разрыв B-007 закрыт) |
| Журнал аудита, журнал роли (W13-A6) | `GET /admin/audit`, `GET /admin/roles/{id}/journal` | `GET /audit` (`audit:read`) | ✓ | — |
| Сброс пароля по почте, уведомления профиля (W13-A6) | `POST /admin/users/{id}/reset-password/email`, `/me/notification-settings`, `/me/test-notification` | `POST /users/{id}/reset-password/email`, `GET/PATCH /me`, `POST /me/test-notification` | — | — |
| Ролевая матрица | `GET /admin/roles` | — (матрица — файл `platform-rbac.yaml`) | — | ✓, редактирование — вопрос 8 |
| Оргструктура, карточка сотрудника, пригласить | `GET/PUT /admin/users/{id}`, `POST /admin/users/invite` | `GET/POST/PATCH /users`, `/users/{id}/invite` (провижининг в ERP с `role_codes` — FIX-63) | провижининг ✓ | Δ CRM-01 |
| Внешние интеграции (обзор «Требует внимания», карточки со статусом пятью уровнями) | `GET /admin/integrations` — сводит реестр `/admin/external-services`, `/system/status`, `/integrations/erp` и `/integrations/telegram`, `/models`, `/system/backups`, `/spend` | как в следующих строках | `/health` `externals[]` (M3-ERP-06, PR #129) | ✓ (BFF 0.7.0, W13-A1) |
| Внешние интеграции: ERP, Telegram, почта, реестр сервисов, модели ИИ, расходы, бэкапы, состояние | `/admin/integrations/{erp,telegram,smtp,services,models,spend,ai-spend,backups,system}*` — прокси с токеном сотрудника; чтение `admin: read`, изменения и пробы `admin: full` | `/integrations/{erp,telegram,smtp}*` (check, pair, rotate, token, channels, profile, test-send, log), `/admin/external-services*`, `/models*`, `/spend`, `/admin/ai-spend`, `/system/{status,backups}` | — | ✓ (BFF 0.7.0, W13-A1); разрывы CRM — `QUESTIONS.md` Q-W13-A1-2 |
| Почта — один отправитель ансамбля (W18A-P1, B-INB-6): SMTP, «Проверить связь», «Проверить отправку» с итогом словами, журнал доставки с источником (CRM, ERP, EDS) и назначением | `/admin/integrations/smtp*` (`getSmtpConnector`, `saveSmtpConnector`, `checkSmtp`, `sendSmtpTest`, `listMailLog` — `source`, `purpose`, `attachments`) | `/integrations/smtp*`; письма ERP и EDS — запрос по шине `uz.railtech.{erp,eds}.mail.requested.v1` → `email_log`, итог — `crm.mail.sent|failed` (CONTRACTS §9.9) | публикует `erp.mail.requested` (`BusEmailBackend`), слушает `crm.mail.*` (журнал писем, итог КП); SMTP в ERP нет; EDS — `mail_out.request_mail` | ✓ (W18A-P1) |
| Журнал интеграций: подписчики шины, доставки и DLQ, входящие с ошибками, повторы | `GET /admin/bus`, `/admin/bus/deliveries`, `/admin/bus/inbox` (слияние трёх доменов, `sources`), `POST /admin/bus/{domain}/…/retry*`; только `admin: full` | `/api/v1/bus/*` (`integrations:read`, `integrations:write`) | `/api/v1/integration/bus/*/` (`team.manage`); EDS `/api/v1/bus/*` (`bus.manage`, вход — SSO `aud=eds`) | ✓ (BFF 0.9.0, W13-A2) |
| Первый запуск: администратор (до входа) | `GET /setup/state`, `POST /setup/admin` (без сессии; ответ как у входа) | `GET /setup/state`, `POST /setup/admin` (код из журнала `crm-api`) | — | ✓ (BFF 0.10.0, W13-A4) |
| Первый запуск: своя компания и чек-лист из пяти шагов | `GET /setup/checklist`, `POST /setup/company` (раздел `admin` полный) | `GET /setup/checklist`, `/integrations/erp`, `/integrations/smtp`, `/users` | `setup/status/`, `setup/company/` | ✓ (BFF 0.10.0, W13-A4); разрывы — `QUESTIONS.md` Q-W13-A4-2 |
| Сотрудник без почты: временный пароль один раз | `POST /admin/users`, `POST /admin/users/{id}/temporary-password` | `POST /users` (`temporary_password`), `POST /users/{id}/reset-password` | — | ✓ (BFF 0.10.0, W13-A4) |
| Настройки бота (14 разделов: компания, часы, тексты, поведение, поиск по БЗ, стоп-слова, конкуренты, передачи, квалификация, веб-форма, канал команды, оповещения, сделки, бюджет) | `GET /admin/bot/settings` (значения и JSON Schema), `PUT /admin/bot/settings/{key}` — форма строится по схеме CRM | `GET /settings`, `PUT /settings/{key}` (`settings:read` / `settings:write`) | — | ✓ (BFF 0.11.0, W13-A5); чтение `admin: read`, правка `admin: full` |
| Пробный прогон правил передачи | `POST /admin/bot/settings/escalation/dry-run` | `POST /settings/escalation/dry-run` | — | ✓ (W13-A5), `admin: full` |
| Шаблоны быстрых ответов | `GET/POST /admin/bot/reply-templates`, `PUT/DELETE /admin/bot/reply-templates/{id}` | `/reply-templates*` (`reply_templates:read` / `reply_templates:write`) | — | ✓ (W13-A5); читает и менеджер с `crm.leads` полным |
| Выгрузки CSV лидов, клиентов, сделок | `GET /admin/bot/exports/{leads,clients,deals}` — поток, имя файла с датой | `GET /export/{leads,clients,deals}.csv` (`export:read` и чтение данных) | — | ✓ (W13-A5): `admin: full` и `crm.leads` / `crm.clients`; одному «Администратору» данные не выгружаются (R3-D-2) |
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

CRM считает статус сама — поле `platform_status` лида и фильтр `GET /leads?platform_status=` (CRM-02, W16-D1-2; правило —
`apps/crm/backend/app/domain/client_requests.py`, SQL — `repositories/lead_status.py`).

| Платформа | `platform_status` | CRM |
|---|---|---|
| Новый | `new` | `new` |
| В диалоге | `dialog` | `engaged`, `qualified`; `handoff`/`in_progress` без просьбы о КП |
| Просит КП | `wants_quote` | `handoff`/`in_progress` с активной передачей по причине `price_or_contract_asked` |
| Без ответа | `no_answer` | `unresponsive` или `handoff` с истёкшим SLA передачи (просьба о КП важнее просрочки) |
| Клиент | `client` | `customer`, `won` |
| (Отказ) | `lost` | `lost` — во вкладке «Все» с тегом |

«Просроченные» (фильтр «мои / все / просроченные») — `GET /leads?overdue=true`: открытая передача с истёкшим SLA ответа.

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
| `ACCOUNTANT` | `viewer` (признак по матрице, D1-8; ответы клиенту во внешнем чате — права `chats.external`, разделы CRM скрывает матрица) | `FINANCE` | `contract.manage`, `fulfillment.act` | договоры, счета, оплаты, акты |
| `ADMIN` | `admin` | — (суперпользователь ERP только для настроек бизнеса) | — | не ведёт процессы |

`CALCULATION` (Расчёт) для новых сотрудников не выдаётся. Каждый сотрудник — пользователь CRM с
`platform_access = ["crm","erp"]` (CRM — источник истины по людям); при нескольких ролях базовая роль CRM — старшая
(`admin` > `manager` > `viewer`). С R-1 (ADR-0012) роли Платформы — данные CRM, права CRM сотрудника — политики casbin его ролей (`pr:<id>`),
базовые роли для проверки прав не используются — и у системной «Администратор» тоже (R3-D-2, R-1c; D1-8 закрыл B-014: матрица прямого API CRM проверена тестом по каталогу, базовая роль вычисляется по матрице, `storage_key` из `MessageOut` убран): её права CRM — раздел `admin`
каталога, лиды, клиенты и сделки — второй ролью; базовая `admin` остаётся признаком «последний админ»; суперпользователь ERP — только системная роль с кодом `ADMIN` (до C2), пользовательской роли с `admin: full` — права разделов (Q-R1c-1 п. 5). **Источник истины карты — `packages/contracts/platform-rbac.yaml`**; изменения — PR с тестом матрицы.

## 5. Номера

| Номер | Где формируется | Статус |
|---|---|---|
| L-NNNN | BFF из `leads.id` | ✓ |
| ЗВ-ГГГГ-NNN / ПР-ГГГГ-NNN | ERP `Deal.number`: счётчик года под блокировкой, без пропусков; ПР — тот же NNN после принятия КП; старым сделкам — миграцией | ✓ ERP-09 (W16-D1-2) |
| ВХ-NNN/ГГ, ИСХ-NNN/ГГ, СЗ-ГГГГ/NNN | сервис EDS (счётчики EDS, волна 12) | ✓ |
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
| ERP-03 | статусы и журнал договора (Проект → Согласован клиентом → Выставлен у оператора → Подписан (скан) / Отклонён), скан — файл; «подпись кликом» для процесса v3 выключена; автосчёт на предоплату по подписи договора | P3 |
| ERP-04 | `PaymentConfirmation` (файл, источник CABINET/BOT/MANUAL, сумма, дата, кто подтвердил); связь с `record-payment`; «запросить платёжку» — событие для бота и письмо | P3 |
| ERP-06 | задача по расписанию: `OVERDUE` по сроку, событие `invoice.overdue`; включить `crm.send_payment_reminders` в расписание | P3 |
| ERP-07 | признак `Deal.process = v3` — **есть** (W16-D1-2: заявки «Создать заявку»); открыто — запрет переходов в обход резолюции, виз и одобрения для таких заявок в сервисном слое | P2 |
| ~~ERP-09~~ | закрыт (W16-D1-2): `Deal.number` ЗВ/ПР, поиск `?search=`; ВХ, ИСХ, СЗ — в EDS | — |
| ERP-16 | уведомления сотрудника: `unread_count` и признак прочитанного в выдаче (для колокольчика без перебора страниц); лента «Сегодня» для сотрудника — события компании по правам, а не `activity-logs` только администратору | P2 |
| ERP-17 | часовой пояс компании в API (сейчас BFF берёт `Asia/Tashkent` константой) | P2 |
| ERP-10 | публикация доменных событий для BFF — через шину `rt_bus` (ADR-0014; задачи B1–B8 стратегии), не Redis Streams | B |
| ~~ERP-11~~ | закрыт (W16-D1-2, решение архитектора 2026-10-28): одобрение директора в EDS с каналами → ERP отправляет КП по доступным каналам в транзакции решения, недоступные — в итоге с причиной | — |
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
| EDS-04 | зона исполнителя резолюции: исполнитель держит раздел зоны каталога (`erp.calc.goods`, `erp.calc.services`, `eds.payments`, уровень `full`) по проекции `employees.sections`; иначе 422 `assignee_zone_mismatch` | D1 | ✓ закрыт D1-8: `eds.yaml` 0.5.0, `identity.user.*` → `permissions.sections` (аддитивно в v1), миграция EDS `employee_sections` |

### Чаты (домен уточняется на этапе D)

| ID | Что | Фаза |
|---|---|---|
| ERP-08 | чаты (домен — коммуникации CRM по ADR-0015, окончательно — этап D): чат проекта (создаётся с заявкой, архивируется на «Выполнено»/«Отказ»), командные и личные чаты, сообщения, вложения, системные сообщения о событиях проекта, поиск по тексту | P3 |

### CRM

| ID | Что | Фаза |
|---|---|---|
| CRM-01 → R-1/R-1b | роли Платформы как данные (`platform_roles`, `user_platform_roles`, `version`), выдача `platform_role_ids`, провижининг ERP вычисленными правами; `GET /me` отдаёт `platform_role_refs` | P1 → волна 9 |
| ~~CRM-02~~ | закрыт (W16-D1-2): `platform_status` (new, dialog, wants_quote, no_answer, client, lost) в ответе лида, фильтры `platform_status` и `overdue` | — |
| ~~CRM-03~~ | закрыт: «Создать заявку» из любой активной стадии и из клиента, без e-mail, со срочностью и файлом письма, `process = v3` (W16-D1-2); приглашение в канал контакта, «Заявка принята» с «Открыть кабинет», «Отправить повторно другим каналом» — D1-9 | — |
| CRM-04 | уведомления сотрудникам из событий CRM (SLA лида, сбой интеграции, новое обращение) — хранение и API чтения | P3; **частично D1-9:** новый запрос с сайта — строка «Моей очереди» (`GET /inbox` → `unassigned`, BFF обновляет её по `lead.created`), личное сообщение менеджерам в Telegram по их настройке `notify_leads` и напоминание «никто не взял» через `settings.web_form.first_response_sla_minutes` (рабочие минуты); хранилища уведомлений сотрудникам в CRM по-прежнему нет — колокольчик строит BFF |
| CRM-05 | тикеты от команды | P4 |
| CRM-06 | записка handoff (запрос, факты, причина, рекомендуемый шаг) в выдаче `GET /inbox` | ✓ закрыт D1-1 (`LeadOut.handoff_note`) |
| CRM-07 | ответ «как бот» из внешнего чата (сообщение уходит от имени бота, в журнале — сотрудник) | P3 |
| CRM-01c | право читать сотрудников (`users:read`) по ролям Платформы: DIRECTOR — да, SUPPLY/ENGINEER — нет (базовая роль `viewer` его не даёт) | P1 (волна 8) |
| CRM-08 | `GET /inbox` с фильтром «мои» (`taken_by`, отложенные) на стороне CRM, вместо фильтрации в BFF | P2 (экран «Ждут ответа» берёт группы `escalations` / `mine` / `unassigned` как есть; «Моя очередь» по-прежнему отбирает чужие передачи в BFF) |
| CRM-09 | итог провижининга в ERP в выдаче пользователя (`erp_sync`: ok/pending/error), повторная отправка приглашения без смены пароля | P2 |
| CRM-10 | канал администратора для системных оповещений (никогда в канал команды), подавление «мигания» сервиса | по решению владельца |
| CRM-11 | W13-A5: (1) удаление документа базы знаний (сейчас только выключение `is_active`); (2) `GET /kb/products` для `kb:read`, а не только `leads:read` (администратор без второй роли вводит ключ продукта руками); (3) подписи полей настроек и тексты ошибок формата на трёх языках приходят от экрана и CRM только по-русски там, где их пишет CRM (`description` схем) | по решению владельца |
| CRM-12 | путь нового клиента (D1-9): подтверждение запроса с сайта (письмо или бот, итог в карточке лида — `confirmation`), срок первого ответа (`first_response_due_at`, `first_response_overdue`), deep-link `/start web`, `/start deal_<id>` (привязка только к заявке клиента, чей Telegram проверен) и подписанная ссылка `lead_…` из письма | **готово D1-9** |
| CRM-13 | сотрудники по разделу каталога: `GET /team?section=&level=` (D1-8, B-007) | ✓ закрыт D1-8 |

### Cabinet и портал ERP

| ID | Что | Фаза |
|---|---|---|
| CAB-01 | страница счёта: реквизиты, QR, «Я оплатил» + файл платёжки (портал: `POST /invoices/{id}/payment-doc`) | P3 |
| CAB-02 | проект договора: «Согласовать редакцию» / «Замечания» вместо «Подписать» для процесса v3 | P3 |
| CAB-03 | статусы для клиента из `client-statuses.yaml`; токены ui-tokens 0.2 | P3 |
| CAB-04 | уведомления в кабинете (колокольчик, непрочитанное) | P4 |
