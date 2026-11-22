# AREA P: the project → stage → task model

Root R = ``. All paths below are under R (main @ a87c49a92). Abbreviations: ERP = `apps/erp/backend`, BFF = `apps/platform/bff/app`, W = `apps/platform/web/src`, DEC = `docs/DECISIONS.md` (cited by line), SPEC = `docs/product/SPEC-v3.md`. I only read code and docs; I ran nothing. Points already in the 22.11 report (two registries, two cards, five queue kinds that are declared but never produced, no "days on step") are cited, not re-argued.

## 0. Bottom line

1. **There is no project, stage or task entity today.**
   - A «project» is a view of the ERP `Deal` after the client accepts the КП.
   - Stages exist as code in **six different scales**.
   - Tasks are rows computed from facts, plus three narrow stored task types.
2. **The owner's rule «100% = all stages closed = all tasks done» already works for one stage: Расчёт.** «Расчёт готов» is allowed only when all visas are collected. Everywhere else, closure is a coded fact: a signed scan, a payment, an accepted act.
3. **For a standard sale, the owner's rule and the accepted 22.11 definition of «выполнен» can give the same answer**, but only if sales stages are closed by the coded facts. If they are closed by ticking tasks, his new rule breaks his own decisions of 21.11 (2) and 22.11 (2).
4. **His stage list differs from the accepted 7-stage scale.** In SPEC, «Оплата» is a stage, while he calls payments tasks. «Акт» is not a stage in SPEC; it is the exit condition of «Выполнено». «Исполнение» deliberately has no stage. The project also starts at КП acceptance, not at the request.
5. **Projects that are not deals do not exist** in code: «Произвольная задача и проект без сделки — нет». The planned home is WFM/PM, «пока раздел, не система».
6. **The launch date blocks the build.** Stored tasks (`WorkItem`) are February and configurable ERP stages are February–March. Before launch only documents are allowed (DEC 360 (3)). A read-only progress view from existing facts is the most that fits before 26–31 December.

## 1. What a «project» is today

**Entity.** There is one ERP row, `Deal`, in `ERP/sales/models/deals.py`:
- class at line 17; `stage` is a foreign key to the `DealStage` lookup (lines 76-84).
- the number is RQ-…, and becomes PRJ-… with the same NNN after the КП is accepted (lines 99-111).
- `is_project` is a flag, «КП принято» (line 114). It is set in `ERP/sales/services/deal_numbers.py:62-66`.
- `process` is legacy or v3 (lines 116-121).
- There is **no project-manager field**: only `manager` and `assigned_to` (lines 54-75).
- There is **no stage-entered timestamp**. The only history is the pghistory `deal.snapshot` trigger (lines 13-16).

**Definitions in docs and code:**
- SPEC §2.1 line 65: «Проект — та же заявка после принятия КП клиентом».
- DEC 299 (10.11): «заявка и проект — один объект с одной карточкой».
- `ERP/crm/services/projects.py:1-4`: «Проект — не отдельная таблица, а срез сделки». The slice is `PROJECT_STAGES = (CONTRACT_SIGNED, CLOSED_WON)` (line 33).

**Six stage scales for one object:**

| # | Scale | Values | Where |
|---|---|---|---|
| 1 | ERP state machine | DRAFT, KYC_PENDING, RFQ_OPEN, SOURCING, CALCULATING, QUOTE_SENT, CONTRACT_SIGNED (meaning «КП accepted»), CLOSED_WON (meaning «contract signed»), CLOSED_LOST | `ERP/sales/models/lookups.py:6-14`; semantics in `ERP/integration/services/stages.py:16-19` |
| 2 | Contract stage for the CRM ↔ ERP seam | 11 codes: request … closing, won, lost | `ERP/integration/services/stages.py:20-40` |
| 3 | SPEC path, «единственная шкала» | REQUEST, RESOLUTION, CALCULATION, QUOTE, CONTRACT, PAYMENT, DONE, plus LOST | SPEC §2.3 lines 113-128; `BFF/feeds/models.py:34-36`; W/shared/ui/RequestSteps.tsx, used on 5 screens |
| 4 | Project step | CONTRACT, PAYMENT, DONE | `ERP/crm/services/projects.py:36, 190-199`; `BFF/schemas_eds_projects.py:16` |
| 5 | Client status | 6 words | `projects.py:202-217`; `client-statuses.yaml` |
| 6 | CRM deal | open, won, lost, plus `external_stage` and `external_stage_at` | `apps/crm/backend/app/models/deals.py:60-68` |

- (inference) The BFF mapping `deal_step` (`BFF/feeds/numbers.py:31-58`) never produces RESOLUTION. It maps CLOSED_WON to PAYMENT. ERP `project_step` maps a signed contract to PAYMENT. That is two separate mappings for scale 3.

**Registries and cards:**
- «Операции · Заявки» is `/calc/requests`. Its rows are ERP **calc tasks** (`BFF/api/erp_calc.py:202-210`; row fields in `BFF/schemas_erp_calc.py:49-61`). (inference) A request with no calc task yet is not on this list.
- «Главная · Проекты» is `/eds/projects` (`BFF/schemas_eds_projects.py:97-111`).
- The two cards are CalcScreen and ProjectView. Evidence is in report README §2.6 and evidence row 53.

## 2. What is attached to a project today

| Item | Link | Stage in SPEC §2.3, or loose | On the project card? |
|---|---|---|---|
| Calc task (resolution → calc) | `CalcTask.deal`, one per incoming letter, so possibly several per deal (`ERP/sales/models/calc_tasks.py:27-56`); assignees by zone (lines 76-98) | Stage 3 | No (lives on CalcScreen) |
| КП and its versions | `Quote.deal` (`ERP/sales/models/quotes.py:28`) | Stage 4 | Accepted version only |
| Contract | `Contract.deal`; one «live» contract (`projects.py:60-63`) | Stage 5 | Yes |
| Invoices (N) | `Invoice.deal` (`ERP/finance/models/billing.py:31`); an invoice can exist **without a contract** (`ERP/crm/services/manual_invoice.py:1-9`) | Stage 6 | Yes, as a list |
| Payments | `Payment.invoice` and `PaymentConfirmation.invoice` (`billing.py:206-282`) | Inside stage 6 | Through invoices |
| Acts (N) | `Act.deal` and `Act.invoice` (`billing.py:336-352`) | Exit condition of stage 7, not a stage | **One act only** (`BFF/schemas_eds_projects.py:229`), although «done» checks all acts (`projects.py:65-66, 120-122`) |
| Fulfilment, delivery lines, shipments | `Fulfillment` one-to-one (`ERP/sales/models/fulfillment.py:12`); `DeliveryLine.deal`; `Shipment.deal` (`ERP/inventory/models.py:184`); `Reservation.deal` | No stage («отдельной стадии не имеет», SPEC §2.3 line 128) | Delivery and lines yes; shipments no |
| Supplier orders | Linked **per line**: `SupplierOrderLine.deal`, nullable (`ERP/supply/models.py:109-116`), so one order can serve several projects | Loose | No |
| Shortage | Computed, no stored record (`ERP/supply/services/shortage.py:67`) | Loose; a queue row | No |
| Price requests | `PriceRequest.deal`, nullable (`supply/models.py:242`); the project number is not shown to the supplier (plan line 58) | Loose (calc) | No |
| Letters, in and out | EDS `letters.erp_deal_id` (`apps/eds/app/models/letters.py:106`); the form field «Связь с проектом» is optional (`W/modules/eds/new/DealField.tsx:8-11`) | Loose | No |
| Memos and internal documents | EDS `documents.erp_deal_id`, nullable (`apps/eds/app/models/documents.py:69`) | Loose | No |
| Approvals and signing | EDS `approvals.erp_deal_id` (`apps/eds/app/models/approvals.py:63`) | Loose | Through «История» |
| ERP documents projected into EDS | EDS `project_documents` table: contract, invoice, act only (`apps/eds/app/models/project_documents.py:18-38`) | Registry projection | — |
| Client chat in Cabinet | `PortalMessage.context_kind` = deal, quote, invoice or act, optional (`ERP/portal/models.py:300, 320-324`) | Loose | No |
| Lead and Telegram dialogs | By lead or client, not by deal (`apps/crm/backend/app/models/leads.py:22, 132-190`) | Not linked | No |
| Service request | `client_id` and `lead_id` only, **no deal** (`apps/crm/backend/app/models/clients.py:160-175`). SPEC §2.1 says «привязанный к проекту» | Not linked | No |
| Generated files and tech docs | `GeneratedDocument.deal`, `TechDocument.deal`, `PortalUpload.deal`, all nullable | Loose | Partly (PDF and scan) |
| Meetings | **None** (areas/organizer.md §1.6) | — | — |
| Journal | `ActivityLog.deal` (`deals.py:311`) | — | «История» tab |

The project card has two sections: documents (quote, contract, invoices, act) and execution (shipment and lines). See `W/modules/eds/projects/ProjectView.tsx:114, 211-264` and `BFF/schemas_eds_projects.py:224-233`.

## 3. The «done» rule: accepted definition vs the owner's new rule

**Accepted (DEC 361, 22.11 (2)).** «Акт принят клиентом в Кабинете или загружен скан подписанного акта, и все выставленные счета оплачены (SPEC-v3 §2.3, шаг 7)». Delivery-line acceptance is not required.

**Code.** The one predicate is `project_is_done` (`ERP/crm/services/projects.py:112-122`):
- at least one billable invoice exists and all of them are PAID;
- at least one live act exists and all of them are SIGNED.

It is read by stock (`ERP/inventory/services/stock.py:101-109`), the seam stage (`ERP/integration/services/stages.py:168-170`), the portal (`ERP/portal/projections.py:89-100`) and `deal_execution_is_complete` (`ERP/crm/services/deal_documents.py:375-384`).

**Owner's new rule.** 100% = all stages closed; a stage is closed when all its tasks are done.

| Point | Agree or differ | Evidence |
|---|---|---|
| Standard sale (contract → invoices → act) | **Agree** if sales stages close on facts. «All invoices paid and all acts signed» is already a conjunction of stage-closing facts | `projects.py:112-122` |
| Расчёт stage | **Agree literally.** «Расчёт готов» is enabled only when all visas are in | SPEC §3.1 step 4; `CalcReady.allowed/missing` (`BFF/schemas_erp_calc.py:187-190`) |
| No contract (invoice works as the offer) | **Differ.** `project_is_done` ignores the contract. Under the owner's rule an unclosed «Договор» stage blocks 100% unless the stage can be **not applicable** | `manual_invoice.py:1-9`; `project_problems` flags `no_contract` (`projects.py:220-226`) |
| Repeated stages | **Differ.** There can be N invoices (prepayment, remainder; SPEC §2.1 «Счёт»; §3.1 step 9 «счёт на остаток — по факту отгрузки»), N acts, N shipments, N calc tasks and several КП versions. A remainder invoice issued later reopens «Оплата». (inference) The percentage can go down. A fixed count of tasks cannot handle this; a stage instance needs a closure predicate | Payment schedules are deliberately out of the processes programme, separate ADR (`docs/research/2026-11-21-processes-as-data/README.md:145`) |
| Delivery and supplier-order tasks | **Differ.** If supplier orders count as tasks, an open or partly received order or a leftover shortage would block 100% even after the act is signed and invoices are paid. The 22.11 decision says delivery acceptance is not required. DEC 359 (21.11 (1)) puts the act after delivery, so delivery is already implied by the act | DEC 359, 361 |
| Closing by ticking tasks | **Conflict.** A user-made task list must not close «Договор» or «Оплата» without the scan or the payment | DEC 360 (2): «статусы с юридическим, денежным и клиентским смыслом … остаются в коде»; ADR-0031 п. 5 (`docs/adr/0031-processes-as-data.md:44-47`); DEC 361 (2) «одно определение» |
| LOST from stages 2–5 | Not covered. A percentage is meaningless for a lost request | SPEC §2.3 line 126 |
| Internal projects | The owner's rule fits naturally: there are no legal facts, so closure is by tasks | — |

**Recommended reconciliation (inference).** Each stage has two parts:
- (a) a coded **closing fact**, with a lock as in ADR-0031 п. 5;
- (b) user-added tasks, which can **hold a stage open but never close it**.

A stage can be marked «не требуется» only by a named role, with the reason logged. For sales projects the result then equals the 22.11 definition, provided «Договор» is either optional or required by policy. The owner must choose, because the code does not require a contract today.

**Data missing to compute stage progress today:**
- a stage entity or instance;
- entered and closed timestamps;
- a not-applicable flag;
- stored tasks linked to a stage;
- a RESOLUTION mapping in `deal_step`;
- a stage code for execution;
- per-stage «closed» booleans exposed by ERP. Today ERP exposes only the step plus `problems` and `act_blocker`.

## 4. Tasks today

**Stored task entities (narrow):**
- EDS `Instruction`, tied to a letter (`letter_id` NOT NULL, `apps/eds/app/models/instructions.py:37-69`);
- ERP `CalcTask` with `CalcTaskAssignee`;
- EDS approval and signing steps (`apps/eds/app/models/approvals.py:78-84`);
- CRM `StaffTicket`.

**Everything else is computed.** There are 35 `QueueItemKind` values (`BFF/feeds/models.py:37-73`), built per viewer: «мои» (`BFF/feeds/erp_work.py:1-12`).

**Queue kinds by stage:**

| SPEC stage | Queue kinds |
|---|---|
| Before the request (lead) | answer_lead, take_lead, triage_lead, create_request, inbound_mail, inbound_mail_mine |
| 1–2 Заявка, Резолюция | resolve_letter |
| 3 Расчёт | calc_task (visas per line). Price requests have no kind |
| 4 КП | approve_quote, rework_document, sign_document |
| 5 Договор | issue_contract, attach_scan, sign_document (`erp_work.py:185-213`) |
| 6 Оплата | issue_invoice, confirm_payment, overdue_invoice (declared, not produced: README §2.6) |
| Исполнение (no stage) | order_shortage, send_supplier_order, receive_goods, partner_date_change, supplier_overdue, ship_project (`ERP/supply/services/tasks.py:1-15`) |
| 7 Акт → Выполнено | issue_act (`erp_work.py:215-226`), sign_document |
| Cross-stage or not a project | problem_project (declared, not produced), service_request, instruction, instruction_extension, acquaint, approve_memo, pay_memo, ticket, integration_issue, partner_application, register_reply (obsolete) |

**Free-form tasks do not exist:**
- `docs/product/MODULES.md:88-94`: «Произвольная задача и проект без сделки — нет».
- `docs/product/NAVIGATION.md:76`: «Поручения без входящего документа … пока нет».
- «Поручение» in the Create window waits for plan row Х-7 (plan line 224).
- `WorkItem` (kind, object ref, person or role, due, `on_behalf_of`) is ADR-0031 п. 11 and phase 3, **February** (`docs/adr/0031-processes-as-data.md:65, 91`; plan line 268; research README:259-263).

**What «a stage is closed when all its tasks are done» needs:**
- Derived tasks are enough for coded stages, but only if the BFF can list **all open work on project X for everyone**. Today it lists only «мои» (inference from `erp_work.py:1-12`).
- Stored tasks (`WorkItem` with `stage_ref`) are needed for user-added steps and for internal projects.
- (inference) A hybrid is required: derived tasks for coded facts, stored tasks for everything else, both on one per-project list.

## 5. Kanban feasibility

**Portfolio board: columns are stages, cards are projects.**
- Columns could be the 7 `StepCode` values. No single endpoint covers requests and projects together. `/calc/requests` returns calc-task rows; `/eds/projects` returns only CONTRACT, PAYMENT and DONE. The 11-code seam stage is the richest single scale, but it is exposed only in the seam and events (inference).
- Card fields that already exist:
  - number, title, client, step, due, responsible, problems, `act_blocker`, total, `client_status` (`BFF/schemas_eds_projects.py:97-111`);
  - for requests: step, state, due, visas, responsible, assignees by zone (`BFF/schemas_erp_calc.py:49-61`).
- Missing:
  - **days on stage**. Possible sources (inference): pghistory `deal.snapshot` (`deals.py:13-16`); CRM `deals.external_stage_at` (`apps/crm/backend/app/models/deals.py:66-68`); document timestamps such as `client_agreed_at`, `signed_at` and `issued_at` (`BFF/schemas_eds_projects.py` ProjectContract, ProjectInvoice, ProjectAct);
  - «N of M tasks»;
  - a stage blocker for pre-project stages other than `CalcReady.blocker`.
- **Drag-and-drop conflicts with an accepted decision.** DEC 349 (18.11): «доска по этапам — во входящих на январь». The source research says the board is «без перетаскивания», because a stage changes by an action with checks (`docs/research/2026-11-18-flexible-ui-assessment.md:43-45, 111`, 2 PR). No drag-and-drop library is installed (`apps/platform/web/package.json:32-35` has only FullCalendar).

**Board inside a project: columns are stages, cards are tasks.** This needs the per-project work list from §4 and, for free tasks, `WorkItem`. Today it is not feasible beyond showing the coded steps.

## 6. Projects that are not sales

- **No entity exists.** `Deal.company` may be empty, but only for a «черновик-калькулятор без клиента» (`deals.py` field help, lines 25-33). That is not an internal project.
- The docs already foresee a WFM/PM module: «Владеет: задачи, поручения, проекты-досье… Без других модулей: задачи и проекты компании» (`docs/product/MODULES.md:77-94`). Its status is «Пока раздел, не система» (MODULES.md:168).
- Processes that already run outside a deal live as EDS documents:
  - П6 «Закупка вне сделки» (`docs/product/BUSINESS-PROCESS.md:56-58`);
  - П8 «Расходы вне сделок» (BUSINESS-PROCESS.md:65).
- Supplier tenders: «Тендер не проводим» (BUSINESS-PROCESS.md:100). Client tenders arrive by mail as leads (areas/organizer.md:134).
- Hiring: there is no HR entity (areas/organizer.md §1.11).

**What a generic model needs:**
- `Project(kind, template_version, manager/PM, optional deal_ref)`;
- a stage template **as data**, versioned and published per ADR-0031 п. 6-7;
- stage instances: status, entered and closed timestamps, not-applicable, repeatable;
- `WorkItem` linked to a stage;
- for kind = sale, stages bound to the locked coded predicates (ADR-0031 п. 5).

**Where it lives.**
- ADR-0031 п. 1 puts deal stages in ERP.
- A generic project and task domain has no owner system. The candidates are the WFM module or CRM, which owns staff communication (DEC 239, W-9).
- The owner now says the Project manager owns Органайзер, so the domain choice needs an ADR. Size L.

## 7. Conflicts to state plainly

1. **Stage list vs SPEC §2.3, «единственная шкала».** «Оплата» is a stage in SPEC and a task for him. «Акт» is a stage for him and the exit condition of «Выполнено» in SPEC. Changing it touches the `StepCode` contract, RequestSteps on 5 screens and Cabinet client statuses. Those are locked as client-facing statuses (DEC 360 (2)).
2. **«The project is the parent» from the start vs «проект = заявка после принятия КП»** (SPEC §2.1:65; numbering RQ→PRJ, `deal_numbers.py:62-66`). It is compatible with DEC 299, «один объект», if «проект» means the whole deal and numbering stays as is (inference). It also strengthens the report's question 4: one list, one card.
3. **The done formula vs DEC 361 (2) (22.11), «одно определение».** It reconciles only as in §3. The contract question is new and needs his answer.
4. **Projects in Органайзер:**
   - vs «у объекта один дом» (NAVIGATION.md rules line 6; DEC 298-299);
   - vs the report's own advice: README §7 «Второй реестр проектов… не делать» and question 4, projects to Операции.
   - The report must change. Either projects move to Органайзер as their single home and Операции links there, or the Органайзер board is a view.
5. **Tasks in Органайзер vs DEC 365 (22.11), «Главная — работа начинается здесь».** (inference) The per-project board is a view; the personal queue stays on Главная.
6. **Meetings as tasks.** The meeting entity is planned as CRM stage 2, after the pilot (DEC 259, 03.11: «свой полный календарь не делаем, личные события не храним»).
7. **Board timing.** It is in the January inbox, without drag-and-drop (DEC 349, 18.11).
8. **Launch.** The date is 26–31 December (DEC 355). Only phase-0 documents are allowed before launch (DEC 360 (3)). `WorkItem` is February and ERP stages are February–March (ADR-0031:86-92).
9. **Two accountable people per project.** The project's «responsible» is `assigned_to or manager` (`projects.py:348-363`). Neither a PM role nor a PM field exists.
   - Roles are data (CRM), so a PM role template needs no code (`packages/contracts/platform-rbac.yaml:1-7`).
   - MANAGER has only `eds.projects: read` (rbac:69). The sales manager cannot act on the contract or act today.

## 8. Gap table

Sizes as in the report: S = 1–2 PR, M = 3–6 PR, L = 8–15 PR.

| Owner's model element | State | What is needed | Size | System |
|---|---|---|---|---|
| Project as parent from the first request | Partly: one Deal, RQ→PRJ; two registries and two cards | One list and one card for the whole deal; «project» covers stages 1–7 | M–L | ERP, BFF, web |
| Project kinds, internal projects | Missing | `Project` entity with kind and template; optional `deal_ref`; ADR on the domain owner | L | New domain (WFM in CRM or a new service), contracts |
| Stage as configurable data | Missing (6 scales in code) | Stage template per kind, versioned (ADR-0031); sales stages locked to coded facts | L | ERP (phase 4), generic domain |
| Stage instance: entered/closed, not applicable, repeatable | Missing | Stage-history table or derivation from pghistory; not-applicable with reason; repeatable instances for invoices, acts, shipments | M | ERP |
| Per-stage «closed» predicate (sales) | Partly: `project_is_done`, `project_step`, `client_status`, `CalcReady` | Expose a closed flag and reason per stage; decide whether «Договор» is required | S | ERP, BFF |
| Stored task with stage link | Missing; only Instruction (letter-bound), CalcTask, approval steps | `WorkItem` contract and per-domain storage; `stage_ref`; a task can hold a stage open but not close it | L | contracts, CRM, EDS, ERP (phase 3) |
| «All open work on project X» (derived) | Missing; the queue is per viewer | Project-scoped aggregation across CRM, EDS, ERP | M | BFF, ERP filters |
| Progress % | Missing | Closed stages ÷ applicable stages; LOST excluded | S (after the rows above) | BFF |
| Linked items on the project (letters, memos, supplier orders, price requests, client chat) | Partly: link fields exist, the card does not show them | A «Связанное» section in the card | M | BFF, web |
| Service request linked to project | Missing (`client_id` only) | `deal_id` on `ServiceRequest` | S | CRM, bus |
| Meetings as tasks | Missing | Meeting entity with `.ics` (DEC 259, stage 2), linked to project and stage | M | CRM |
| Free task «поручение без письма» | Missing | Generalise Instruction or use `WorkItem` | M–L | EDS or WFM |
| Days on stage | Missing | Stage-entered timestamp | S–M | ERP, BFF |
| Portfolio kanban (stages × projects) | Missing; card data mostly exists | One list endpoint for requests and projects; read-only board without drag-and-drop | M | BFF, web (January per DEC 349) |
| Kanban inside a project (stages × tasks) | Missing | Needs the per-project work list and `WorkItem` | M after L | web, BFF |
| PM role and PM field on project | Missing | Role template (data only); `project_manager` on Deal/Project; contract and bus | S + S–M | CRM roles, ERP, contracts |
| Payment schedules (planned repeat invoices as tasks) | Missing, deliberately out of programme | Separate ADR | L | ERP, Cabinet |
| Tracker connectors (Jira, Notion) for tasks | Missing | (inference) Needs `WorkItem` first. Only statuses go out; visa, signature and resolution stay in the Platform (DEC 303) | M per connector | CRM or WFM |
