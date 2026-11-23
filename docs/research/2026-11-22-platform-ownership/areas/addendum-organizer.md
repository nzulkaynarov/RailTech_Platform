# AREA O: Органайзер as the project manager's workplace and internal engine

Root: ``. Short forms: W = `apps/platform/web/src`, BFF = `apps/platform/bff/app`, DEC = `docs/DECISIONS.md`, NAV = `docs/product/NAVIGATION.md`, CONN = `docs/research/2026-11-22-connectors/README.md`, WS = `docs/research/2026-11-22-connectors/areas/workspace.md`, REP = `docs/research/2026-11-22-platform-ownership/README.md`. Size scale is the one in REP §8 line 466: S = 1–2 PR, M = 3–6, L = 8–15. I added **XL = more than 15 PR or a new service**. CONN uses a different scale (S = 1 PR, M = 2, L = 4–6; CONN line 7), so its sizes are quoted as written there. This area extends `areas/organizer.md` and does not repeat it.

## 0. Verdict

1. **The owner's addition is not new in principle.** He already accepted a WFM/PM box in MODULES.md:77-94: «Владеет: задачи, поручения, проекты-досье, сроки и просрочки». The same box says: «своя база — когда появятся задачи вне документов». Projects of any kind, meetings, notes and files are exactly that condition. The addition triggers the WFM box; it does not invent it. ADR-0031 §1 (line 33) rejected a central process service because it «не было бы главного пользователя» (ORCHESTRATOR §3 p.1). Naming the PM as main user removes that objection for the WFM box. It does not remove it for document routes, which stay with EDS and ERP.
2. **Building all seven elements internally is about 60–100+ PR (inference).** The plan says about 100 PR remain before launch (plan-2026-11-12.md:285). The «Процессы как данные» programme (about 55 PR) is already queued after launch (plan:262-283). Launch is estimated at 26–31.12 (plan:287). **Nothing new here can go before launch except «Люди» (S, already in REP).**
3. **Four earlier decisions block parts of the list as written:**
   - group channels and internal calls (DEC 2026-11-10, line 297);
   - our own full calendar and stored personal events (DEC 2026-11-03, line 259; DEC 2026-11-10, line 303);
   - «Велосипеды не делаем» (DEC 2026-11-10, line 306) and «не изобретать велосипед» (plan:103, 22.11). Mail, calendar, disk, messenger, wiki, tracker and video calls are already paid for in Яндекс 360 (CONN:105; WS:7);
   - «меню модуля — не больше пяти коротких пунктов» (NAV:6). The owner lists six items.
4. **«Stage is closed when all its tasks are done» conflicts with two accepted rules:**
   - statuses with legal or money meaning stay in code (DEC 2026-11-21, line 360 (2); ADR-0031 §5, line 44);
   - «проект выполнен» = act accepted plus all invoices paid (DEC 2026-11-22, line 361 (2)).
   For deal projects the stage must close by the document's status. Tasks can only give progress.

## 1. Element by element

| Element | Exists in code today (beyond organizer.md) | Earlier owner decisions | Connectors research verdict | Honest internal size and main components |
|---|---|---|---|---|
| **Projects with a kanban of stages and tasks** | Deal projects only. ERP `Deal`: `stage` FK to `DealStage`, `is_project`, `manager`, `assigned_to`, `notes` (apps/erp/backend/sales/models/deals.py:17-140). There are 9 ERP stage codes (apps/erp/backend/crm/constants.py:13-22). SPEC defines one 7-stage scale: Заявка, Резолюция, Расчёт, КП, Договор, Оплата, Выполнено, plus Отказ (SPEC-v3.md:113-128). Execution runs in parallel between steps 6 and 7 (SPEC-v3.md:128). The list is «Главная · Проекты»: `eds.projects` (W/modules/navigation.ts:83; rbac:273). **No kanban component in the web app** (no kanban or dnd package in apps/platform/web/package.json; grep finds no kanban). No stored task and no project without a deal (MODULES.md:88-94). A `WorkItem` contract is planned for phase 3, February (ADR-0031 §11, line 65; phase table line 91) | Заявка and проект are one object with one card (DEC 10.11, line 299). Tasks: «всё, что ждёт моего действия» on Главная (NAV:23; DEC 22.11, line 365). Projects and tasks connect to corporate services in Settings (DEC 10.11, line 303). Statuses with legal or money meaning stay in code (DEC 21.11 (2), line 360). Drag of panels comes after launch (DEC 10.11, line 297) | Yandex Tracker «не нужно» (WS:52). Jira and Notion only on real need. Notion has blocked users in Russia, so Russian suppliers cannot be invited (WS:62-64, 93). Trello no (WS:63) | (a) Read-only kanban of deal projects by the SPEC 7 stages: **S–M**. Data exists; cards move only by domain actions, never by drag. (b) Projects without a deal, stored stages and tasks, completion rule, members: **L**. It overlaps ADR-0031 phase 3 (19–20 PR). (c) As its own WFM service: **XL**. That means a new DB, migrations, a new bus domain (contract change, §3), RBAC resources, backups and BFF clients. Components: storage (none today; BFF has no DB: BFF/calendar_link.py:1-2); realtime (SSE hints exist, no data in the stream: BFF/api/events.py:1-6); search (⌘K exists: BFF/api/search.py); mobile (390 layouts); notifications (bell plus Telegram; ГЛ-2); retention (none); access (project membership, a new resource); audit (journal) |
| **Calendar: events, deadlines, meetings** | Deadlines and the ICS feed exist (organizer.md §1.2). The feed is a Redis snapshot of the queue, refreshed only when the employee opens the Platform (BFF/calendar_link.py:1-16). It is one-way. No meeting entity anywhere (organizer.md §1.6). FullCalendar MIT is installed (package.json:32-35) | «Свой полный календарь не делаем, личные события не храним». Stage 2 is «Встреча» as a CRM object with `.ics` (DEC 03.11, line 259). Personal events and meetings live in the work calendar, shown here through a connection, not stored here (NAV:48) | iCal is built. `.ics` invite plus video meeting is January, 2 PR, CRM (CONN §3.2 #10, line 144). Two-way CalDAV is M–L after the pilot, through the service app, not app passwords (WS:43, 100). Yandex refreshes subscriptions only every few hours, so the feed suits deadlines, not «через 30 минут» (WS:44) | Meeting object with invite and video link: **M**. Own full calendar (personal events, recurrence, free/busy, rooms, a CalDAV server): **XL, and forbidden** by 03.11 and 10.11 |
| **People** | As organizer.md §1.4. Employee identity is the CRM IdP (ADR-0003). The 360 directory is not connected | One list; name, company and position visible to all; phone and email on click with a log entry; no export. Only own book syncs outward (DEC 10.11, line 300; NAV:50-56) | 360 directory: one-time import plus «выход из всех сессий» on dismissal, S, later. No directory webhooks, polling only (WS:42, 105). CardDAV for the organisation's book is not documented (WS:113) | Fix: **S**, before launch (REP §7). Merge into one entity: **M**, backend stage |
| **Own mail (incoming and outgoing)** | Only the company's shared intake box (CRM IMAP, read-only `EXAMINE`; apps/crm/backend/app/integrations/imap.py:1-9). One SMTP sender for the whole ensemble with optional Reply-To (smtp.py:1-7, 187-201). Registry key `mail`: «Вся исходящая почта ансамбля» (external_registry.py:119-131). **No personal mailbox** | Director reads the whole shared queue; a manager sees only his own letters (DEC 13.11, line 328). **Every outgoing letter goes through «Подписать», paper too** (DEC 21.11 (3), line 359). Outgoing letters get the registrar's «оформление» visa (DEC 12.11, line 321) | SMTP works; inbound IMAP is ready. Move to service-app OAuth later. **No personal-mailbox client proposed** (CONN:41-42; WS:39). REP leaves it as question 22 (REP:542). The owner's addition answers «yes» | Own mail client (folders, threads, search, drafts, attachments, spam, signatures, mobile, legal hold): **XL (inference)**. Connect Yandex Mail through the service app instead: «my letters» list, «attach to object», «send as me»: **M (inference)**, with tariff caveat Asosiy+ (WS:10). **Risk:** a personal outbox becomes a bypass of the signed-outgoing rule of 21.11 |
| **Messenger: groups, channels, chats** | Placeholder only (organizer.md §1.3). Staff chats belong to the CRM domain (DEC 2026-10-29 W-9, line 239) | Inside the company: object discussions and personal messages, **without group channels and calls** (DEC 10.11, line 297; rationale: work talk stays inside, research/2026-11-10-workspace-ux.md:77). Chats send copies and notifications outward, replies come back into the Platform, a call opens in an external service (NAV:69) | Yandex Messenger bot «не нужно — дублирует Telegram» (CONN:192; WS:47). Telegram Business puts managers' client chats into the CRM card, January, 2 PR (CONN:20, 135) | Personal messages plus object discussions: **L** (REP §7). Groups and channels (presence, read receipts, moderation, push, retention): **XL, and forbidden** by 10.11 |
| **Notes** | Only `LeadNote` (team note on a lead, CRM leads.py:199-210) and `Deal.notes` (deals.py:89-94). The «Обсуждение» tab is declared and filled nowhere (organizer.md §1.9). Personal notes: none | No decision on notes. Workspace research: team notes on the object only (workspace-ux.md:77) | Yandex Wiki «позже», only if the company already keeps regulations there (WS:54). Notion on need (WS:64). **Obsidian is not mentioned anywhere in the repo** (grep). (inference, not verified this session) Obsidian is a local Markdown vault with no official server API; a «connector» is realistically import and export of a Markdown folder | Personal notes with object links: **S–M**. Shared wiki with permissions, versions and search: **L** |
| **Files: own and shared folder** | S3 in Tashkent (CONN:44). EDS `StoredFile`/`FileVersion` with sha256 and versions; a file belongs to at most one letter, document or instruction; **an unattached file is visible only to its uploader** (apps/eds/app/models/files.py:1-45). That is the seed of «my files». ERP attachments: sourcing/models.py:18; portal/models.py:158. No folders and no sharing | No decision on folders. The documents archive is the home of numbered documents (DEC 10.11, line 301; REP §4.1) | Yandex Disk REST plus service app, «позже» (WS:48; CONN:104). Off-site backup code exists but is off (CONN:44). Price list via public link, S (CONN:70) | Folders, ACL, sharing, preview, quotas, search: **L–XL (inference)**. Connect Yandex Disk: **M**. **Risk:** a shared folder becomes a second home for documents |

Sum (inference): a usable internal level is about L + M + S + XL + L + M + L, i.e. **60–100+ PR**. That is the same order as the whole remaining pre-launch queue.

## 2. «Project → stages → tasks»: where it fits the facts and where it does not

| Owner's rule | Fact | Assessment |
|---|---|---|
| A project is the parent; КП, contract and act are its stages | SPEC §2.3 already has stages КП (4), Договор (5), Оплата (6), Выполнено (7), each with one owner (SPEC-v3.md:117-125). But today «проект» = the deal **after** the КП is accepted, number RQ→PRJ (deals.py:96-112; NAV:23) | Consistent if «project» = the whole заявка→проект object (DEC 10.11, line 299). Then the «Заявки» list and the «Проекты» list are two lists of one object (§6) |
| Correspondence, supplier orders, payments and meetings are the tasks of a stage | Supplier orders, payments, letters, invoices and acts are domain objects with their own statuses and owners (ERP, EDS; SPEC-v3.md:56-84; ORCHESTRATOR §3 p.16). Today's «tasks» are about 33 derived queue kinds, not stored rows (organizer.md §1.5) | As data, a «task» must be a **WorkItem that points to the object** (kind, object ref, person or role, due date, `on_behalf_of`: ADR-0031 §11; research §173/260). It cannot be a copy of the order or payment. Planned for February |
| A stage closes when all its tasks are done; a project is 100% when all stages are closed | «Выполнен» = act accepted plus all invoices paid (DEC 22.11 (2), line 361). Statuses with legal or money meaning stay in code (DEC 21.11 (2); ADR-0031 §5). Execution runs in parallel with payment (SPEC-v3.md:128) | **Conflicts.** If every task is ticked, «Договор» would close without a signed contract. One open meeting task would block a paid, accepted project. Proposal: for deal projects, stage closure = locked domain status and tasks give progress only; for non-deal projects the owner's rule applies as written. A percentage by task count is a misleading measure (inference) |
| Kanban inside the project | No kanban in the web app. Drag of panels is post-launch (DEC 10.11, line 297). The process editor has no drag (ADR-0031 §3) | Columns = stages, cards = tasks. A card or project moves only by a domain action, not by drag. **Open question:** does the owner mean «columns = stages» or «columns = task status»? |
| The PM is accountable for all stages | No PM role. The roles are 2 system roles + 7 templates: ADMIN, DIRECTOR, MANAGER, SUPPLY, ENGINEER, ACCOUNTANT, REGISTRAR, MANAGER_ALL, LAWYER (rbac:22-173). Each SPEC stage has its own owner (SPEC-v3.md:117-125) | Compatible as an **overseer**, not as the executor of every step. Roles are data (ADR-0012 §1-2, adr/0012…md:29-39), so a «Менеджер проектов» template is a catalogue PR, not hard-coding. The owner's «don't hard-code roles» is already the architecture |

## 3. Integration layer: what exists today

| Piece | Fact | Evidence |
|---|---|---|
| «Настройки · Подключения» | One page `/admin/integrations` (group `channels`). Cards in order: erp, telegram, mail, services, models, spend, storage, system. Card level = the worst of its services; there is a «Требует внимания» list | W/modules/admin/settingsRegistry.ts:434-437; BFF/integrations_overview.py:1-16, 57-66 |
| Service model | CRM `ServiceSpec` with fields key, title, purpose, system, source, check, tiers, fix_path, switch, vendor. Status is one of `ok`, `warn`, `fail`, `unknown`, `off`. Rule: «новый внешний сервис принимается в код только со строкой здесь» | apps/crm/backend/app/domain/external_registry.py:1-10, 17, 61-72 |
| Endpoints | Hand-written per service: ERP pair/rotate/check, Telegram token/profile/channel, SMTP, offsite, models, spend, backups, system. **No generic connector model** | BFF/api/admin_integrations.py:115-639 |
| Secrets | Fernet in CRM `integration_secrets`; the API returns only `configured`, `last4` and `updated_at` | apps/crm/backend/app/security/secrets_store.py:1-5 |
| Auth to outside services | **No Yandex OAuth and no service app.** Yandex Disk uses WebDAV with an app password (crm integrations/yadisk.py:1-7). IMAP and SMTP use app passwords (imap.py:4). Google Drive uses a service-account JWT (crm integrations/gdrive.py:70) | grep for oauth, token-exchange, service_app |
| Bus | CloudEvents with HMAC delivery, outbox and inbox. ADR-0014 §5: external systems only through connectors with their own queue and container and a **manifest** (version, subscriptions, rights, settings, secrets, enable flag), three templates (polling API, inbound calls, manual adapter) and a daily reconciliation. The envelope already reserves `source rt://connector-<имя>`. **But the event `type` pattern allows only the domains `crm\|erp\|eds\|identity\|platform`** | docs/adr/0014-integration-bus-rt-bus.md:21-22; packages/contracts/events/envelope.v1.json:33, 37, 57; docs/architecture/rt-bus.md:255-266 |
| Event contracts | Events exist for deal, quote, contract, invoice, act, delivery, request (ERP); approval, letter, document, signing (EDS); lead, contact, client, mail (CRM); identity.user. **No events for project, stage, task, meeting, message, note or folder file** | packages/contracts/events/* |
| MCP | `erp-mcp` 0.1.0 has 7 tools for the **client bot** with a signed agent context (packages/contracts/mcp-tools.json). The CRM MCP servers `kb`, `crm` and `docs` serve the dialog agent (apps/crm/backend/app/mcp/servers.py:1-9). **Not a staff or connector API.** The 360 MCP servers are recommended off (CONN Q2:301-303) | — |
| Webhooks | Only the Telegram webhook (apps/crm/scripts/set_webhook.py) and the old ERP↔CRM webhook secrets (secrets_store.py:26-30). There are no outbound webhooks for third parties, and ADR-0031 §2 forbids «вебхуков в обход «Подключений»» | adr/0031:36 |
| ICS feed | Only one-way output: a token hash, a 30-day snapshot, wiped on deactivation | BFF/api/calendar.py:45-100; BFF/calendar_link.py:1-16 |

**Conclusion:** there is a health-and-secrets registry and a bus that is ready for connectors on paper. There is **no connector framework**: no manifest model, no identity-mapping table, no sync engine, no conflict handling and no connector event domain. (inference: grep for «manifest» finds only ERP pairing.)

## 4. What a «connector standard» must define (one port, internal engine or external tool)

| Point | Must define | Anchor in existing rules |
|---|---|---|
| Object model | `project` (kind deal\|internal, owner, members, status, derived progress, `erp_deal_id`). `stage` (order, kind = locked SPEC code `QUOTE/CONTRACT/PAYMENT/DONE` or free, closure rule `domain\|all_tasks`). `task` = WorkItem (kind, object ref, person or role, due, `on_behalf_of`, status, stage). `event` = iCalendar VEVENT (uid, start, end, organizer, attendees, video URL). `message` (thread = object or direct message, author, team-only visibility). `note` (owner, Markdown, object links, private or shared). `file` = EDS model (versions, sha256, owner object or folder, ACL) | SPEC-v3.md:119-128 codes; ADR-0031 §11; RFC 5545 (WS:44); eds/models/files.py |
| Identity mapping | Table `(connector, object_type, our_id, ext_id, ext_version, last_synced_at)`. People by corporate e-mail mapped to the CRM user (360 token exchange uses e-mail as `subject_token`). Counterparties' people never leave, except the employee's own book | ORCHESTRATOR §3 p.2 (external ids); WS:40; NAV:56 |
| Sync direction | Declared per object type: out-only mirror, in-only, or two-way **only field by field** with one owner per field | ORCHESTRATOR §3 p.16 |
| Conflict rule | Field ownership, not «last write wins». Locked statuses are never accepted from outside. An outside edit of our field is reverted, logged and signalled. For objects the external tool owns, the tool wins and we keep a projection | ADR-0031 §5; DEC 10.11 (line 303) «Виза, подпись и резолюция завершаются только в Платформе» |
| Permissions | One service principal per connector with minimal scopes. Per-user delegation through the 360 service app. Syncing never widens visibility («маршрут = доступ»). Outbound filter: no amounts, prices or deal terms. Personal-data rules. Employee consent | ADR-0031 §7; DEC 303; CONN §5.1; WS:11 |
| Audit | Append-only journal of each sync operation and each configuration change. Reveals of people's contacts are logged | ADR-0031 §8; DEC 300 |
| Contract | A manifest per ADR-0014 §5, a row in `external_registry`, and events from `rt://connector-<имя>`. **Needs a contract change:** a new event domain (or `wfm`) in envelope patterns lines 37 and 57, through ADR and `contract-change` | envelope.v1.json:37, 57; ORCHESTRATOR §3 p.3, p.10 |
| Failure signals on «Состояние» | Reuse the 5 levels and the attention list. Per connector: auth expired or revoked, age of the last successful sync, backlog or DLQ (`bus_dlq` exists), pending conflicts, unmapped users, quota or rate limit, daily reconciliation diff, switched off. A route to fix it, and «к кому обратиться» for people who cannot fix it | external_registry.py:17, 248; REP §6.3 |
| Naming | Vendor names only in «Подключения» | DEC 10.11, line 302 |

Honest limit: interchangeability works only for **satellite objects**. For system-of-record objects an external tool can only be a mirror, so «interchangeable» is not achievable there (inference, follows from DEC 303). There is no common open standard for projects and tasks: Jira, Notion and Linear APIs are proprietary, and iCalendar VTODO support in Yandex is not verified (inference). Each such tool therefore needs its own adapter behind the port.

## 5. System of record: ours, or allowed outside

| Must be ours (documents, money, approvals, identity) | Can live in an external tool, with only links and statuses mirrored |
|---|---|
| Deal projects and their stages: заявка, КП, договор, счёт, оплата, акт (ERP, EDS) | Non-deal internal projects and tasks (Jira or Notion, «по потребности», WS:62-64) |
| Supplier orders and payments (ERP) | Personal calendar events: **must** be external (DEC 03.11, line 259) |
| Visas, signatures, resolutions (DEC 303) | Video meetings (Телемост, CONN:69) |
| Registered incoming and outgoing letters (EDS; DEC 21.11 (3)) | Personal mailbox (Yandex Mail), on condition that official letters still go through EDS |
| Files attached to records (EDS S3, Tashkent) | Group chats, channels, calls: only outside, since banned inside (DEC 297; NAV:69) |
| Employee identity and roles (CRM IdP, ADR-0003, ADR-0012) | Personal notes (Obsidian, Notion, Wiki), with a no-PII and no-prices rule |
| Counterparties' people (DEC 300) | Working files and shared folders that are not records (Yandex Disk) |
| Internal personal messages and object discussions («ответы возвращаются в Платформу», NAV:69) | — |
| The meeting **object** with a counterparty (DEC 03.11, stage 2), deadlines, the audit journal | — |

## 6. «Проекты» in Органайзер, the rule «у объекта один дом», and REP's question 4

- **The rule survives if there is exactly one list.** Today there are two lists of one object: «Операции · Заявки» and «Главная · Проекты» (NAV:42; navigation.ts:69, 83). REP proposes putting both in «Операции» (REP:235, 515).
- **The owner's addition makes the КП a stage of the project.** So the project starts at the заявка. If «Проекты» goes to Органайзер, then «Операции · Заявки» becomes a second home and must go too. «Операции» would keep Закупки, Каталог and Финансы (inference).
- **Home is a screen idea; ERP still owns the data.** MODULES.md:7-8: «У объекта один дом, кнопка может стоять где угодно». So Органайзер can be the home of the project list without moving data.
- **Choose by main user.** If the PM owns projects, Органайзер is coherent. Caveats:
  - there is no PM role in the pilot (4 templates, SPEC-v3.md:377);
  - the daily user of the заявка is the sales manager (rbac MANAGER, `erp.calc: full`; DEC 13.11, line 328).
- **REP needs four corrections:**
  1. Question 4 becomes «one list "Проекты" (заявка→проект, kanban by the 7 stages): Органайзер (PM) or Операции (manager)».
  2. The row «Статусы проектов — не согласен» in REP §3.6 (line 166) is withdrawn if the single list moves; it is not a second registry.
  3. The row «Задачи — спорит с решением 22.11» (REP:165) is narrowed. There is no conflict if the task's home is its project card and «Главная · Задачи» stays the only «my tasks» view. The conflict exists only if Органайзер gets a second «my tasks» list.
  4. The «Задача» row in REP §4.1 (line 211, «не хранится») changes to «stored WorkItem from February; home is the project card; Главная and Календарь are витрины».
- **Menu limit:** Проекты · Календарь · Люди · Сообщения (почта + чаты) · Заметки · Файлы = 6, against «не больше пяти» (NAV:6). Options: notes and files inside the project card and «Мои материалы» (inference), or the owner relaxes the rule.

## 7. Conflicts to state plainly

1. Groups and channels: DEC 2026-11-10, line 297: «без групповых каналов и звонков».
2. Own calendar: DEC 2026-11-03, line 259: «Свой полный календарь не делаем, личные события не храним». Repeated in DEC 10.11, line 303.
3. «Не изобретать велосипед» (plan:103, 22.11) and «Велосипеды не делаем» (DEC 10.11, line 306) against an internal mail client, drive and messenger, while 360 is paid for (CONN:105).
4. Яндекс 360 is the base ecosystem (DEC 10.11, line 303). The research verdicts put mail, calendar and disk in 360 (WS:39-48).
5. Personal outgoing mail against «любое исходящее — через «Подписать»» (DEC 21.11 (3), line 359) and the registrar role the owner himself describes (item 9 of his list).
6. Completion rule against DEC 22.11 (2) (line 361) and DEC 21.11 (2) (line 360).
7. The launch condition «ничего не скрыто» (DEC 10.11, line 301; NAV:78). New menu items would add more «появится здесь» screens, which is the «сыро» complaint (REP question 2). Recommendation: do not add Органайзер items before launch.
8. The jurist confirmation from DEC 10.11, line 303 («передачу названий задач с именами в Яндекс 360») has no later DECISIONS row (inference: not found). Any task connector waits for it.

## 8. Recommended sequence (inference)

1. **Before launch:** «Люди» S (already in REP). Decide where the single «Проекты» list lives. No new Органайзер items.
2. **January:**
   - meeting object with `.ics` and video link (CRM, 2 PR, CONN #10);
   - 360 service app, after the tariff answer (CONN Q9);
   - read-only kanban of deal projects (S–M);
   - connector-standard ADR plus the envelope domain contract change (S, documents and contract).
3. **February:**
   - WorkItem (ADR-0031 phase 3);
   - non-deal projects and stage tasks (L, in the CRM domain per W-9, or a WFM service = XL; ADR decision);
   - personal messages and object discussions (L).
4. **By real need:** Yandex Disk and Mail views through the service app (M each); personal notes (S–M); Jira or Notion adapters behind the port (M each per WS:62-64).

## 9. Questions only the owner can answer

1. Kanban inside a project: columns = stages, or columns = task status?
2. For deal projects, do you accept «stage closes by document status; tasks give progress»?
3. «Проекты» single list: Органайзер (PM) or Операции? If Органайзер, «Заявки» leaves «Операции».
4. Personal mail: a 360 view with «attach to object» (M), or our own client (XL)? Official letters still go through «Подписать».
5. Do you keep the ban on group channels and calls (10.11)? If not, connect Yandex Messenger or Telegram rather than build.
6. Six Органайзер items against the five-item rule: relax the rule, or fold notes and files into the project card and «Мои материалы»?
