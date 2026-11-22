# AREA R: roles as zones of responsibility, not hard-coded

Checkout: ``, main at a87c49a92. All paths below are relative to it. I read code and docs only; nothing was run. "(inference)" marks my own reading. Facts already in `docs/research/2026-11-22-platform-ownership/areas/roles.md` (active role, queue kinds per role, «Сводка», endpoints with company facts) are referenced, not repeated.

## 0. Short answer

- **The owner's principle is already his own accepted rule.** ADR-0012 (`docs/adr/0012-configurable-platform-roles.md:3`, "требование владельца 2026-10-22", accepted) says roles are data, and p. 6 (L56-61) says "процесс опирается на возможности, а не на названия ролей".
  - The mechanism exists: an admin can create any role from any set of sections, and a person can hold several roles.
  - So the addition does not change the architecture. It exposes three gaps:
    1. **Sections are too coarse to describe some zones.** HR cannot manage people without also getting IT administration. A lawyer cannot edit templates without also getting requisites and taxes. There is no "project control" section at all.
    2. **About 15 places are tied to a role name or a fixed list of roles.** The heaviest are the system DIRECTOR, the «Директор» step label and the fixed lists of six or seven "kinds" of worker.
    3. **"Who is accountable for a zone" is stored nowhere as data.** Only "who may" (permissions) and "who signs" (signing register) exist.
- **The report's verdict «должность не делит меню» stands, made more precise** (§4). The owner himself says one person often holds several roles and the system must not be hard-coded. A menu split by role is exactly that kind of hard-coding.
  - The verdict should be completed: **a role decides what you see; a zone of responsibility decides what you are accountable for and what is signalled to you.**
- **Name collision to fix before any screen.** In the system, «заместитель» means a temporary substitute during absence (W15-H6; DECISIONS 2026-11-21 (2), `docs/DECISIONS.md:359`). The owner's «заместители директора» are permanent heads of a zone. They are different objects (§1.4).
- **Launch date.** The zones register and zone routing fit ADR-0031 phase 2 ("время, назначение, замещение, поле «руководитель»", January; plan `docs/runbooks/plan-2026-11-12.md:267`). DECISIONS 2026-11-21 (3) (`DECISIONS.md:360`) put the whole processes programme after launch. Before launch only the cheap de-hard-coding fits (§6).

## 1. The role model today

| Element | Fact | Evidence |
|---|---|---|
| **System roles** | `ADMIN` and `DIRECTOR`. Fixed and cannot be deleted (409 `role_system`). The company must always have at least one active admin and one active director (409 `last_admin` / `last_director`) | `packages/contracts/platform-rbac.yaml:23-53`; `apps/crm/backend/app/api/v1/platform_roles.py:1-7`; `apps/crm/backend/app/services/user_platform.py:36-37,124-136` |
| **Templates** | `MANAGER`, `SUPPLY`, `ENGINEER`, `ACCOUNTANT`, `REGISTRAR`, `MANAGER_ALL`, `LAWYER`. Created at first start as ordinary editable roles (`tpl:<код>`) | `platform-rbac.yaml:57-173`; `apps/crm/backend/app/domain/platform_roles.py:113-125,140-156` |
| **Custom roles** | Yes. Admin (`users:write`) creates a role with name, description, any section at `full` or `read`, and restricted fields. A "what will happen" preview shows who gains or loses what. Optimistic version lock. Director reads the matrix only | `apps/crm/backend/app/api/v1/platform_roles.py:73-120`; `domain/platform_roles.py:159-176` (only checks that the section and level exist); model `apps/crm/backend/app/models/platform_roles.py:26-50` (`code` is empty for custom roles); UI `apps/platform/web/src/modules/admin/roles/RolesPage.tsx`, `RoleEditor.tsx`, `RoleMatrix.tsx`, `RoleJournal.tsx` |
| **Multi-role and active-role switch** | `user_platform_roles` is many-to-many. Rights are the union of roles (highest level per section). The active-role switch narrows the menu and queue (details in roles.md §1.2) | `models/platform_roles.py:53-66`; `domain/platform_roles.py:182-197,337-352`; `apps/platform/bff/app/rbac.py:149-155` |
| **Granularity** | A section has no scope by zone, amount, client or project. A holder of `eds.memo.approve` approves **every** memo; a holder of `approvals.decide` approves every quote | `platform-rbac.yaml:301-305,265-272`; `apps/eds/app/services/approvals.py:47-56` |
| **Coarse sections (zone ≠ section)** | `admin` = employees + roles + integrations + backups + AI models + bot + KB + log + tickets in one section. `company.settings` = requisites + numbering + taxes + sales terms + document templates. `eds.projects` = "договор, счёт, акт, сканы" (paperwork, not project control) | `platform-rbac.yaml:363-406`, `407-415` (menu `:466-475`), `273-280` |
| **Positions vs roles** | Position is free text up to 120 characters, with no effect on rights. ERP's nine "должностей" were turned into this text field | `domain/platform_roles.py:132-137`; `docs/product/SPEC-v3.md` §4.3 (L436-439); CRM `models/auth.py:92` |
| **Org structure** | None: no departments and no "руководитель" field. «Оргструктура» in the menu is the employee list (`org: [admin]`). The «руководитель» field is planned for phase 2 (January) | `platform-rbac.yaml:461`; employee card fields `apps/platform/web/src/modules/admin/org/EmployeeCard.tsx:44-52`; ADR-0031 p. 10 (`docs/adr/0031-processes-as-data.md`); DECISIONS 2026-11-21 (7) `:360` |

### 1.4 Deputy (замещение) — what transfers and what does not

| Aspect | Fact | Evidence |
|---|---|---|
| Storage | One deputy per employee with a period: `users.deputy_user_id/from/to`. Projected to EDS | `apps/crm/backend/app/models/auth.py:128-132`; `apps/eds/app/services/employees.py:28-30` |
| Who sets it | **Only the employee, in Профиль** (`PUT /me/deputy`). An admin or HR cannot set a deputy for someone who is suddenly absent (inference: there is no admin endpoint; `deputy` does not appear in CRM users services) | `apps/crm/backend/app/api/v1/me.py:159-168`; `apps/platform/web/src/features/profile/DeputySection.tsx` |
| Who can be a deputy | Any active employee (ЕД-6 (3)) | `apps/crm/backend/app/services/staff_deputy.py:54-64`; DECISIONS `:362` |
| What transfers | Steps of the replaced person: memos (including those with an amount), quote approval, instructions and deadline extensions; his leads and queue, marked «за <имя>» | `apps/eds/app/services/access.py:19-24,77-139`; BFF `feeds/queue.py:262-300`; DECISIONS 2026-11-21 (2) `:359` |
| What does not transfer | Signature (ADR-0024 p. 2; decision 2026-11-05) and payment confirmation. Rights to objects stay the deputy's own | `access.py:22-24`; `docs/adr/0024-signing-authority-and-official-documents.md:48`; `staff_deputy.py:1-7` |
| **Gap** | Substitution is per person and only for an absence period. There is no "deputy for a zone" and no deputy for a zone owner (inference) | — |

## 2. Behaviour tied to a role name or a fixed role set

| # | Where | What is hard-coded | What breaks when the duty is delegated |
|---|---|---|---|
| 1 | `apps/platform/bff/app/feeds/work_roles.py:17-37` (`_DECIDER_ONLY = "DIRECTOR"`) | "Director gets decisions only": execution rows (`calc_task`, `confirm_payment`, `issue_*`, `attach_scan`, …) are removed only for the **system** DIRECTOR | (a) A deputy director for a zone, created as a custom role with `eds.drafts` / `eds.memo.approve` and `erp.calc` / `eds.projects`, gets every execution row; the "decider" behaviour does not apply to him. (b) A role with the same rights built from a template gets a different queue than the system director. The behaviour belongs to the code, not to the zone. CONVENTIONS allows this (`docs/systems/platform/CONVENTIONS.md:45-47`, "кроме системных ADMIN/DIRECTOR") |
| 2 | `apps/eds/app/services/approvals.py:28-29,47-56` | Memo and quote route steps are labelled «Директор» and «Бухгалтер». The step is assigned to a permission (`approvals.decide`, `memos.approve`, `payments.confirm`) or to an addressee | When a sales deputy approves quotes, the route still says «Директор». All holders of the right share one queue, with no zone, amount or department scope. The composition is code (ADR-0031 phase 1, January) |
| 3 | `apps/eds/app/services/commercial_signing.py:36-44` | Visas before signature: contract → accountant + lawyer; invoice and act → accountant. The role appears as a word in the refusal reason | A company without a lawyer cannot sign a contract: the route does not start without a holder of `approvals.visa_legal` (owner rule 13, `platform-rbac.yaml:312-313`; `_missing_visa_role` L48-59). The visa set cannot change without code (ADR-0031 phase 1) |
| 4 | `apps/eds/app/services/people.py:48-56` (`default_director`) | Default addressee of incoming mail = the active holder of `letters.resolve` **with the smallest id** | When a deputy gets the right to resolve, the default addressee is decided by who was created first. Nobody chose it (inference). Listed in the processes inventory (`docs/research/2026-11-21-processes-as-data/README.md` §2) |
| 5 | Web: `shared/i18n/ru/letters.json:369` («Директор (по умолчанию)»); `approvals.json:109` + `modules/eds/approvals/MemoView.tsx:181`, `eds/documents/DocumentCard.tsx:152` («Директор» when there is no addressee); about 71 mentions of «директор» in `shared/i18n/ru/*.json` (for example `calc.json:38-82,238-278`, `letters.json:3,113,188,214,322,477-479,580,673-674`, `help.json:121-209`, `request.json:81`) | Texts name the person who decides | When duties are delegated, the interface shows the wrong person. Statuses also carry the word: `at_director`, `rejected_director` |
| 6 | Contract and models: BFF `schemas_erp_calc.py:23,29` (`at_director`, `RejectedBy = "director"`); ERP `sales/models/quotes.py:309-323` (`director_decision/comment/decided_at`); `crm/services/eds_quote_approval.py:153-312` | "Director's decision on a quote" is a field and an event code (`quote.director_approved`) | Data and the journal say «директор» whoever actually decided. Renaming is a contract change (inference: worth doing together with ADR-0031 phase 1, when quote visas move into the EDS route) |
| 7 | `apps/platform/web/src/features/help/startKinds.ts:7-24` | Fixed list of six "kinds" for «С чего начать» and onboarding (admin, director, manager, supply, engineer, accountant). Derived from permissions, but the list is closed | Registrar (`crm.leads.triage`, `eds.inbox.register`), lawyer (`eds.visa.legal`), signatory, HR, CRM specialist and project manager all get "default". Used in onboarding at `features/onboarding/Onboarding.tsx:221-222` |
| 8 | `apps/platform/web/src/modules/dashboard/queue.ts:44-64` (`queueEmptyKind`) | Same closed list (seven kinds) for the empty Главная. Anyone with `eds.inbox` / `eds.drafts` / `eds.memo.approve` full counts as "director" | A deputy with memo approval sees the director's texts; registrar and lawyer see neutral ones |
| 9 | `shared/i18n/ru/help.json:47-100` | Role guides written by role name (director … admin) | Same six kinds; texts like «КП уйдёт директору» |
| 10 | `platform-rbac.yaml:512` `problem_project: eds.projects full` (no producer yet) | "Problem projects" go to whoever holds `eds.projects` full: director, accountant, all-round manager | There is no "project control" right, so the signal goes to the accountant instead of the project manager (inference). When created, it should go to the person accountable for the project or zone |
| 11 | CRM `domain/staff_notify.py:28-58`, `services/external_services/alerts.py:118-125`, `services/leads.py:308`, `services/team.py:85-91` | Recipients by CRM base role (`admin` / `manager`), which is derived from the matrix (`admin: full`, `crm.leads: full`; `platform-rbac.yaml:180-190`) | Not a role name, but a fixed set of "everyone with X". Integration failures go to every holder of `admin: full`; a new lead goes to every manager. Handover is possible only to a holder of `crm.leads: full`. Nobody is "the accountable one" (ADR-0031 phase 3, about 30 notifications) |
| 12 | ERP `crm/services/deal_notifications.py:28-45`, `notifications/signals.py` | Recipients = "all `can_sell` employees" | Same: no zone or accountable person |
| 13 | CRM texts: `services/erp_events.py:257` («ждёт резолюции директора»), `services/mail_types.py:57-59` («→ директору») | Role name in a notification or button | As #5 |
| 14 | SPEC-v3 §9 notification matrix (`docs/product/SPEC-v3.md:768-789`); SPEC §4.1 (`:373-404`) | Recipients by role name (director, accountant, manager, supply) | The document invites code keyed to roles. It should say "zone or section" |
| 15 | Plan: ГЛ-3 «Сводка… для директора» (`plan-2026-11-12.md:148`); ДВ-4б «второй фактор обязателен директору, бухгалтеру и администратору» (`:178`); DECISIONS 2026-11-22 (6) (`:365`) | Not yet code; worded by role name | (inference) If built literally, they become hard-codes. Key them on sections instead: `dashboard.summary`; `admin` / `eds.payments` / `eds.inbox` full / holders of signing authority |

Not hard-coded (checked):
- Resolution executors by zone: `eds/services/people.py:81-91` reads catalog sections.
- Visibility of «Сводка»: the `dashboard.summary` section.
- Queue kinds: the catalog `queue` block (`platform-rbac.yaml:500-560`).
- ERP provisioning: permissions only (`integration/services/provision.py:49-111`).
- The only remaining ERP role-code special case is the ERP superuser for system `ADMIN` (`domain/platform_roles.py:355-363`).

## 3. The owner's roles 1–9 against what exists

| # | Role | Role / template today | Sections that express the zone | Tools and screens: exist / missing | What "accountable" needs as a visible fact |
|---|---|---|---|---|---|
| 1 | Director | System `DIRECTOR` (`platform-rbac.yaml:28-53`) | All business sections; `dashboard.summary`; resolution, quote approval, memos | Queue of decisions: exists. «Сводка» is a re-cut of the personal queue with three placeholders (roles.md §2). ГЛ-3 comes after ГЛ-1/2 | Company state: funnel, stuck projects, receivables, loss reasons, readiness. The data exists in CRM, ERP and EDS; there is no aggregate (roles.md §3). Plus "who owns which zone, and are any zones unowned" — nowhere |
| 2 | Deputy directors (zone heads) | **None.** Possible only as a custom role | Any sections, but without scope: a holder of `eds.memo.approve` approves everything | Collides with «Замещение» (§1.4). Breaks on #1, #2, #4, #8 | The zone's signals routed to its head, steps "only if zone or amount" (ADR-0031 phase 1 conditions), escalation to the head (the «руководитель» field, phase 2). Nothing exists |
| 3 | Accountant | `ACCOUNTANT` (`:101-122`); on the pilot `MANAGER_ALL` | `eds.payments`, `eds.visa.finance`, `eds.projects` full, `dashboard.summary` read | Payments, invoices, contract, act and scans: exist, spread over 4 modules (roles.md §4). **Visa is not in the queue** (no queue kind; Х-19, `plan:236`). `overdue_invoice` has no producer (`yaml:529`) | Receivables and overdue amounts (ERP `finance/views_receivables.py:93-135`, BFF uses only part of it, roles.md §3); "invoices waiting for my visa". Signals, not a module |
| 4 | Lawyer | `LAWYER` (`:163-172`), not in the pilot four (`SPEC-v3.md:377-386`) | `eds.visa.legal` only (contract) | **Veto exists for contracts:** a visa refusal stops the route (`commercial_signing.py:275-286`, owner rule 7), and the route does not start without a lawyer (#3). The visa is not in the queue (Х-19). No access to templates: `company.settings` bundles them with requisites and taxes (`yaml:407-415,466-475`; report §6.2). No veto on memos, risky projects or quotes: the memo route is director + accountant (`approvals.py:47-56`). "Memo over 10 million → add the lawyer" is the acceptance case for ADR-0031 (`processes README` §12), January | Mandatory legal visa by document kind or amount, as data; register of open legal visas and refusals; signing authorities with expiry (the register exists, `eds.signing.manage` can be granted to a lawyer, `yaml:306-313`) |
| 5 | Project manager | **None** | **No section.** `eds.projects` is paperwork. ERP `Deal` has `manager` (sales manager) and `assigned_to` ("who took the request"), but no project-manager field (`apps/erp/backend/sales/models/deals.py:51-75`) | No stage owner, no stage deadlines or norms, no days-on-stage (roles.md §3, `deals.py:17-150`). Stage transitions are code (`crm/services/deals.py:44-59`) | Stages with norms, overdue stages, one definition of "project done", problem projects routed to the PM. See §5.1 on the owner's "100 %" rule |
| 6 | HR | **None** (report §3.6) | Managing people requires `admin: full`, which also gives integrations, backups, AI models and bot (`yaml:363-406`). ERP superuser stays only with system ADMIN | Exist: invite, disable with handover of CRM leads and clients (`apps/crm/backend/app/services/user_handover.py:16-30`; ERP deals and EDS tasks not checked), positions. Missing: separate "people" section, setting a deputy for someone else, absence types, org chart, «руководитель» (organizer.md §1.11) | Who holds which zone (and which zones are unowned), absences and coverage, load per person (only CRM `ManagerStat`, `apps/crm/backend/app/schemas/admin.py:44-52`), onboarding / offboarding checklist |
| 7 | Sales manager | `MANAGER` / `MANAGER_ALL` (`:58-75,141-162`) | `crm.leads`, `crm.clients`, `erp.calc` | Leads, requests, quotes: exist. Client owner `clients.owner_user_id` (`apps/crm/backend/app/models/clients.py:53`); "his manager" for a Кабинет request = client owner (DECISIONS 2026-11-21 (4), `:359`) | "My clients' open obligations": quotes waiting for the client, invoices, deliveries overdue. Not aggregated; the manager does not see that a request waits for resolution (report §4.5) |
| 8 | CRM specialist (first contact) | Closest: `REGISTRAR` with `crm.leads.triage` (`yaml:213-223`) | `crm.leads.triage`: triage and hand over to a manager with a note; handover only to holders of `crm.leads: full` (`services/leads.py:308`) | Triage queue and «Входящая почта»: exist. The SLA measured is the **manager's take time** (`SlaStat`, `schemas/admin.py:55-60`; `settings.py:238,536`). No triage SLA metric (inference) | Time from first contact to assignment, unassigned leads, share handed over within SLA. The data is partly in CRM `/dashboard` (not read by the BFF) |
| 9 | Registrar | `REGISTRAR` (`:124-140`) | `eds.inbox.register` (incoming and outgoing registration); paper dispatch only (DECISIONS 2026-11-22 ЕД-6 (2), `:362`) | Registration: exists. No queue kind for "send the signed letter" (`bff/app/feeds/models.py:41-76`). Letters on control or overdue: EDS has the filter (`apps/eds/app/api/v1/letters.py:113-132`), but they are not collected on Главная | Registered today, overdue on control, signed but not sent |

Summary:
- **Have both a template and sections:** director, accountant, lawyer, registrar, sales manager, and roughly the CRM specialist (via the triage section).
- **No template, no sections:** deputy for a zone and project manager.
- **No section:** HR (the needed rights are buried inside `admin`).

## 4. "Workplace of a role" without splitting the menu

- **Building blocks that exist:**
  - catalog sections and the menu (`yaml:418-483`);
  - queue kinds keyed on sections (`yaml:500-560`);
  - Главная cards (at most 4, `bff/app/feeds/queue.py:86`);
  - active-role switch (roles.md §1.2);
  - "kinds" for help and the empty state (#7, #8).
- **Saved views:** none. A search for saved views or table preferences found nothing (inference: the table column menu exists, saved filters do not).
- **What the report proposed:** Главная = my work + signals of my zone by role + a readiness line (report §3.2, §4.4).
  - Its signal table covers only 4 pilot roles: admin, director, registrar, manager.
  - "Responsible for order" in a module is a person, not a visibility rule (§4.2).
- **What the owner's addition changes. The verdict holds and is refined:**
  1. "Signals of my zone" must be keyed on **zone or section, not role name.** Otherwise #7 and #8 repeat for every new role.
  2. Two levels are needed. **Role** = what I may do; it shapes the menu and permissions. **Zone** = what I answer for; it decides which signals, escalations and "no owner" warnings reach me. Today only the first level exists.
  3. A person with several roles gets the union of signals. A zone with no owner is itself a signal to the director (the "readiness" pattern, like `_missing_visa_role`).
  4. The fixed "kinds" (#7, #8, #9) are replaced by: zone → help article and empty-state text (inference).
- **Why not split the menu by role:**
  - The owner's own sentence: "the same people perform several roles … must not be hard-coded".
  - The pilot has 4 templates; every working module is used by 7–9 roles (report §1 p. 5).

## 5. Responsibility as data

| Where | What is stored | Is it "accountable for a zone"? |
|---|---|---|
| EDS signing register `signing_authorities` | Employee, document kinds, amount limit, basis (charter, order, power of attorney with number and date), valid from–to, revocation, journal, expiry reminder | **The closest model.** Per person, per kind, with a limit and a legal basis (`apps/eds/app/models/signing.py:67-88,91-105`; ADR-0024) |
| Responsible person on objects | Lead `assigned_user_id`, client and deal `owner_user_id` (CRM), deal `manager` / `assigned_to` (ERP), partner `responsible` (ERP), project document `responsible_crm_user_id`, letter `manager_crm_user_id` (EDS) | Per object, not per zone (`apps/crm/backend/app/models/leads.py:50`, `clients.py:53`, `deals.py:64`; `apps/erp/backend/sales/models/deals.py:51-70`; `apps/erp/backend/parties/models/relationships.py:97`; `apps/eds/app/models/project_documents.py:44`; `letters.py:101`) |
| Resolution templates | Responsible person per template (person, addressee, none) | Per template (`apps/eds/app/models/resolution_templates.py:29-49`) |
| External services «кто исправляет» | Class `admin` / `owner` / `hosting` / `provider`, worked out in code from the cause | A class, not a person (`apps/crm/backend/app/schemas/external_services.py:12,80`) |
| Module "owners", zone heads, «руководитель» | **None.** «Руководитель» is phase 2 (DECISIONS `:360` (7)); module owners are an open question (report Q8) | — |

**Minimal "zones of responsibility" register (inference; modelled on the signing register):**

1. **Zone.** A key from a closed catalog in code, like sections: finances, legal, sales, first contact, docflow, supply, projects, people, settings and IT. Each zone maps to the sections, queue kinds and signals it covers. New zones only through a PR (ADR-0031 p. 2 "блоки — код").
2. **Accountable person** (`crm_user_id`), an optional backup, and an optional scope: amount, client segment, project. Several zones per person; one accountable per zone and scope.
3. **Basis and period.** Order number and date, valid from–to, revocation, append-only journal. The same as the signing register; the owner's "accountable person" needs a legal trace.
4. **Checks:**
   - the holder has the zone's sections (ADR-0031 p. 7 "живой исполнитель");
   - a zone without an owner is a readiness signal to the director;
   - leaving or being disabled forces a handover, as with `user_handover`.
5. **Consumers:**
   - Главная signals and escalations;
   - default addressee (replaces #4);
   - route step "head of the zone" (replaces the «Директор» label, #2);
   - notification recipients (#11, #12).
6. **Home.** CRM, the owner of identity and roles (ADR-0012), with a bus projection to EDS and ERP, like the deputy today. Screen: Настройки · «Люди и доступ» (report §6.1). Rough size M. It belongs with ADR-0031 phase 2 (10–12 PR, January, `processes README` §12).

### 5.1 Where the addition conflicts with facts or accepted decisions

| Owner's addition | Conflicts with | Comment |
|---|---|---|
| "Not hard-coded" | Nothing; it **is** ADR-0012 (2026-10-22, accepted) | The violations are §2 #1–#15 |
| Project manager owns Органайзер | Report Q14, "новых ролей (HR, второй менеджер) до запуска не вводим" — a recommendation, not a DECISIONS row | Ownership of a module is not a permission (report §4.2), so no conflict. But **the PM role has no section to express its zone** (§3 #5). A PM template without a "project control" section and a PM field on the project would be a label without power (inference) |
| "Project 100 % when all stages are closed; a stage is closed when all its tasks are done" | DECISIONS 2026-11-22 (2) (`:361`): "проект выполнен = акт принят клиентом (или скан) и все счета оплачены", one definition for ERP, warehouse, CRM, Platform and Кабинет | Can be reconciled if the "КП / договор / акт" stages close on today's legal and money facts and tasks only add to them (inference). If "closed" means "all tasks ticked", it competes with the accepted definition and with the statuses ADR-0031 p. 5 keeps in code |
| Project kanban inside Органайзер | DECISIONS 2026-11-10 (`:299`) "заявка и проект — один объект с одной карточкой"; report §3.6 (a second register of projects is a duplicate); DECISIONS 2026-11-22 (`:365`) "работа начинается на Главной" | Belongs to the Органайзер area. For roles: the PM's board must be a **view** over ERP projects, not a second home |
| Messenger with groups and channels | DECISIONS 2026-11-10 (`:297`) "без групповых каналов и звонков" | Plain conflict with his own decision. Needs an explicit reversal |
| Calendar events | DECISIONS 2026-11-10 (`:303`) "личные события не храним (решение 2026-11-03 в силе)" | Meetings as objects: yes (report §7). Personal events: conflict |
| Deputy directors | The existing «замещение» (DECISIONS `:359` (2)) | Different meanings; split them in UI terms before building |
| Launch 26–31 Dec | The report already adds 15–22 PR; ADR-0031 is after launch (DECISIONS `:360` (3)) | The register and zone routing go to January |

## 6. What fits before launch versus January (inference, rough)

**Before launch (S, about 2–3 PR):**
1. Remove role names from step labels and defaults (#2, #5, #13): show the holder's name and position, or the section name.
2. Make "default addressee" an explicit company setting instead of the smallest id (#4).
3. Replace the fixed kinds (#7, #8, #9) with section-keyed kinds, adding registrar, lawyer and signatory.
4. Visas in the queue: already planned as Х-19.
5. Reword ГЛ-3 and ДВ-4б by section, not role (#15).
6. Fix the SPEC §4.1 and §9 wording (#14).

**January, with ADR-0031 phases 1–2:**
- the zones register (§5);
- splitting `admin` into "people and roles" versus "IT and settings", and `company.settings` into "requisites" versus "templates", so HR and lawyer zones can be expressed;
- a "project control" section and a PM field on the project;
- deputy set by admin or HR, and a deputy for a zone;
- replacing `_DECIDER_ONLY` with a "decider" attribute of the zone or role (#1);
- renaming the `director_*` fields (#6).
