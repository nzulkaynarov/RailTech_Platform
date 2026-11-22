# AREA C: navigation and information architecture compared with the owner's module-ownership draft

All paths below are under `/home/umarbek/projects/RailTech_Platform/.claude/worktrees/research-main/`. The checkout is main @ `2ecd40446`.
Abbreviations: **nav** = `apps/platform/web/src/modules/navigation.ts`, **rbac** = `packages/contracts/platform-rbac.yaml`, **NAV doc** = `docs/product/NAVIGATION.md`, **DEC** = `docs/DECISIONS.md`.
Everything is a fact with a source unless marked (inference).

---

## 1. Today's map: rail module → menu item → route → section and access → RBAC menu key → domain system

There are two layers. `module.ts` files hold sections, routes and access rules. nav lays them out into rail items, and a section may sit in a module other than the one it belongs to (nav L6-9: «раздел может стоять не в своём модуле»). The route prefix is the domain code; the menu label is the new name.

| Rail · item (tab) | Route the item opens | Section · access rule (file:line) | `menu` key in rbac (L418-483) | Data comes from |
|---|---|---|---|---|
| **Главная** · Задачи | /dashboard/queue | dashboard.queue · `dashboard.queue` (dashboard/module.ts L7-12) | dashboard.queue | BFF snapshot of all domains (34 task kinds, rbac L500-547) |
| Главная · Проекты | /eds/projects (nav L83); /dashboard/projects redirects there (dashboard/index.tsx L34-36) | **eds**.projects · `eds.projects` (eds/module.ts L57-65) | dashboard.projects **and** eds.projects | ERP `GET /crm/projects/` (bff/app/eds_projects.py L1-9) |
| Главная · Сводка | /dashboard/summary | dashboard.summary (dashboard/module.ts L19-24) | dashboard.summary | CRM dashboard/spend + ERP data.export (rbac L196-201) |
| **Контакты** · Лиды | /crm/leads (also lights for crm.messages) | crm.leads · anyOf crm.leads, crm.leads.triage (crm/module.ts L13-19) | crm.leads, crm.messages | CRM |
| Контакты · Контрагенты | /crm/clients (filters: clients, partners, applications, bank_changes — ClientsPage.tsx L44) | crm.clients · anyOf crm.clients, **erp.stock** (crm/module.ts L20-27) | crm.clients | CRM clients + ERP parties (the supply specialist's list comes from ERP, rbac L77-79) |
| Контакты · Почта | **/eds/mail** (nav L89) | **eds**.mail · anyOf crm.leads.triage, crm.leads, crm.mail (eds/module.ts L30-38) | **eds**.mail | **CRM** `/api/v1/inbound-mail*` (bff/app/api/inbound_mail.py L1-19) |
| Контакты · База знаний | /crm/kb | crm.kb · anyOf crm.leads, admin (crm/module.ts L31-38) | crm.kb | CRM |
| **Документы** · Входящие | /eds/inbox (also lights for eds.register) | eds.inbox · anyOf eds.inbox, eds.inbox.register (eds/module.ts L22-29) | eds.inbox | EDS |
| Документы · Исходящие | /eds/documents?box=outgoing (also eds.outbox, eds.drafts) | eds.documents · any of 7 eds resources (eds/module.ts L5-21) | eds.documents/outbox/drafts | EDS registry + ERP (KP, contract, invoice, act — DocumentsPage.tsx L91-95) |
| Документы · Внутренние | /eds/documents?box=internal (also eds.approvals) | eds.documents · same 7 eds resources | eds.approvals | EDS (memo, application, report — DocumentsPage L93) |
| Документы · Архив | /eds/documents?box=archive | eds.documents | — | EDS |
| Документы · Шаблоны | **/admin/templates** (nav L97) | **admin**.templates · `company.settings` (settingsRegistry.ts L359-362); page is wrapped in `SettingsPage` (TemplatesPage.tsx L20-24) | admin.templates | ERP document templates + EDS letters + CRM e-mails (TemplatesPage L14) |
| **Операции** · Заявки → Продажи | /erp/requests (also erp.calc) | erp.requests · `erp.calc` (erp/module.ts L9-18) | erp.requests, erp.calc | ERP |
| Операции · Заявки → Закупки | /erp/stock?view=orders (nav L71, L106); the supplier-order card belongs to this tab through `objects` | erp.stock · `erp.stock` (erp/module.ts L30-38) | erp.stock | ERP |
| Операции · Каталог → Товары / Склад / Документация | /erp/catalog, /erp/stock, /erp/docs | erp.catalog, erp.stock, erp.docs · all `erp.stock` (erp/module.ts L39-52) | erp.catalog, stock, docs | ERP |
| Операции · Финансы → Счета клиентов / Заявки на оплату | **/eds/payments**, /eds/payments?show=memos (nav L72-75) | **eds**.payments · `eds.payments` (eds/module.ts L81-88) | **eds**.payments | ERP finance + EDS memo payments (bff/app/api/eds_payments.py L1-11) |
| **Органайзер** · Календарь | /chats/calendar | chats.calendar · `dashboard.queue`, `hidden: true` (chats/module.ts L9-15) | **none** | Deadlines from the task queue (CalendarPage.tsx L78) |
| Органайзер · Чаты | /chats (also chats.internal, chats.external) | chats.all · anyOf chats.internal, chats.external (chats/module.ts L16-22) | chats.all/internal/external | Screen layout only — «переписка подключается отдельным этапом» (ChatsPage.tsx L20) |
| Органайзер · Люди | /chats/contacts | chats.contacts · `chats.internal` (chats/module.ts L36-42) | chats.contacts | EDS staff + ERP `parties/people` + CRM leads (PeoplePage.tsx L55-57; bff/app/api/people_contacts.py L1-7) |
| **Настройки** · Сотрудники / Компания / Подключения / Журнал | 21 pages in `SETTINGS`, 4 groups (settingsRegistry.ts L14-23); «Шаблоны документов» is skipped here and shown under Документы (nav L137-141) | admin.* · `admin` / `company.settings` / `eds.signing.manage` | admin.* (22 keys) | Mostly CRM; ERP for company and numbering; EDS for signing and the system exchange |

**Sections that are registered and not hidden but only redirect** (old SPEC-v3 §6.2 lists), 10 in total:

| Section | Redirects to | Where |
|---|---|---|
| crm.messages | /crm/leads?scope=waiting | crm/index.tsx L23-31 |
| crm.requests | /erp/requests | crm/index.tsx L20 |
| crm.channels | /admin/telegram | crm/index.tsx L21 |
| eds.outbox | documents box=outgoing | eds/index.tsx L104-110 |
| eds.drafts list | documents | eds/index.tsx L29-34 |
| eds.approvals list | box=internal | eds/index.tsx L36-39 |
| erp.calc list | /erp/requests?mine=1 | erp/index.tsx L39-41 |
| chats.internal | /chats | chats/index.tsx L15-17 |
| chats.external | Лиды «Ждут ответа» | chats/index.tsx L18-20 |
| dashboard.projects | /eds/projects | dashboard/index.tsx L34-36 |

`eds.documents` («Все документы») has no menu item: the test expects `/eds/documents` to map to no menu item (registry.test.ts L47).

**Who sees each item.** Computed from the role catalogue in rbac (system roles plus templates) and the access rules above. F = full, R = read, «—» = hidden.

| Item | ADMIN | DIRECTOR | MANAGER | MANAGER_ALL | SUPPLY | ENGINEER | ACCOUNTANT | REGISTRAR | LAWYER |
|---|---|---|---|---|---|---|---|---|---|
| Главная · Задачи | F | F | F | F | F | F | F | F | F |
| Главная · Проекты | — | F | R | F | R | R | F | R | R |
| Главная · Сводка | — | F | — | — | — | — | R | — | — |
| Контакты · Лиды | — | R | F | F | — | — | — | F (разбор) | — |
| Контакты · Контрагенты | — | F | F | F | F (партнёры) | F | R | R | R |
| Контакты · Почта | — | R | F (свои письма) | F | — | — | — | F | — |
| Контакты · База знаний | F | R | F | F | — | — | — | R | — |
| Документы · Входящие | — | F | R | R | — | — | R | F | R |
| Документы · Исходящие / Внутренние / Архив | F | F | F | F | F | F | F | F | F |
| Документы · Шаблоны | F | F | — | — | — | — | — | — | — |
| Операции · Заявки | — | F | F | F | F | F | R | — | — |
| Операции · Каталог | — | F | R | F | F | F | R | — | — |
| Операции · Финансы | — | R | R | F | — | — | F | — | — |
| Органайзер · Календарь / Чаты / Люди | F | F | F | F | F | F | F | F | F |
| Настройки · Сотрудники / Подключения / Журнал | F | R | — | — | — | — | — | — | — |
| Настройки · Компания | F | F | — | — | — | — | — | — | — |

There is no HR role. The catalogue has 9 roles: ADMIN, DIRECTOR (rbac L22-53) and MANAGER, SUPPLY, ENGINEER, ACCOUNTANT, REGISTRAR, MANAGER_ALL, LAWYER (rbac L57-173). Owner draft roles «клиент-менеджер» and «менеджер по продажам» are both held by one template, MANAGER: `crm.leads: full` plus `erp.calc: full` (rbac L59-74, DEC L328).

**Where the NAV doc role table (L97-108) differs from the code:**
- Менеджер also sees Финансы (`eds.payments: read`, rbac L70).
- Гл. инженер sees Контрагенты, although the doc says «Контакты —» (`crm.clients: read`, rbac L93).
- Бухгалтер also sees Заявки and Каталог (`erp.calc`/`erp.stock: read`, rbac L112-113).
- Юрист:
  - sees Проекты, although the doc says «задачи» only (`eds.projects: read`, rbac L169);
  - sees Контрагенты, although the doc says «—» (`crm.clients: read`, rbac L167);
  - does **not** see Шаблоны, although the doc grants it (no `company.settings`).
- Директор also sees Настройки · Подключения (`admin: read`).
- Делопроизводитель also sees База знаний (`crm.leads: read`).

The doc itself says «Точная матрица прав закрепляется на этапе ролей» (L113-115).

## 2. Several sources of navigation truth, and drift between them (facts)

1. **The rail menu and the contract `menu` disagree.**
   - The rail and submenu come from nav plus `canSee`: AppShell.tsx L119-123, 182.
   - `Me.modules` comes from the contract `menu` via BFF `modules_for` (bff/app/rbac.py L91-106, schemas.py L145). It is used for the home path (app/access.ts L38-45), search (GlobalSearch.tsx L129) and the help-coverage test (features/help/articles.test.ts L70-78).
   - The contract `menu` still uses the old SPEC-v3 §6.2 keys: crm.messages, requests, channels; eds.documents, mail, outbox, projects, drafts, approvals, payments; chats.all, internal, external. It has no keys for calendar, Внутренние, Архив, Финансы.
2. **Search groups by module code, not by menu.**
   - Section search goes through `module.sections` with the module title, skipping only `hidden` sections (GlobalSearch.tsx L127-147). So «Почта», «Проекты» and «Финансы» show up under **Документы**.
   - The 10 redirect-only sections above are findable under their old names: «Ждут ответа», «Каналы связи», «КП на одобрение», «На согласовании», «Мои расчёты», «Команда», «С клиентами» (still in i18n ru/modules.json `sections`).
   - Календарь is `hidden` (chats/module.ts L13), so search does not find it.
   - BFF object search puts заявки under `crm` and проекты under `eds` (bff/app/feeds/search.py L271-274).
3. **Breadcrumbs follow the menu** (AppShell.tsx L298-317). Page titles of eds sections use `modules:eds.sections.*` (DocumentsPage L414).
4. **`menuAccess` is declared but never read.** It is declared in types.ts L37 and set in crm/module.ts L36 and admin/module.ts L41, but no runtime code reads it; only `app/rbac.generated.test.ts` L154 reads it. So administrators get Контакты · База знаний in the menu, even though the comment in crm/module.ts L35 says they enter from Telegram settings.
5. **Five settings groups versus four.**
   - SET-IA (owner, 2026-11-03; research `docs/research/2026-11-02-flexibility/4-settings-ia.md` §4.1) defined 5 groups: Люди и доступ · Компания · Каналы связи · Процессы · Система.
   - NAV doc (2026-11-10, L58-67) and the code (settingsRegistry.ts L14-23) have 4 groups: Сотрудники · Компания · Подключения · Журнал.
   - Comments still describe the 5 groups: rbac L456-459, types.ts L26-30, admin/module.ts L126-129, TemplatesPage.tsx L16 («Процессы · Шаблоны документов»).
   - BACKLOG B-EDSREG-1 (L219) still says «Настройки · Процессы · Справочники».
   - DEC has no row tagged SET-IA; its date is known only from rbac L456.
6. **Settings page count.**
   - NAV doc lists 19 page names under 20 screens; «Продажи» (/admin/sales, ДОК-13) is not in the NAV doc table.
   - Code has 21 pages; Компания has 9 tabs (settingsRegistry L115-410).
7. **SPEC-v3 §6.1 is stale.** It still names the rail «Главная · Клиенты · Документы · Расчёт · Чаты · Настройки» (SPEC-v3 L512), and the §6.3 route map is the old one (L550-590). NAV doc replaced only §6.2 and the side-window rule (NAV doc L4).
8. **Placeholders in the screenshots.**
   - Screenshot (a): `eds.new` declares no `tabs`, so it gets `DEFAULT_TABS` «Карточка · Чат проекта · Документы» (types.ts L83-87). Its card tab shows «Объект не выбран» (ru/modules.json L805-807) on a form.
   - Screenshot (b): PeoplePage has no `Card`, no subtitle and `width: null` on every column (PeoplePage L146-190, L197-231). ProjectList wraps its table in `<Card>` with fixed widths (ProjectList L34, L363, L410).
   - PeoplePage opens the person in an AntD `Drawer` (L232). This goes against ORCHESTRATOR §3 п.18: «окно — немодальная область, не `Drawer`».

## 3. Accepted decisions that set today's structure

- **NAV doc, status line L2:** «принята владельцем 2026-11-10; … открытых вопросов нет». Rules (L6): «у объекта один дом; меню модуля — не больше пяти коротких пунктов; кнопка «Создать» одна…; что не положено роли, не показывается». Menu table: L12-19.
- **DEC L298 (2026-11-10):** «меню из 18 пунктов владельца и пять уточнений архитектора — «Люди» в Органайзере вместо второго раздела «Контакты», «Сводка»…, согласования и служебки — через «Задачи» и «Исходящие»…».
- **DEC L300 (2026-11-10):** «(1) клиенты и поставщики — один пункт «Контрагенты»… лиды отдельно… (2) «Люди» — один список… сотрудники, люди клиентов и партнёров, лиды… контрагенту пишет только ответственный».
- **DEC L301, Q-NAV-1:** «в «Документах» пятый пункт «Внутренние»… служебные записки, заявления, отчёты, заявки на закупку и оплату». The reason is in NAV doc L36: «совпадает со словарём и привычным делением документов, а внутренних документов будет больше, чем писем и КП». NAV doc L161: «Замечание по самоописательности снято пунктом «Внутренние»». **Q-NAV-2:** everything is visible from day one.
- **DEC L303 (2026-11-10):** «Задачи, Проекты, Календарь и Чаты подключаются к корпоративным сервисам в настройках. Основная экосистема — Яндекс 360…». Also in NAV doc L69.
- **DEC L307:** people and contacts — a person linked to several counterparties; CardDAV only for own contacts.
- **DEC L328 (2026-11-13), FR-10:** «Почта»: the director sees the whole queue read-only through the new section `crm.mail`; a manager sees only their own letters.
- **DEC L231 and L232 (2026-10-28):** mail is a **channel** — «Настройки · Каналы связи», «Почта — один канал на вход и выход».
- **DEC L364 (2026-11-22), ЕД-7, and DEC L365 (2026-11-22), ГЛ:**
  - «Главная — работа начинается здесь»;
  - ГЛ-1 done-when (plan L145): «пользователь не ищет задачи по разделам: всё, что ждёт его действия, — на «Главной»».
- **NAV doc on mail** (L31): «Почта — вся электронная переписка компании. Регистрация официального письма создаёт входящий документ». History (L179): «Документы: Входящая почта · Моя почта → Контакты · Почта».
- **NAV doc on chats** (L49): «Чаты — только внутри компании»; L188: «переписка с контрагентами — в карточках».
- **NAV doc on addresses** (L93): «Адреса строятся на внутренних кодах модулей и не обязаны повторять меню… если меняется, старый адрес перенаправляет».
- **MODULES.md** (`docs/product/MODULES.md`):
  - CRM «Владеет: …почтовый ящик компании» (L18);
  - EDS «Для кого: Делопроизводитель, директор, все инициаторы документов; Владеет: …внутренние документы» (L36-37);
  - ERP «Для кого: Менеджеры, расчётчики, снабжение, бухгалтер» (L60);
  - WFM «Для кого: Все сотрудники, директор» (L81);
  - Чаты (L164, owner 2026-11-10): «разговоры с клиентами и партнёрами; внутри компании — обсуждения на объектах».

## 4. ORCHESTRATOR §3 invariant 1 (docs/ORCHESTRATOR.md L52)

> «**Одна система — один главный пользователь.** Клиент не входит в CRM, ERP и Платформу; сотрудник не входит в Cabinet… Платформа — интерфейс сотрудников; CRM и ERP после задачи P6 волны 18a — бэкенды без своих фронтендов.»

How it maps to modules:
- The invariant is about systems (CRM, ERP, EDS, Cabinet, Platform), not about rail modules. For the Platform, the main user is the employee.
- The rail modules do not line up one-to-one with systems:
  - Контакты includes /eds/mail with CRM data.
  - Главная includes /eds/projects with ERP data.
  - Операции includes /eds/payments with ERP and EDS data.
  - Документы includes /admin/templates with ERP, EDS and CRM data.
  - Люди combines three systems.
- The only per-system «для кого» statements are in MODULES.md (§3 above).
- A per-module «owner» is a new concept, not derived from §3 п.1 (inference).
- Related invariants:
  - п.7 «Одна передача — один владелец. Лид → клиент: CRM» (L58);
  - п.13 «Одна консоль администратора — раздел Admin Платформы… Админ видит и контролирует все внешние сервисы» (L64). This supports draft idea 1.

## 5. The six owner ideas checked against the code

### 1. Настройки: owner is the administrator (foundation, accident risks)
- **Fits:**
  - Подключения · Сервисы — health of services (settingsRegistry L435-441);
  - Журнал: История, Обмен между системами, Выгрузки;
  - Расходы на ИИ;
  - Уведомления — failure alerts;
  - the admin's task kinds `integration_issue` and `ticket` (rbac L530-531);
  - plan СЦ-3, «страница готовности у администратора… красная строка на «Главной»» (plan L124).
- **Does not fit the admin owner:**
  - `company.settings` pages are business rules. The director holds them in full (rbac L49): Реквизиты и бланк, Нумерация, Налоги и валюты, Продажи (term, payment, warranty, margin), and Справочники (`anyOf admin, company.settings`).
  - Admin-only process pages with business content: Шаблоны резолюций, Время и сроки (response times, hand-over to a manager), Статьи компании, Telegram texts and behaviour.
- **Fits Настройки but lives elsewhere:**
  - Документы · Шаблоны is a Settings page with `company.settings` access (TemplatesPage.tsx L20-24);
  - Справочники for the catalogue (ТН ВЭД, бренды, запросы на категории) sit in Операции · Каталог (RefsPanel.tsx L43), while categories and charges are in Настройки · Справочники (DictionariesPage.tsx L63-78).
- **Duplicates:**
  - База знаний: Контакты · База знаний plus the Telegram «База знаний» tab, which is an entry card linking to /crm/kb (TelegramPage.tsx L17-20, L43-49).
  - Templates in 5 places, gathered by BFF `templates_catalog.py` L97-179: /admin/templates?tab=documents|emails|letters, /admin/resolutions, /admin/telegram?tab=templates.
  - The e-mail templates tab stays in Документы · Шаблоны until ДОК-15 (plan L161).
- **Moving a settings page within Настройки:** touches `settingsRegistry.ts`, `redirects.ts` (for an old address), rbac menu.admin, `apps/crm/backend/tests/unit/domain/test_platform_links.py` (reads the registry, DEC L265), and the help article (`screens`).

### 2. Главная: hall and situation centre for everyone
- **Today:** Задачи (34 task kinds from CRM, EDS, ERP and admin; rbac L500-547), Проекты, Сводка.
- **Who gets what:**
  - Сводка only for DIRECTOR (full) and ACCOUNTANT (read);
  - ADMIN gets Задачи only.
- **Planned (in flight):**
  - ГЛ-1: groups, reasons, «Вы ждёте других»;
  - ГЛ-2: badges and Telegram notifications;
  - ГЛ-3: Сводка for the director;
  - plan L144-147.
- **Does not fit «зал для всех»:** Проекты is an ERP deal with contract, invoice, act and scans (rbac L273-275 label «Главная · Проекты: договор, счёт, акт, сканы»). It is a working list, not a hall view.

### 3. Контакты: owner is the client manager, leads only (Telegram bot or site); remove mail
- **Lead sources today are more than two:**
  - Telegram, site form, Кабинет «Запрос» (connectors research §1 table);
  - mail → «Создать лид» (inbound_mail.py L326);
  - phone call → Создать · Лид (createKinds.ts L30-33);
  - SPEC-v3 §7.2 channel filter «Telegram / Почта / Веб-форма / Звонок».
  - Removing mail without a replacement would drop the mail → lead path (inference).
- **Not leads, living here today:**
  - Контрагенты: clients, partners, partner applications, bank-detail changes (ClientsPage L44). The reference copy of a counterparty is in ERP (MODULES L148, ADR-0028).
  - Почта (§6.1 below).
  - База знаний — the bot knowledge base, maintained by the admin (NAV doc L32).
  - «Создать → Заявка» opens /crm/clients?create=1 (createKinds.ts L37-40).
- **Leads that live elsewhere:** Органайзер · Люди lists leads as people (PeoplePage KINDS L21, LEADS_RULE L40).
- **Contradicts:** NAV doc L15 and L25-32; DEC L300(1); DEC L328(2); MODULES CRM L18.

### 4. Документы: owner is the registrar, legally binding external correspondence only; remove internal
- **«Internal corporate correspondence» in Документы today is «Внутренние»:** memo, application, report (DocumentsPage L93). Purchase requests (П6) and expenses (П8) are memo kinds, and paid memos feed Операции · Финансы · Заявки на оплату (PaymentList.tsx L78-129; model.ts L10).
- Chats and messages are not in Документы.
- **Does not fit «registrar, external»:**
  - Шаблоны is a settings page;
  - Исходящие also holds commercial КП, contracts, invoices and acts (BOX_TABS L92). Their rows open the project card in Главная (pagePath L130-140).
- **Fits but lives elsewhere:**
  - the registrar's intake mail is Контакты · Почта: `crm.leads.triage` is a REGISTRAR right (rbac L124-136, L213-222). Registration starts from the letter (NAV doc L72).
- **Contradicts:**
  - Q-NAV-1 (DEC L301, NAV doc L36, L154, L158, L161);
  - SPEC-v3 §3.2 (L176-187);
  - MODULES EDS «Владеет: …внутренние документы» (L37).

### 5. Операции: owner is the sales manager (calculations, purchases, money)
- **Who actually acts here (rbac):**
  - Заявки → Продажи: MANAGER, MANAGER_ALL, SUPPLY, ENGINEER have `erp.calc` full.
  - Закупки and Склад: actor is SUPPLY (`erp.stock` full); MANAGER and ACCOUNTANT read only.
  - Финансы: actor is ACCOUNTANT (`eds.payments` full); MANAGER and DIRECTOR read only.
  - SPEC-v3 §6.2 note: «Счета и оплаты — рабочее место бухгалтера» (L545).
- **The sales manager is the main actor in 1 of 3 items** (inference from the above).
- **Fits but lives elsewhere:**
  - creating a заявка lives in Контакты (createKinds L37-40);
  - search shows заявки under Контакты (search.py L272);
  - Проекты (договор, счёт, акт) sit under Главная;
  - rates are in Настройки · Налоги и валюты (pages.tsx L17, L45).
- **Mixed by design:**
  - Финансы is an EDS route (/eds/payments) with ERP data;
  - one section, erp.stock, serves two menu tabs (Закупки and Склад; nav L71, L106, L114).

### 6. Органайзер: owner is HR; internal and project communication, meetings, tasks, project status; own connectors
- **No HR role exists** (§1).
- **Employee records are elsewhere:** Сотрудники, Роли и права, Права подписи are in Настройки (admin). NAV doc L54: «Роль и права сотрудника остаются в «Настройки · Сотрудники»».
- **Today:**
  - Календарь: deadlines from the queue; no meetings;
  - Чаты: layout only, no data (ChatsPage L20; MODULES L111 «Экран в Платформе — нет, заглушка»);
  - Люди: people from three systems.
- **Tasks and project status live in Главная** (Задачи, Проекты). «Поручение» in Создать is marked «скоро» (`soon: withChats`, createKinds L92-95). MODULES WFM: «Произвольная задача и проект без сделки — нет» (L91).
- **Communication with clients today:**
  - in Лиды «Ждут ответа» (chats/index.tsx L18-20);
  - in the lead card;
  - in the calculation's «Задание» tab with the project chat (erp/module.ts L3-4).
  - ЕД-7 found «Обсуждение» and «Документы» nowhere filled (plan inbox, 2026-11-22).
- **Connectors:**
  - decided 2026-11-10 (DEC L303), configured in Настройки · Подключения;
  - research `docs/research/2026-11-22-connectors/README.md` §6 waits for 13 owner answers;
  - the research says iCal stage 1 is «в план не внесён» (§1). It has since landed on main on 2026-11-22: commits 8c419ccda and 368c02c22, `apps/platform/bff/app/calendar_link.py`, `features/profile/CalendarLinkSection.tsx`. It lives in **Профиль**, not in Органайзер.
- **Contradicts:**
  - NAV doc L18, L49, L188 (chats internal only);
  - DEC L300(2) (only the responsible person writes to a counterparty);
  - ГЛ (DEC L365) and NAV doc L14 (tasks on Главная).
- **Agrees with:** MODULES L164 (chats with clients and partners). Here the accepted documents disagree with each other.

## 6. The specific topics

### 6.1 Mail
There are five places:
1. **Контакты · Почта.**
   - Route /eds/mail; section in the eds module; data in CRM.
   - Tabs for the registrar: new, mine, in_work, done, spam, all. Tabs for one's own mail: mine, done, all (mailModel.ts L36-37).
   - Actions: «Зарегистрировать ВХ» (to EDS), «Создать лид» (to CRM), archive, reply (inbound_mail.py L197-334). Plus «Отправленные», the journal of all mail sent by the systems (bff/app/api/mail_sent.py L1-7).
2. **«Моя почта».**
   - Route /eds/my-mail, hidden section, access `dashboard.queue` (eds/module.ts L39-49).
   - Opened from Задачи (task kind `inbound_mail_mine`); highlights Главная · Задачи (nav L82).
3. **Настройки · Подключения · Почта** (/admin/mail): IMAP/SMTP setup.
4. **Настройки · Справочники**, group «Почта»: mail types (DictionariesPage L56-62).
5. **Документы · Шаблоны**, e-mails tab (until ДОК-15).

Registered letters live in Документы · Входящие (EDS).

**Why mail sits in Контакты:** NAV doc L31 and L179; MODULES CRM owns the mailbox; FR-10 (DEC L328). The process maps step П1.1 («Контакты · Лиды, Почта») and step П4 («кнопка на письме в «Почте»») to it (NAV doc L123, L141).

**Moving mail in the menu only** (the route can stay under the address rule, NAV doc L93) touches:

| What | Files |
|---|---|
| nav L89 | 1 |
| i18n modules.json `nav.mail` in ru, uz, en | 3 |
| registry.test.ts L18 | 1 |
| rbac labels L216, L229 (menu.eds.mail is already under eds) | 1, then regenerate web `app/rbac.generated.ts`, bff `app/rbac_generated.py`, crm `app/domain/platform_roles_generated.py` |
| help articles that say «Контакты · Почта»: inbox.md, inbound-mail.md, admin-mail.md (+ what's-new 2026-11-20) | 3 |

- e2e menu expectations are generated from nav plus rbac (e2e/support/rbac.ts L1-12, which imports `visibleItems`), so they follow automatically.
- 4 e2e specs check the «Почта» page heading, which does not change.

**If the route moved as well:**

| Where | Files |
|---|---|
| e2e | 9 (/eds/mail) + 2 (/eds/my-mail) |
| web production code | 3 + 3 |
| web unit tests | 5 + 4 |
| BFF link builders: feeds/numbers.py L182, feeds/queue.py L970 | 2 |
| help (`screens`) | 1 |

### 6.2 «Внутренние» (memos, applications, reports; approvals)
- Menu: nav L95. List: DocumentsPage `box=internal` (L89-95). Card: /eds/approvals/:id (ApprovalsScreen).
- Creation: Создать → «Внутренний документ» (createKinds L66-69).
- Rights: `eds.memo.create` (every role), `eds.memo.approve` (DIRECTOR). Labels «Документы · Внутренние · …» (rbac L294-303).
- Paid memos also appear in Операции · Финансы · Заявки на оплату.

Removing it touches:

| What | Files |
|---|---|
| nav | 1 |
| DocumentsPage BOXES and BOX_TABS | 1 |
| eds/index.tsx redirect L36-39 | 1 |
| createKinds | 1 |
| rbac labels | 1 + 3 generated |
| i18n | 3 |
| registry.test.ts | 1 |
| e2e: 4 (/eds/approvals) + 1 (box=internal) | 5 |
| web production code: 6 + 2 | 8 |
| web unit tests: 8 + 2 | 10 |
| BFF link builders: numbers.py L150, queue.py L987 | 2 |
| help memos.md | 1 |

It also reverses Q-NAV-1.

### 6.3 «Проекты» under Главная **and** Документы
- **Under Главная:** the menu item (nav L83) and the breadcrumb (AppShell L300).
- **Under Документы:**
  - the route /eds/projects and the eds section (eds/module.ts L57-65);
  - the search-result group «Документы» (GlobalSearch L127-147, search.py L273);
  - the Исходящие tabs Договор, Счёт, Акт open the project card (DocumentsPage L92, L135-136);
  - i18n `eds.sections.projects`;
  - the old SPEC-v3 §6.2 item «Документы: Проекты: договоры и акты»;
  - rbac menu has both dashboard.projects and eds.projects (L421, L440).
- Badge counters exist for both (`MenuCounter` dashboard/projects and eds/projects, feeds/queue.py L1077-1079).
- Data comes from ERP.

A menu-only move touches:

| What | Files |
|---|---|
| nav | 1 |
| i18n | 3 |
| registry.test.ts L49 | 1 |
| e2e app-shell.spec L157, L261 (menu link «Проекты 4») | 1 |
| rbac label L275 + menu.dashboard | 1 + 3 generated |
| dashboard/module.ts and index.tsx (redirect) | 2 |
| BFF feeds/queue.py counter | 1 |
| help projects.md | 1 |

A route move adds: e2e 7, web production code 7 files that build the route (module.ts, ProjectsScreen, ProjectView, api.ts, DocumentsPage, dashboard/index, UiShowcase), web unit tests 12, BFF 4 builders (numbers.py L91, L241; schemas_erp_stock.py L599; schemas_eds_letters.py L1073), CRM 0.

### 6.4 «Люди» vs clients/leads vs counterparties
- **Люди** (/chats/contacts, `chats.internal`, all roles) merges:
  - employees (EDS staff);
  - counterparty people (ERP `parties/people`, contacts revealed on demand and logged: people_contacts.py L1-7);
  - leads (CRM).
- **Контрагенты** (/crm/clients) lists the legal entities. Their people are also in the counterparty card.
- **Лиды** (/crm/leads) lists the same leads that appear in Люди.
- So leads appear in 2 places and client people in 2 places. This is by decision (DEC L300(2), NAV doc L50-56); merging into one entity is deferred to the backend stage (NAV doc L55).
- Employee administration is in Настройки · Сотрудники.
- The label of `chats.internal` is «Органайзер · Чаты и Люди» (rbac L351); `chats.external` is labelled «Контакты · Переписка с клиентами» (rbac L354), but its section redirects to Лиды.

### 6.5 «Задачи» (dashboard queue) vs EDS tasks
- **Главная · Задачи** is the only list: /dashboard/queue, 34 kinds.
- `/eds/tasks/:id` is the working screen of one instruction (поручение). It is hidden; its list redirects to /dashboard/queue (eds/module.ts L99-109, eds/index.tsx L35). Menu highlight goes to Задачи (nav L82).
- Links come from BFF `letter_task_path` (numbers.py L136) and CRM Telegram notices (`apps/crm/backend/app/services/eds_notices.py` L85).
- Tickets: list in Задачи, card at /admin/tickets/:id (admin/module.ts L58-69; redirects.ts L104).
- There is no second task list.

### 6.6 Placement inside Операции
See §5.5 for who acts on calculations, requests, stock and payments.
- Calculation cards stay at /erp/calc/:id (erp/index.tsx L34-46).
- Old catalogue addresses for partners and applications redirect to Контрагенты (erp/index.tsx L20-29).
- Bank-detail changes moved from Финансы to Контрагенты (eds/index.tsx L94-97), but ERP still emits the old link `/eds/payments?show=bank_changes` (`apps/erp/backend/portal/services/bank_details_change.py` L150).

### 6.7 Chats
- The menu item exists and the screen is a placeholder.
- The client chat filter redirects to Лиды.
- Conversations with clients live in CRM leads; there is a project chat only in the calculation panel.
- The NAV doc rule (internal only) and MODULES L164 (clients and partners) disagree (see §5.6).

## 7. Where the owner's draft contradicts accepted decisions

1. «Убрать почту из Контактов» vs NAV doc L15 and L31; DEC L328 (FR-10, 2026-11-13); MODULES CRM L18; NAV doc L123 and L141 (process steps П1.1 and П4 placed in «Почта»).
2. «Контакты — только лиды» vs DEC L300(1) («Контрагенты» as one item next to «Лиды»); NAV doc L15 and L25-32.
3. «Убрать внутреннюю переписку из Документов» vs Q-NAV-1, DEC L301 (owner, 2026-11-10), with the reason quoted in NAV doc L36 and L161; SPEC-v3 §3.2; MODULES EDS L37.
4. «Органайзер: общение с клиентами и партнёрами» vs NAV doc L18, L49, L188 and DEC L300(2). It matches MODULES L164, so the accepted documents themselves disagree.
5. «Органайзер: ставятся задачи, статусы проектов» vs DEC L365 and ГЛ-1 (2026-11-22, «всё, что ждёт его действия, — на «Главной»»); NAV doc L14 and L23; DEC L298.
6. «Операции — владелец менеджер по продажам» vs the rbac actors (SUPPLY, ACCOUNTANT); SPEC-v3 §6.2 note L545; MODULES ERP L60.
7. «Органайзер — HR» vs the absence of any HR role in rbac; NAV doc L54 (employees in Настройки); MODULES WFM L81 («все сотрудники, директор»).
8. «Свои коннекторы в Органайзере» vs DEC L303 and NAV doc L69 (connectors in «Настройки · Подключения»; Задачи and Проекты, which live in Главная, are among the services to connect).

Ideas 1 and 2 agree with ORCHESTRATOR §3 п.13, СЦ-3 and ГЛ.

## 8. «Одни и те же настройки в нескольких местах»: every instance found in my area

| Topic | Places |
|---|---|
| База знаний | Контакты · База знаний; Настройки · Telegram · tab «База знаний» (link) |
| Почта | Контакты · Почта (work); Настройки · Подключения · Почта (connection); Настройки · Справочники · Почта (types); Документы · Шаблоны · e-mails (until ДОК-15 moves them to Настройки · Уведомления) |
| Шаблоны | Документы · Шаблоны (documents, letters, e-mails); Настройки · Шаблоны резолюций; Настройки · Telegram · Шаблоны ответов |
| Справочники | Настройки · Справочники (categories, charges, mail and document types, reasons); Операции · Каталог · Справочники (ТН ВЭД, бренды, запросы на категории) |
| Календарь | Органайзер · Календарь; Профиль · calendar link |
| Уведомления | Настройки · Уведомления (company); Профиль · notifications (personal) |
| Обращения сотрудников | Задачи (new ones); /admin/tickets/:id card; Помощь · «Мои обращения» (/help/requests) |
| Заявки партнёров | Контакты · Контрагенты · applications; task kind `partner_application`; old catalogue address redirects |
| Courses | single place (Настройки · Налоги и валюты reuses ERP `RatesView`) — not a duplicate |

Not checked in this area: duplicated fields inside individual record cards (ЕД-7 covers those).

## 9. File counts for moving a whole route

The numbers below count files that reference the route. If routes stay and only the menu moves (NAV doc L93), use the much smaller menu-only sets in §6.1-6.3.

| Route | e2e | web production code | web unit tests | BFF link builders | Other backend links | help (`screens`) |
|---|---|---|---|---|---|---|
| /eds/mail | 9 | 3 | 5 | 2 | — | 1 |
| /eds/my-mail | 2 | 3 | 4 | (same) | — | (same) |
| /eds/approvals | 4 | 6 | 8 | 2 | — | 1 |
| /eds/projects | 7 | 9 | 12 | 4 | — | 1 |
| /chats/contacts | 2 | 3 | 3 | 0 | — | 1 |
| /chats/calendar | 1 | 1 | 1 | 0 | — | 1 |
| /crm/leads (+/crm/messages) | 11 | 16 | 15 | 2 | CRM platform_links.py L24 | 1 |
| /crm/clients | 15 | 13 | 12 | 4 | — | 1 |
| /eds/tasks | 1 | 2 | 1 | 1 | CRM eds_notices.py L85 | 1 |
| /eds/payments | 7 | 10 | 7 | 2 | ERP bank_details_change.py L150 | 1 |
| /erp/requests | 6 | 6 | 4 | 2 | — | 1 |
| /erp/stock | 9 | 6 | 4 | 2 | ERP supply/services/orders.py L996 | 1 |

Notes on the table:
- The BFF builders are in 12 files in total: feeds/numbers.py, queue.py, search.py, notifications.py, rework.py; schemas_erp_calc.py, schemas_erp_stock.py, schemas_eds_letters.py; eds_approvals.py; clients/eds.py; api/templates_catalog.py; api/mail_sent.py.
- `apps/crm/backend/tests/unit/domain/test_platform_links.py` L72-83 reads every `module.ts` and `settingsRegistry.ts`, so any route change also triggers the CRM CI job.
- `feeds/queue.py` card links still point at legacy paths that redirect: /crm/messages, /eds/drafts, /eds/approvals (L933-987).
- EDS builds no Platform links.
