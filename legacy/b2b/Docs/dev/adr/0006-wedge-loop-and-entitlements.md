# ADR-0006 — Wedge: the request→quote→contract loop is the product; entitlements wrap it

Status: Accepted (2026-06-30, owner: «принимаю все»). Supersedes the "broad multi-service platform"
framing of the prior discussion; refines (does NOT reverse) ADR-0005.

Amended 2026-07-07 (owner decision, see `Docs/dev/specs/spec-remaining-2026-07-07.md` §2/§3):
**Leads reclassified CUT → KEEP** as the top-of-funnel of the CRM counterparty layer — see
"Amendment 2026-07-07" below.

## Context / decision

The bottleneck is **throughput of client requests**: a 5-person team works заявки sequentially,
no automation, 2-3 extra clients = chaos. The product value is the loop **first request →
fast quality КП → signed contract**, with **speed as the moat** (78% of B2B buyers buy from the
first responder; the industry answers an RFQ in 3-5 days — minutes is a defensible moat, not a
marginal gain). We will NOT build a unique ERP / EDO / Marketplace (we'd lose to 1С / Didox /
Faktura.uz on their turf — the parity trap). We nail this one slice.

**The moat is AI-acceleration of the loop** (request → structured lines → catalog auto-match →
draft КП), NOT Kanban/SLA (that's CRM hygiene). The catalog matcher already exists
(`sourcing/services_ai.py match_lines_to_catalog`) but is unwired — highest-ROI dormant asset.
But AI is useless on a leaky loop, so: **make the loop honest first (cheap), then build the AI
moat (expensive, and monetizable).**

Reconciliation with ADR-0005/the entitlement memo: the loop = the free, flawless core that earns
trust + adoption; **AI-accel + scale = the paid layer**. AI moves from "side feature" to "core
differentiator you monetize". This is a refinement, not a reversal.

## Two honest push-backs (tech-lead, not yes-man)

1. **"Unify UI/UX → fewer tests" is half-true.** Unification removes duplicate per-variant tests
   (real saving), but a shared core = shared **blast radius** (one change to the shell / design
   system / capability engine breaks many features). Reframe: unify to cut REDUNDANT tests, then
   reinvest the saving into **seam/contract tests + visual-regression on the design system +
   feature flags** — not "fewer tests" overall.
2. **Don't sell the role FLOOR / don't fight ERP.** Keep a free RBAC floor (OWNER + basic roles);
   sell advanced/custom roles. The permission engine КП reads stays free (else circular).

## KEEP / PERFECT / CUT

- **PERFECT (core loop):** Deal+FSM, Quote/Charge/approvals, Sourcing-import + Smart Match, AI-intake.
- **KEEP minimal (loop finish line, NOT an ERP):** catalog Product/SupplierOffer (price source),
  RBAC/DocProfile, master_data, notifications, messages, a flat Contract + one Invoice as "контракт
  взят", the subscription GATE (not the tier UI).
- **CUT (ballast / dead / duplicates ERP·EDO·marketplace):** ~~Leads (403 dead page)~~ → **KEEP,
  amendment 2026-07-07 below**, Analytics page + CRMAnalyticsView (orphan — cut executed 2026-07-07),
  Clients page (orphan — cut executed; superseded by the CRM counterparty layer), Fulfillment (WMS dupe);
  DEFER carefully (migrations): Payment-ledger + Act (EDO dupe); DEFER: subscription tier UI. Every cut
  shrinks the test surface — the GOOD "fewer tests".

## Amendment 2026-07-07 — Leads = KEEP (top of the CRM funnel); analytics cut executed

Owner decision (2026-07-07): the platform gets a **CRM counterparty layer** — "книга контрагентов
с историей" (clients AND suppliers with an interaction timeline), spec:
`Docs/dev/specs/spec-remaining-2026-07-07.md` §2. That changes the cut-list:

- **Leads — KEEP (was CUT).** `Lead` (`crm/models/deals.py`) + `LeadViewSet`/public `LeadCreateView`
  + `convert_lead_to_deal` are NOT ballast: they are the canonical top-of-funnel of the CRM layer
  (unqualified inbound prospect → converts into Account+Contact+Relationship+Deal). The 2026-06-30
  framing saw only the dead frontend page; the backend loop is load-bearing for the counterparty book.
  Follow-up (CRM layer, not this amendment): a leads inbox page + `convert_lead_to_deal` creating the
  Relationship edge.
- **Analytics — partial cut, executed 2026-07-07.** Orphan `CRMAnalyticsView` + route
  `/api/v1/crm/analytics/` + dead frontend caller removed (zero callers, zero tests).
  `DashboardAnalyticsView` and `TimeToFirstQuoteView` STAY — they feed the Operations Inbox and the
  wedge KPI.
- **Clients page cut stands** — replaced by the CRM layer's «Контрагенты» page (spec §2.2), which is
  relationship-scoped (seller sees «Клиенты», buyer sees «Поставщики»), not the old flat page.

## Roadmap (loop first, monetization wraps it, cut early)

- **Move 0 — loop integrity (DONE, branch feat/move0-loop-integrity):** capture swallowed FSM errors
  in send/approve/reject + auto RFQ_OPEN→CALCULATING on send (the КП-stuck-in-RFQ_OPEN dead-end);
  seller re-match permission (was IsPlatformAdmin → 403); contract notifications to both sides + to the
  КП author (not NULL deal.manager) on PENDING_CLIENT + SIGNED; auto CONTRACT_SIGNED→CLOSED_WON when
  both sign (triggers the auto-invoice finish line); КП-expiry notifies prepared_by; +2 regression tests.
- **Move 1 — cut ballast early** (shrink surface before building) — needs the cut-list executed.
- **Move 2 — assignment layer (de-serialize the 5-person pile):** `Deal.assigned_to` + round-robin +
  capacity-cap + claim-lock + routing-aware notifications (stop the fan-out to the whole seller pool) +
  SLA timers + work-queue/Kanban. This is the felt-pain fix.
- **Move 3 — AI moat:** wire `match_lines_to_catalog`; intake completeness/exception + assumption-list +
  confidence; pricing-assist from SupplierOffer history; draft-КП. "minutes, not days."
- **Move 4 — UX wrapper + instrumentation + monetization:** single Deal-workspace (state + next-action +
  owner + SLA), `time-to-first-КП` metric, then entitlements (ADR-0005/0006) gate the AI-accel + scale —
  monetize the moat, not the core.

## Risks

- KYC-floor is still FE-only (Layer-0 gap) — "after KYC = minimum" isn't true on the backend until
  Phase E. Don't claim it done.
- Blurring roles must not weaken server gates (cost/margin redaction, Type-floor in is_seller,
  routing scoping, ADMIN_VIEWER_CANNOT_ACT) — ADR-0005 risk, unchanged.
- `crm/services/quotes.py` mixes the free buyer-RFQ and the paid КП engine in one ~1.9k-line file →
  split (rfq.py free / quoting.py gated) before gating КП as an entitlement, else toggling КП breaks
  the free заявка.

Anchor files: `backend/crm/services/{deals,quotes,contracts}.py`, `backend/crm/tasks.py`,
`backend/crm/views/quotes.py`, `backend/sourcing/services_ai.py` (unwired matcher),
`frontend/src/config/navigation.tsx`. See ADR-0005 (unified nav + capabilities).
