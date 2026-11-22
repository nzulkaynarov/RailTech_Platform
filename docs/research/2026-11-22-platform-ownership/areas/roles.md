# AREA E: roles, module owners and the «situation centre»

All paths are relative to `` (main at 2ecd40446). Anything marked (inference) is my reading, not something the code or docs state.

**The short version:**
- The owner's six-owner model doesn't match the role catalog:
  - There is no HR role.
  - The "client manager" and the "sales manager" are one template role (`MANAGER`, and `MANAGER_ALL` on the pilot).
  - Every business module is used by 7 to 9 of the 9 roles.
  - The accountant has no module of its own.
- Главная today shows the user's own queue only. «Сводка» is a re-cut of that same queue plus three placeholder blocks, and it is visible to 2 roles.
- Company-level facts (funnel, loss reasons, SLA, overdue receivables, overdue letters, readiness) already exist in CRM, ERP and EDS endpoints. The BFF doesn't aggregate any of them.
- Five queue kinds are declared but nothing produces them (table in §2).

## 1. Roles and the role mechanism

### 1.1 Roles in `packages/contracts/platform-rbac.yaml`
- **System roles (fixed):**
  - `ADMIN` (L23-27): admin, company.settings, dashboard.queue, chats.internal, eds.memo.create, eds.signing.manage. All full.
  - `DIRECTOR` (L28-53): every business section. Several are read-only: crm.mail, crm.leads, eds.payments, chats.external, admin.
- **Templates (editable data, L57-173):** `MANAGER` L58, `SUPPLY` L76, `ENGINEER` L89, `ACCOUNTANT` L101, `REGISTRAR` L124, `MANAGER_ALL` L141, `LAWYER` L163.
- **Pilot:** 4 templates only: admin, director, registrar, all-round manager (SPEC-v3 §4.1 L377-386).
- **Labels don't match where sections are shown:**
  - `eds.projects` is labelled «Главная · Проекты» (L275).
  - `eds.payments` is labelled «Операции · Финансы» (L283).
  - `chats.external` is labelled «Контакты · Переписка с клиентами» (L354), but its screen is in Органайзер (§1.3).

### 1.2 Active role (how it works)
- **Switcher:** avatar menu shows "All roles" plus each role, only when the user has more than one role (`apps/platform/web/src/app/shell/AvatarMenu.tsx:55-80`). Choosing one sends `PATCH me {active_role}` (L140-142).
- **BFF:** `view_roles()` uses the active role if set, otherwise all roles (`apps/platform/bff/app/rbac.py:149-155`).
  - `build_me` builds `modules`, `resources` and `restricted_fields` from that view (`bff/app/schemas.py:131-150`).
  - Feeds take `?role=` or the active role (`bff/app/feeds/view.py:8-19`).
- **Restricted fields:** the BFF strips them by the union of all roles. The active role hides fields only in the SPA (`rbac.py` `strip_restricted` docstring, L158-170).
- **Forbidden page:** when an active role is set it says "not available to the active role" (`web/src/app/RequireAccess.tsx:14`, `shared/ui/Forbidden.tsx:24-38`).
- **Landing:** every role lands on `/dashboard/queue`, because all 9 roles have `dashboard.queue` (`web/src/app/access.ts:38-45`).

### 1.3 Two menu definitions
- **The catalog `menu`** (yaml L418-483) decides which modules appear in the rail (`bff/app/rbac.py:92-107`, `web/src/app/rbac.generated.ts:760`).
- **The web `NAVIGATION`** (`web/src/modules/navigation.ts:80-142`) decides the submenu. It places sections outside their code module:

| Item shown in | Real section (code module) | Evidence |
|---|---|---|
| Главная · Проекты | `eds.projects` (eds); `/dashboard/projects` redirects to `/eds/projects` | navigation.ts:83; dashboard/index.tsx:34-36 |
| Контакты · Почта | `eds.mail` (eds), access crm.leads.triage / crm.leads / crm.mail | navigation.ts:89; eds/module.ts:30-38 |
| Документы · Шаблоны | `admin.templates` (Settings, company.settings) | navigation.ts:97; yaml L475 |
| Операции · Финансы | `eds.payments` (eds) | navigation.ts:72-75, 118-125 |
| Органайзер · Календарь | `chats.calendar`, access dashboard.queue | chats/module.ts:222-228 |
| Настройки · Каналы связи (also) | `crm.channels` | navigation.ts:139 |

(inference) The catalog menu puts payments under `eds` (yaml L443) while the submenu puts Finance under `erp`. A custom role holding only `eds.payments` would therefore get Документы in the rail, and Операции · Финансы would not be reachable from the menu. No current template triggers this.

## 2. What each role lands on and sees on Главная

Queue kinds per role come from the catalog `queue` section (yaml L500-547). The cards come from `bff/app/feeds/queue.py:922-1014`, which shows at most 4 (`MAX_CARDS`, L86). A "dead" kind is one nothing in `bff/app/feeds/*` produces (checked by grep).

| Role | Queue kinds with a producer | Dead kinds | Cards on «Задачи» | «Сводка» |
|---|---|---|---|---|
| ADMIN | rework, ticket, instruction, acquaint, inbound_mail_mine, sign_document | integration_issue | **none** (tickets only as a menu badge, queue.py:1051) | — |
| DIRECTOR | resolve_letter, approve_quote, approve_memo, plus supply rows (send_supplier_order, partner_date_change, receive_goods, partner_application, supplier_overdue) | problem_project, create_request, service_request | Inbox without resolution, Quotes to approve, Memos, Projects in work | full |
| MANAGER | answer/take_lead, calc_task, rework… | create_request, service_request | Leads without answer, Leads without a manager, Projects in work | — |
| SUPPLY / ENGINEER | calc_task, all 6 supply kinds, supplier_overdue | — | Projects in work | — |
| ACCOUNTANT | confirm_payment, issue_invoice, issue_contract, attach_scan, issue_act, pay_memo | problem_project, overdue_invoice | Memos, Payments to confirm, Invoices to issue, Projects | read |
| REGISTRAR | triage_lead, inbound_mail… | (register_reply, deprecated) | Leads to triage, Inbound mail, Projects | — |
| MANAGER_ALL | lead work, calc, supply, payments, project kinds | create_request, service_request, problem_project, overdue_invoice | 6 candidates cut to 4; invoices_to_issue and projects_in_work are dropped (inference from dict order, L926-1014) | — |
| LAWYER | rework, instructions, sign | — | Projects in work | — |

**Problems found in this table:**
- **Promised rows never appear.** SPEC-v3 §4.1 (L399-404) promises "projects with problems" to the director, "overdue invoices" to the accountant and "integrations with errors" to the admin. All three are dead kinds.
- **Visas are missing from the queue.** Accountant and lawyer visas (`eds.visa.finance`, `eds.visa.legal`) have no queue kind at all. Plan Х-19 confirms this (plan-2026-11-12 L99, L235).
- **The director gets supply work rows.** The rule is "director gets decisions only" (`bff/app/feeds/work_roles.py:1-10`). But `EXECUTION_KINDS` (L17-28) excludes only order_shortage and ship_project. The other supply kinds and supplier_overdue pass through `view.wants` (`queue.py:855-866`, `snapshot.py:174-190`).
- **The "Сегодня" feed is narrow.** Only the platform admin gets the company-wide log. Everyone else gets the timelines of 5 deals (`feeds/activity.py:1-6`, `TIMELINE_DEALS=5`).
- **What «Сводка» actually shows** (`web/src/modules/dashboard/SummaryPage.tsx`):
  - It calls the same `/queue` and `/queue/cards` as «Задачи» (L34-35; compare QueuePage.tsx:65-66).
  - The chart is my tasks by due date (L41). "Просрочено" is my overdue tasks, capped at 5 (L18, L43).
  - Three blocks ("Заявки по шагам", "Прибыль по проектам", "Цели на 12 месяцев") show "Данные появятся здесь" (L17, L102-110; `shared/i18n/ru/modules.json:129-142`).
- **SPEC-v3 §7.1 (L614) wants something else:** funnel from message to payment, stuck projects (days on stage over the norm), receivables, loss reasons. None of these is present. ГЛ-3 (plan L147) is scheduled after ГЛ-1/ГЛ-2 and is for the director only.
- **The summary endpoint doesn't exist.** The BFF dashboard API has only menu-counters, queue, queue/cards and activity/today (`bff/app/api/dashboard.py:39-115`). There is no `GET /summary` in `packages/contracts/openapi/platform-bff.yaml` or in the BFF. Yet `docs/architecture/integration-map.md:41` marks `GET /summary` as ✓ (doc drift).
- **Unused backend rights.** `dashboard.summary` grants CRM `dashboard:read`, `spend:read` and ERP `data.export` (yaml L199-201). The BFF never calls CRM `/dashboard`.

## 3. Endpoints that already expose company-level facts

| Fact | Endpoint | Used by BFF? |
|---|---|---|
| Lead funnel, SLA (due/met/share), per-manager stats, escalation reasons, open escalations | CRM `GET /api/v1/dashboard?days=` (`apps/crm/backend/app/api/v1/admin.py:22`; schema `schemas/admin.py:31-77`) | no |
| Won (sums by currency), lost by reason, open count, daily | CRM `GET /api/v1/deals/summary` (`api/v1/deals.py:104`; `schemas/deals.py:84-95`) | no |
| Deal volume, active requests, clients, deals by month, request completion | ERP `GET /api/v1/crm/analytics/dashboard/` (`apps/erp/backend/core/urls.py:406`; `crm/views/analytics.py:27`; `crm/services/dashboard_analytics.py:100-315`) | no |
| Time to first quote (median / p90) | ERP `/api/v1/crm/analytics/time-to-first-quote/` (urls:407; analytics.py:57) | no |
| Deals active/won/lost, pipeline value, by stage, attention counters | ERP `/api/v1/analytics/platform-dashboard/` (urls:460; `core/views/stats.py:214`). Platform-admin only | no |
| Receivables, overdue tab with counts, bank details ready | ERP `/api/v1/finance/receivables/?tab=to_issue,awaiting,proofs,overdue,all` (`finance/views_receivables.py:93-135`; TABS in `finance/services/receivables.py:32`) | only proofs and to_issue (`snapshot.py:389-405`) |
| Late supplier orders | ERP `/api/v1/stock/overdue/` (urls:396) | yes (queue) |
| Projects and stages | ERP `/api/v1/crm/projects/`, `/crm/deals/` (urls:267, 222) | yes (`projects_in_work`, queue.py:913) |
| Days on stage | `Deal` has no stage-entered timestamp (`apps/erp/backend/sales/models/deals.py:17-150`). Changes are logged as `deal.stage_changed` and `deal.lost` (`crm/services/deals.py:153-168, 259`) | no (would need to be derived) |
| Overdue or on-control incoming letters | EDS `GET /letters?on_control=&overdue=` (`apps/eds/app/api/v1/letters.py:113-132`); `/registry` (`registry.py:54`) | no (only awaiting_resolution) |
| Readiness and accident risk | BFF integrations overview with `attention[]` (`api/admin_integrations.py:115-170`; `schemas_integrations.py:629-632`); `/setup/checklist` (`api/setup.py:139`); bus journal (`api/admin_bus.py:70`); EDS `/signing/setup-hint` (`signing.py:181`) | admin screens only, nothing on Главная |

**What a per-role situation centre needs that ГЛ-1/ГЛ-2 don't give.** ГЛ-1 and ГЛ-2 cover my own tasks, "you are waiting on others" and signals (plan L145-146; DECISIONS 2026-11-22 L365). A situation centre would also need (inference):
- Area or company state:
  - funnel and loss reasons (CRM sources above);
  - stuck requests and projects by stage with their age (needs a days-on-stage field);
  - overdue receivables with sums;
  - late supplier orders;
  - incoming letters on control or overdue;
  - quotes waiting for the client or expiring.
- Readiness: nobody can sign, mail or bot not set up, company requisites empty. Scenario walk sc.12 (`docs/audits/2026-11-19-scenario-walk.md:42`) says there is no readiness page; sc.3 L95-96 shows an invoice blocked by requisites only the admin can set.
- SLA breaches: lead take SLA (CRM `SlaStat`) and resolution deadlines.
- Team load (CRM `ManagerStat`).
- Per-role scoping with restricted fields: margin and receivables are restricted (yaml L488-497; SPEC §4.2 L413). Today «Сводка» is visible to only 2 of 9 roles (yaml L32, L105; SPEC §6.3 L556), which conflicts with "situation centre for everyone".

## 4. The six owner proposals against the facts

Who uses each module comes from the catalog `access` blocks.

| Module (owner proposed) | Matching role | Who actually uses it | Where the owner idea breaks |
|---|---|---|---|
| **Настройки** (admin) | `ADMIN` system role (`admin: full`, L26) | ADMIN full; DIRECTOR `company.settings: full` + `admin: read` (L49-50) | Requisites, numbering, taxes and templates are company settings owned by director and admin together (L405-413). Templates are shown in Документы (navigation.ts:97). The knowledge base is edited by admin (`kb:write`, L391-392) but lives in Контакты (`crm/module.ts:150-156`). The only "accident" queue kind, `integration_issue`, has no producer. Admin has no cards on Главная. |
| **Главная** (everyone) | all roles | queue: 9 of 9; Проекты (`eds.projects`): full for DIRECTOR, ACCOUNTANT, MANAGER_ALL, read for the other 5 templates, none for ADMIN; Сводка: 2 roles | Главная · Проекты is a work register where contract, scan and act are done (label L275; queue kinds issue_contract, attach_scan, issue_act L524-527), not a view. It is also where the screenshot (c) "projects under Главная" comes from. NAVIGATION L42 puts the request in Операции before the quote is accepted and in Главная after, for the same object. |
| **Контакты** (client manager, leads only) | `MANAGER` / `MANAGER_ALL` (`crm.leads: full`) | Leads: MANAGER, MANAGER_ALL full; REGISTRAR read + triage (first line, owner decision 2026-11-01, SPEC L388-393); DIRECTOR read. Контрагенты: DIRECTOR, MANAGER, MANAGER_ALL full; ENGINEER, ACCOUNTANT, REGISTRAR, LAWYER read; SUPPLY sees partners through `erp.stock` (L427). Почта: REGISTRAR works it, managers see their own, DIRECTOR reads all (L217-232). 8 of 9 roles. | "Leads only" leaves Контрагенты (clients and partners, ERP master data per MODULES.md decision 2) without a home. The registrar is the leads first line but proposed as Документы owner. On mail removal: MODULES.md L19 says CRM owns the company mailbox and NAVIGATION L31 calls Почта "all company email". Mail is the intake for both leads and registered incoming letters (`crm.leads.triage` backend L222 plus `letters.register`). |
| **Документы** (registrar) | `REGISTRAR` (`eds.inbox.register`, L132) | `eds.memo.create`: 9 of 9; resolution `eds.inbox: full`: DIRECTOR only; quote approval `eds.drafts`: DIRECTOR (L267-272); visas: ACCOUNTANT, MANAGER_ALL, LAWYER | The registrar only reads incoming and registers. He has no `eds.drafts`. He cannot sign: DECISIONS 2026-11-22 (ЕД-6 p.2) says the registrar only does paper dispatch. NAVIGATION says registrar sees "everything" in Документы (L107), but the catalog doesn't grant it; the exact matrix is deferred (L115). Исходящие holds quotes approved by the director (L267; navigation.ts:94). Removing "internal correspondence" could mean three different things: (a) «Внутренние» memos, statements and reports, decided 2026-11-10 (Q-NAV-1, NAVIGATION L36), which carry the payment route (SPEC §3.2 p.5); (b) "внутреннее письмо" (SPEC §3.2 L178); (c) chat or discussion tabs on document cards (`eds/module.ts:27,71,79,86`). |
| **Операции** (sales manager) | `MANAGER` (`erp.calc: full`, L66) | `erp.calc` full: DIRECTOR, MANAGER, SUPPLY, ENGINEER, MANAGER_ALL; read: ACCOUNTANT. `erp.stock` full: DIRECTOR, SUPPLY, ENGINEER, MANAGER_ALL; read: MANAGER, ACCOUNTANT. Финансы (`eds.payments`) full: ACCOUNTANT, MANAGER_ALL; read: DIRECTOR, MANAGER. 7 of 9 roles. | Costing visas belong to supply and engineer (L332-343). Warehouse and purchasing kinds go to SUPPLY, ENGINEER and DIRECTOR (L514-521). Payment confirmation belongs to the accountant (SPEC §3.1 step 8). The sales manager doesn't see cost or margin (SPEC L429). MODULES.md L56 lists ERP's users as managers, costing staff, supply and accountant. |
| **Органайзер** (HR manager) | **no HR role** in the catalog, SPEC §4 or MODULES.md (grep) | Calendar: `dashboard.queue` (all roles). Chats and People: `chats.internal` (all 9). External chats: MANAGER, ACCOUNTANT, MANAGER_ALL full; DIRECTOR, REGISTRAR read. | People: roles and rights stay in Настройки · Сотрудники and admin edits all cards (NAVIGATION L54). Tasks and meetings: there are no tasks without an incoming document (NAVIGATION L76; MODULES.md L81-90, "WFM — a section, not a system"). Project tracking lives in Главная · Проекты. The docs disagree with each other on client chat: NAVIGATION L18/L49 says chats are internal only and client correspondence is in cards; MODULES.md L104 and L163 say chats should carry client and partner talks. The owner's draft sides with MODULES.md. Connectors: NAVIGATION L69 puts them in Настройки · Подключения. |

**Roles the owner model doesn't cover:**
- **Accountant has no module of their own.** The work is spread over Главная · Проекты (contract, scan, act), Операции · Финансы (invoice, payment, memo payment), Документы (visa, which has no queue row), Контакты (read) and external chats.
- **Lawyer:** visa only, through Задачи.
- **Director:** spans every module.
- **Client manager vs sales manager:** a single role. The pilot doesn't separate them (SPEC L377-386).

## 5. Every place one role jumps across modules for one scenario
Sources: scenario walk (`docs/audits/2026-11-19-scenario-walk.md`), SPEC §3.1 (L162-174), NAVIGATION "Процесс → экран" (L121-146).

| Scenario | Role: path | Evidence |
|---|---|---|
| sc.1 Lead → quote | Manager: Контакты · Лиды → Создать заявку → Главная · Задачи (empty, can't see the request waits for resolution) → Контакты · Контрагенты (request steps) | walk L48-55 |
| sc.1 | Director: Главная → Документы · Входящие (resolution) → Главная → Документы · Исходящие (quote approval) | walk L56-58, 69-72; SPEC §3.1 steps 3, 5 |
| sc.1 | Executor: Главная → Операции · Заявки (costing) | walk L61-68 |
| sc.2 Contract | Manager: Контакты · Контрагенты (resend invite) → Главная · Задачи → Главная · Проекты (contract) | walk L78, 85-89 |
| sc.3 Invoice and payment | Manager: Главная → Операции · Финансы, blocked by missing requisites; Admin: Настройки · Компания · Реквизиты; Manager back to Финансы | walk L95-97 |
| sc.3 | Accountant: Главная → Операции · Финансы | walk L100-101 |
| sc.4 Supply → act | Supply: Главная (deficit is not a task) → bell → Контакты · Контрагенты (add partner) → Операции · Заявки · Закупки (order) → Операции · Каталог · Склад (receive, ship); act → Главная · Проекты | walk L107-121; NAVIGATION L131 |
| sc.5 Outgoing letter | Author: Создать → Документы · Исходящие; Registrar and Director: Главная → Документы card; Admin: Настройки · Права подписи (required before anyone can sign) → Director: Главная again | walk L127-136 |
| sc.6 Incoming → reply | Registrar: Документы · Входящие · Зарегистрировать; Director: Главная → Документы · Входящие; Executor: Главная → `/eds/tasks` (hidden Документы section) → reply in Документы · Исходящие; signer: Главная | walk L142-160; eds/module.ts:99-109 |
| sc.7 Memo → payment | Author: Создать → Документы · Внутренние; Director: Главная → Документы · На согласовании; Accountant: Главная → Операции · Финансы · Заявки на оплату; the author is never notified | walk L166-173; navigation.ts:73-75 |
| sc.8 Client request from Кабинет | Goes to the Director's Главная → Документы · Входящие (not to the manager) → Supply: Операции · Заявки | walk L182-184 |
| sc.9 Partner | Supply: Операции · Закупки → Контакты · Контрагенты (invite, contact rights) → Операции · Закупки | walk L194-204 |
| sc.10 Catalog | Supply: Операции · Заявки (costing) → Операции · Каталог · Товары (draft, publish) | walk L210-214 |
| sc.11 Employee | Admin: Настройки · Сотрудники; Director: avatar → Профиль · Замещение; the deputy's Главная doesn't show the director's tasks | walk L221-229 |
| sc.12 First setup | Admin: Настройки (wizard) → Подключения → Почта → delivery log → Telegram → Права подписи (not in the wizard) → Компания · Реквизиты | walk L33-42, 135 |
| SPEC П1.7-П1.10 | Accountant: Главная · Проекты (contract, act) ↔ Операции · Финансы (invoice, payment) ↔ Задачи (visa) | NAVIGATION L129-132; SPEC §3.1 steps 7-9 |
| SPEC П2.6, П8 | Supply, Director, Accountant: Создать → Документы · Внутренние → Задачи → Операции · Финансы | NAVIGATION L139, L146 |
| SPEC П3 | Supply, Lawyer, Director: Контакты · Контрагенты → Задачи → partner card | NAVIGATION L140 |
