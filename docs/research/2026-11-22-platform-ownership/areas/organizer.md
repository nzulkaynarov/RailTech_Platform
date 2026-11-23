# AREA D: Органайзер, internal communication, tasks and connectors

All paths are relative to `` (main @ 2ecd40446). Abbreviations: W = `apps/platform/web/src`, BFF = `apps/platform/bff/app`.

## 1. Facts: what exists today

### 1.1 Органайзер module (code name `chats`)
| Item | Fact | Evidence |
|---|---|---|
| Menu | Календарь · Чаты · Люди. Rail label «Органайзер», module code `chats` | W/modules/navigation.ts:127-135; W/shared/i18n/ru/modules.json `chats.name` |
| Routes | `/chats/calendar`, `/chats`, `/chats/contacts` (= «Люди»). Old `?scope=internal` redirects to `/chats`; `?scope=external` redirects to `/crm/leads?scope=waiting` | W/modules/chats/module.ts:9-43; W/modules/chats/index.tsx:15-20 |
| RBAC | `chats.internal` = «Органайзер · Чаты и Люди», full for all 8 roles. `chats.external` = «Контакты · Переписка с клиентами» | packages/contracts/platform-rbac.yaml:349-362, 450-454; role blocks 23-175 |

### 1.2 Calendar (real, read-only, deadlines only)
- **Screen.** FullCalendar showing the user's own queue items that have a `due_at`. Four filters: tasks, documents, invoices, deliveries. Clicking an event opens the object. Source is `useGetQueue` (W/modules/chats/calendar/CalendarPage.tsx:22-76, 85). There are no meetings, no team or other people's calendars, and no own events.
- **Wrong filter label.** The «tasks» filter is labelled «Поручения» (ru modules.json `chats.calendar.kinds.tasks`), but it also contains `answer_lead`, `ticket`, `integration_issue`, `service_request` and others (CalendarPage.tsx:25-39).
- **ICS feed: real, merged 2026-11-22** (commits 9a5e107c9, 8c419ccda, 368c02c22).
  - `GET/POST /me/calendar-link` and a public `GET /calendar/{token}.ics` (BFF/api/calendar.py:45-100).
  - The token hash is stored in CRM `users.calendar_token_hash`. The feed is a Redis snapshot of the queue, refreshed only when the employee opens their queue in the Platform (BFF/calendar_link.py:1-16; BFF/api/dashboard.py:27-36).
  - The snapshot has a 30-day TTL. Disabling the employee wipes it (bus.py:94).
  - The calendar name is hard-coded «RailTech — сроки» (calendar_link.py:32). (inference) This conflicts with DECISIONS 2026-11-10, line 302, which says the platform brand is a setting.
- **Where the link lives.** The link block is in Профиль, part «notifications» (W/features/profile/ProfilePage.tsx:75). The Calendar page button navigates to `/me?part=notifications` (CalendarPage.tsx:117-123).
- **The research is stale on this.** It was checked at 9801bfe57, which does not contain the ICS commits. README §2 row (line 108), §6 Q13 (lines 337-340) and plan inbox line 103 all still call iCal stage 1 «не внесён / вопрос 13».

### 1.3 Chats (placeholder: no storage, no API, no send or receive)
- **ChatsPage is a static layout** on `@chatscope`. Search and message input are disabled, there is no send button, and both groups («Обсуждения на объектах», «Личные») show «Данные появятся здесь». The «Созвон» button is a SoonButton (W/modules/chats/inbox/ChatsPage.tsx:18-56).
- **No internal message entity anywhere.**
  - CRM `Conversation` and `Message` exist only for lead channels `telegram` and `cabinet`, with roles lead/bot/manager/system (apps/crm/backend/app/models/leads.py:132-190).
  - ERP `PortalMessage` is the cabinet chat with a client company, owned by CRM (apps/erp/backend/portal/models.py:289).
  - MODULES.md:104-113 confirms: «Владеет — сейчас ничего… Экран в Платформе — нет, заглушка».
- **Client chats.** The API exists: BFF `GET /chats/external` (BFF/api/chats.py:1-70), plus `/crm/messages/{lead}/thread` and attachments. There is no Organizer screen for them (BACKLOG B-W18AP3-1, line 104). Client conversation is worked in «Контакты · Лиды» (`crm.messages` → `crm.leads`, navigation.ts:85).
- **Who can talk to whom.** Internally: nobody, no implementation. Externally: whoever has `crm.leads` sees all dialogs; whoever has only `chats.external` sees dialogs where they participate or that are invoiced (BFF/api/chats.py:1-8). Replying requires «Забрать» (BACKLOG B-W18AP3-2).
- **Project chat: none.** The calc TaskPanel «Обсуждение» block is placeholder text promising «к пилоту» (W/modules/erp/calc/TaskPanel.tsx:121-126; ru calc.json:266). MODULES.md:113 says «есть только чат в расчёте», which is inaccurate.
- **Doc conflicts.** SPEC-v3 §1 p.6 (line 39), §line 77 `ProjectChat` and §516/660/663 «Чат проекта» are superseded by DECISIONS 2026-11-10 «без групповых каналов» (line 297), but SPEC was not updated. The domain for staff chats is CRM (DECISIONS 2026-10-29 W-9, line 239; BACKLOG B-WDOCS2-6, line 212).

### 1.4 People directory («Органайзер · Люди»)
- **What it is.** A client-side union of three lists: EDS staff (`listEdsStaff`), counterparty people (first 200), and CRM leads (first 100). Kind filter and search. Phone and email of counterparty people appear on click and are logged (W/modules/chats/people/PeoplePage.tsx:36-122).
- **Employees are invisible to most roles.** Staff rows load only with `eds.inbox.register | eds.inbox | admin | eds.signing.manage` at **full** level (PeoplePage.tsx:36-39, 55). Only ADMIN, DIRECTOR and REGISTRAR have that (platform-rbac.yaml:26, 36-37, 132). MANAGER, SUPPLY, ENGINEER, ACCOUNTANT, MANAGER_ALL and LAWYER have only `eds.inbox: read` or nothing, so (inference from the code) they do not see colleagues in «Люди».
- **Employee rows are thin.** They have no phone, email or card link (`revealId: null`, lines 64-72). «Написать» and «Позвонить» are SoonButtons (277-278).
- **Second employee list.** «Настройки · Сотрудники» (/admin/org) is a separate list with its own card (W/modules/admin/org/OrgPage.tsx, EmployeeCard.tsx).
- **Screenshot (b), root cause from code:**
  - ProjectList wraps DataTable in `<Card>` and passes `className="pf-dec-table"` (W/modules/eds/projects/ProjectList.tsx:233, 410). That class gives a left-aligned header, a subtle header band and row lines (W/modules/eds/decision/decision.css:81-92).
  - PeoplePage passes no className and no Card (PeoplePage.tsx:223-231).
  - The shared `.pf-fixed-table th` sets no `text-align` (W/shared/ui/data-block.css:105-117), and no reset is imported (W/main.tsx). (inference) So headers fall back to the browser default, which centres them.
  - The same holds for every DataTable usage without a module class: admin/org/EmployeeList.tsx:76 (saved only by Card, OrgPage.tsx:207), admin/bus/SubscribersView.tsx:142, admin/company/common.tsx:519, admin/docflow/DictionaryFile.tsx:163, admin/settings/TemplateCatalog.tsx:110, eds/mail/SentMail.tsx:116.
  - Header styling is otherwise spread over about 10 per-module classes: pf-dec-, pf-crm-, pf-docs-, pf-calc-, pf-cat-, pf-kb-, pf-bot-, pf-int-, pf-letters-, pf-pay-table.
- **Other ui-standard breaks on People:**
  - Drawer is 400 px; the standard allows only 480 or 640 (ui-standard.md:107; PeoplePage.tsx:233-236).
  - The row does not open the card; only the name button does (§7 line 123).
  - A bordered «Показать» button sits in every row; §7 line 124 says no bordered buttons in rows (PeoplePage.tsx:127-138).
  - Loading is a paragraph skeleton and the empty state is a bare hint; §7 line 128 requires a table-shaped skeleton and an EmptyState (PeoplePage.tsx:218-221).

### 1.5 Tasks and assignments
- **Instructions (поручения) are the only employee-to-employee task entity, and only from an incoming letter.** `Instruction.letter_id` is a non-null FK to `letters` (apps/eds/app/models/instructions.py:37-69). It carries due date, report, extensions with reason and decision (72-98), and «ознакомить» (101-114).
- **Other "tasks" are derived queue rows,** not stored tasks: about 33 `QueueItemKind`s (CalendarPage.tsx:25-60). Assignments come from domain objects: CRM lead assignee and «Передать коллеге», ERP calc visas per group (TaskPanel.tsx:106-119), EDS approval steps (models/approvals.py:78-84), signing.
- **No free task or free project.** MODULES.md:88-94: «"Мои задачи" единым списком — нет; Произвольная задача и проект без сделки — нет»; «Модуля как отдельной системы нет». NAVIGATION.md:76: «Поручения без входящего документа в системе пока нет».
- **«Поручение» and «Сообщение» in the Create window are disabled** «вместе с чатами» (W/app/shell/createKinds.ts:84-96); plan Х-7 (plan-2026-11-12.md:223).
- **Planned generic task.** A `WorkItem` contract (kind, object ref, person or role, due date, `on_behalf_of`) is phase 3, February, post-launch (ADR-0031:65, 91; research/2026-11-21-processes-as-data/README.md:173, 260).
- **Staff → admin requests** exist (CRM `StaffTicket`/`StaffTicketMessage`, models/staff_tickets.py:25-62).

### 1.6 Meetings
None. There is no meeting entity in CRM, ERP, EDS, BFF or web, and no Telemost code (grep across apps). Decided but not built: «Встреча» as a CRM object, an `.ics` invite and «Назначить встречу» (DECISIONS 2026-11-03, line 259, stage 2).

### 1.7 Project status tracking
- **Main list.** «Главная · Проекты» (`eds.projects`, navigation.ts:82): client status, step, contract/invoice/act tags, due date, responsible (ProjectList.tsx:142-214). Also the project card, the `problem_project` queue row and Cabinet.
- **One object, one home.** A project is the deal after the КП is accepted; «заявка и проект — один объект с одной карточкой» (DECISIONS 2026-11-10 architect, line 299; NAVIGATION.md:23).
- **One definition of «выполнен»** for all systems (DECISIONS 2026-11-22, line 361).

### 1.8 Internal correspondence (Документы · Внутренние)
- **Kinds.** EDS `Document.kind` is one of memo, application, report, letter_out. Internal kinds get СЗ/ЗЯ/ОТ numbers at creation; the letter gets ИСХ at sending (apps/eds/app/models/documents.py:28-33). Fields include amount and currency, addressee, watchers, extra approvers.
- **Routes.** ApprovalRoute templates are memo, application, report, quote, signing (models/approvals.py:36). A memo with an amount, once approved, goes to the accountant: `DocumentPayment` (documents.py:125+) and «Операции · Финансы · Служебки» (navigation.ts:73-75, 120).
- **Legal weight.** The signing state applies only to `letter_out` (apps/eds/app/services/signing_state.py:16, 25). SPEC-v3 line 38: legally significant actions (operator signature, bank) stay outside the platform; only the result is recorded. (inference) So internal docs are numbered, routed administrative documents without e-signature, and many of them are money requests.
- **Placement.** Под «Документами» by owner decision Q-NAV-1 (DECISIONS 2026-11-10, line 301; NAVIGATION.md:16).

### 1.9 Comments and discussion on objects
- **No generic discussion API or storage.**
  - The «Обсуждение» tab (`chat`) is declared in `RECORD_TABS` (W/modules/types.ts:62-80) and in section tabs (eds/module.ts:27, 71, 79, 86; erp/module.ts:4).
  - No `PanelPortal tab="chat"` exists anywhere: the only filled tabs are card, history, facts, task, step, role, resolution, journal and employees.
  - Under ЕД-7 empty tabs are hidden (DECISIONS line 364), so the tab is never visible. Plan inbox line 107: «"Обсуждение" и "Документы" нигде не заполнены».
- **Comment-like data that does exist:**
  - CRM `LeadNote`, the team note on a lead (leads.py:199-210; served via `/crm/messages/{lead}/thread`).
  - Approval decision comments (required on return or reject).
  - Instruction report and extension reasons.
  - Cabinet `QuoteComment` and `PortalMessage` (client side).
  - Staff ticket messages.
- **Planned.** `@человек` / `@документ` mentions are post-launch (plan:258).

### 1.10 Notifications
- **Bell.** CRM and ERP feeds via BFF (BFF/api/notifications.py:1). CRM `StaffNotification` (staff_tickets.py:63+). Gated by `dashboard.queue`.
- **Personal Telegram.** CRM flags `notify_system` and `notify_leads`; profile settings and test message (BFF/api/me_notifications.py:1-6).
- **Team channel.** A Telegram channel with lead hand-off cards and «Забрать» (apps/crm/backend/app/services/notifications.py:1-6; bot/channel.py).
- **Settings «Уведомления»** covers only the team channel and failure alerts (settingsRegistry.ts:393-400). The event × recipient × channel matrix is B-SETIA-4 (BACKLOG:231).
- **In flight.** ГЛ-2 badge and per-task signal (plan:146; DECISIONS line 365).
- **Known gap.** B-P8B-3: instruction notifications are sent to Telegram ignoring personal settings (BACKLOG:184).

### 1.11 HR-specific functions (complete list)
| Function | State | Evidence |
|---|---|---|
| Employees: invite, roles, status, Telegram, ERP provisioning | exists, in Настройки · Сотрудники (ADMIN; DIRECTOR read-only) | OrgPage.tsx:30-33; settingsRegistry.ts:46-60 |
| Employee fields | name, email, position, phone, timezone, language, avatar, signature, TOTP | crm/models/auth.py (User) |
| Absence / deputy | deputy and period, set **by the employee in Профиль**; the deputy acts for them (not signature, not payment) | W/features/profile/DeputySection.tsx:23-27; crm auth.py:128-132; eds models/employee.py:46-48; DECISIONS 2026-11-21 (2), line 359; ЕД-6 (3), line 362 |
| Absence types (vacation, sick leave), absence calendar | none | — |
| Departments, manager, org chart | none; «руководитель» field is phase 2 (January) | DECISIONS 2026-11-21 (7), line 360; plan:266 |
| Signing authority register | exists (Настройки · Права подписи) | settingsRegistry.ts:80 |
| «Заявление» (application) document kind | exists as an internal doc | documents.py:33 |
| Working hours, holidays | «Время и сроки» (SLA, working hours); holidays are B-P8B-2 | settingsRegistry.ts:376-390; workspace.md §D (lines 75-80) |
| Payroll, HR records | out of scope: «кадры и зарплата — чужой участок, учёт в 1С» | connectors README §3.4, line 187 |

## 2. What the connectors research (2026-11-22) concluded
| Domain | Verdict | Evidence |
|---|---|---|
| Base suite | Яндекс 360 stays («уже есть»); switching to Google or Microsoft makes no sense | README:105; workspace.md:22-25 |
| Foundation for all 360 connectors | «Сервисное приложение» (token exchange, admin key instead of app passwords). Needs Asosiy or higher; company tariff unknown; staff must be notified | workspace.md:7-13, 40; README:107 |
| Mail | outbound SMTP via 360 works; inbound IMAP code ready (prod info@ is an owner action). Move to service-app OAuth later. No personal-mailbox client proposed | README:41-42; workspace.md:39 |
| MCP servers 360 | owner decision before launch: disable (rec. (a)); conflicts with DECISIONS 2026-11-11 p.1 | README:106, Q2 (301-303); workspace.md:41 |
| Calendar | stage 1 iCal (now built), then `.ics` invite plus video meeting button (CRM, 2 PR, Jan, §3.2 #10), then two-way CalDAV (M–L, after pilot). Libraries icalendar and caldav (Apache licence) | README:69, 108, 144, 213; workspace.md:43-46 |
| Messengers | Telegram Business is the best post-launch connector: managers' client chats land in the **lead or counterparty card in CRM**. Jan, 2 PR, consent needed; Premium not needed (verify/api-reality.md:9; law-risk.md:121). Messenger 360 bot «не нужно — дублирует Telegram». WhatsApp later | README:20, 63, 135, 192; workspace.md:47 |
| Task trackers | Yandex Tracker «не нужно»: visa, signature and resolution stay only in the Platform. Jira and Notion only on real need (Notion blocks Russian suppliers). Trello no | workspace.md:52, 62-64, 93 |
| Storage | Yandex Disk as archive via admin key later; offsite backup code exists but is off; price list via public Disk link (S) | README:44, 70, 104 |
| Directory and HR-relevant | 360 directory API: one-time employee import and «logout from all sessions» on dismissal, S, later | workspace.md:42, 88; README:107, 161 |
| Login | own login stays; «Войти через Яндекс» later via a generic OAuth client | workspace.md:26-29 |
| Owner decisions on the 13 questions | **none recorded.** Plan:103 says «ждёт ответов владельца на 13 вопросов»; nothing in DECISIONS after 2026-11-22 about connectors | DECISIONS:361-365 |
| Internal flaws in the research | Q13 has two «Рекомендую (а)» lines (README:339-340). comms.md:24 still says Premium is needed (corrected only in verify/). Q13 is stale versus code (§1.2) | — |

## 3. Gap analysis: «Органайзер = all organisational part, owner HR»
| Owner element | Buildable on existing data | Needs a connector (per research) | Contradicts an accepted decision |
|---|---|---|---|
| Communication between employees | Nothing exists. Needs new storage in CRM (W-9) and the existing chatscope layout | Messenger 360: research says no (duplicates Telegram) | Allowed: personal messages and discussions on objects. **Group channels and internal calls are banned** (DECISIONS 2026-11-10, line 297). The «Созвон» button on ChatsPage:29 is in tension with this; NAVIGATION:69 allows a call only in an external service |
| Communication with clients and partners «within a project» in Organizer | Data exists (CRM dialogs, cabinet chat, `/chats/external`) | Telegram Business, into the **CRM card** | **Yes:** «Чаты только внутри компании; переписка с контрагентами — в карточках» (NAVIGATION:18, 49, 188; DECISIONS 2026-11-10, line 300) |
| Meetings | No entity | `.ics` plus video meeting (360), CalDAV later | Planning as a CRM object is allowed. **«Свой полный календарь не делаем, личные события не храним»** (DECISIONS:259, 303) |
| Tasks | Instructions (letter-bound) and queue rows only. A free task needs `WorkItem` (Feb) | Jira or Notion only on need | Tracker «не нужно». Visa, signature and resolution only in the Platform (DECISIONS:303) |
| Project status tracking | Exists in Главная · Проекты | — | «У объекта один дом» (NAVIGATION:6). Project = deal = заявка (DECISIONS:299). A second home in Organizer would duplicate it, the very thing the owner criticises |
| Calendars | Deadlines calendar and ICS built | CalDAV, .ics | consistent |
| Mail «as a connector» in Organizer | The current «Почта» is the shared info@ intake (`eds.mail`, visible to triage, leads and mail roles; rbac menu `eds.mail`), which feeds leads and incoming registration | 360 service app | (inference) Moving it to Organizer mixes lead intake and registration with internal communication. Removing it from Контакты cuts one of the lead sources (mail, tenders via mail: README:19, 64) unless re-homed |
| Internal memos moved to Organizer | They are numbered EDS documents with approval routes and money (payments) | — | Q-NAV-1 placed them in Документы (DECISIONS:301). (inference) The owner's split «legal force vs internal» is consistent with the fact that only `letter_out` is signed, but memos would lose the shared archive and number registry |
| HR ownership | Employees, deputy, signing rights, «заявление» exist, all in Настройки or Профиль | 360 directory (import, dismissal logout) | «Кадры и зарплата — 1С, не строим» (README:187). The «руководитель» field is planned for January. No absence types or org structure |
| «Do not reinvent» | FullCalendar and chatscope already used, as ruled | — | DECISIONS 2026-11-10 (line 306) and plan:103 |

**Duplication the owner complained about, inside this area:**
- Employees are in two lists: Настройки · Сотрудники and Органайзер · Люди.
- Notification settings live in three places: Профиль, Настройки · Уведомления, and the iCal link under Профиль «notifications».
- The «Обсуждение» tab is declared in about 7 places and filled in none.
- The calc «Обсуждение» block is a stale placeholder.
- (inference) The «Люди» table is unstyled because header styling sits in per-module CSS classes rather than in the shared DataTable.
