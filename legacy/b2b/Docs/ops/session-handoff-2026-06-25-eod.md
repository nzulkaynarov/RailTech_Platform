# Session handoff — 2026-06-25 EOD (definitive)

> Cross-machine source of truth (Claude Code memory is machine-local; this travels via
> `git pull`). LATEST — read this first. Supersedes `session-handoff-2026-06-25-pm.md`
> and `-2026-06-25.md` (AM). A very large day: 11 verified, merged deliverables incl. a
> two-round adversarial security program. Everything below is MERGED into `main`.

## ⭐ The meta-lesson of the day (make this standard practice)
**Two adversarial review passes both found REAL exploitable bugs in code we had already
MERGED.** Round 1 (review of the day's work) → 2 CRITICAL cross-seller leaks. Round 2
(whole-platform audit) → 1 CRITICAL + 6 HIGH. Every one was reproduced by hand before
fixing. **Before shipping anything non-trivial: run an adversarial finder pass and attack
your own merged work.** It paid off many times over.

## State of `main` — merged this session (PRs #119-#137)
1. **RBAC cost-gate** + **catalog waves 3-4 / dead-code purge / systemic i18n**.
2. **MS-routing — COMPLETE (slices 1-4)**: `DealSellerRouting` (Deal↔seller M2M), routing
   inferred from `product.owner_company` at submit + a buyer seller-picker for free-text RFQs,
   `seller_visible_deal_ids`/`seller_can_access_deal`/`seller_company_routed_to_deal` scope every
   seller surface. Closes the cross-seller confidentiality leak. AppShell invalidates React
   Query on Buyer↔Seller context switch.
3. **UX wave**: list-page error states, ConfirmActionDialog on irreversible actions, catalog
   polish (publish affordance, no-op sort headers), import-FAILURE status, cart→request can_buy.
4. **AI features (5 live, all AI#1 pattern: `services_ai._client` + Structured Outputs +
   AI_IMPORT_ENABLED gate + ScopedRateThrottle + stub tests):** #1 заявка import, #5 bilingual
   catalog-match (`name_canonical`), #7 pre-flight заявка check, #2 PIM product enrich, #4
   deal-chat reply assist. Routes in `core/urls.py`, throttles in `core/settings.py`
   (ai_match/ai_preflight/ai_enrich/ai_chat 20/min).

## 🛡️ Security program — ALL 14 findings remediated (regression-tested)
Two adversarial audits (workflow finders → I reproduced + fixed each). Key fixes — DO NOT regress:
- **C1/H1** cross-seller КП cost/margin/charges: `can_view_quote_costs_for(user, quote)` redacts
  cost unless the quote is the viewer's OWN company's; quote/item/charge querysets scoped to own
  КП (`seller_acting_company_ids`). On a deal routed to A+B, A never sees B's КП internals.
- **H2** КП pricing writes now require `quote.edit_pricing` (`can_edit_quote_pricing`) — a
  can_sell view-only role can't tamper with margin (was `is_seller` only).
- **H3/H4/M1** cross-tenant seller writes (contract sign / act / fulfillment) bind to
  `seller_company_routed_to_deal` — a seller can't act on a competitor's deal.
- **H5** CSV/formula injection neutralized in `core/exporters._normalize_value` (prefix `'`).
- **H6** SVG upload removed (stored XSS) — raster image formats only.
- **M2** CompanyRoleApplication moderation fields (status/reviewed_by/company/...) → read_only.
- **L1** `send_deal_message` refuses the platform-admin viewer. **L2** offer can't attach to a
  foreign DRAFT product. **L3** can't deactivate a company's sole active OWNER (never-orphan).
  **L4** AI Excel read capped at nrows=50_000.
- Round-1 (MS-routing) leaks: product-owner OR-clause removed, QuoteItem/Charge create now
  guards deal access, AI match filtered to PUBLISHED, chat-write routing, sourcing routing.

## Remaining backlog (NOT done — by priority)
- **#7 dashboard analytics not routing-aware** (deferred during audit): a pure seller sees 0
  KPIs — `crm/views/analytics.py` still scopes by buyer-company; needs the helpers refactored
  to deal-id scope. Under-grant, no leak.
- **Frontend refactor debt** (do CAREFULLY one-at-a-time, NOT blind fan-out): F4.x god-component
  splits (>500-line modules — AdminCatalogPage, RequestDetailPage), F3.2 flowStore→React-Query,
  F4.3 userStore→authStore.
- **More AI** (roadmap `docs/ops/ai-features-roadmap-2026-06-18.md`): #3 КП-vs-заявка diff,
  #6 PDF contract/invoice extraction, #8 conversational заявка builder.
- **P0 commercial — deferred by owner**: real payment (Click/Payme), E-IMZO e-sign, in-country
  UZ DB (ЗРУ-547), payment idempotency. **Infra**: structured JSON logging + request-id,
  Sentry-frontend, staging buffer.

## Verification playbook (every wave — agents lie about success)
git-status (files real, endpoints/hooks not invented) → makemigrations --check → merge any
localeKeys yourself (agents return 0 even when asked) → `pytest -q -p no:cacheprovider` →
`tsc -b` (docker node:22) → `python3 scripts/check_i18n_symmetry.py` → browser eyes-on
(Dockerized Playwright `frontend/e2e/run-in-docker.sh <spec> --workers=1`, rebuild frontend
first). For security fixes: REPRODUCE the exploit before AND after. Shared files (locales,
core/urls.py, core/settings.py) → single writer.

## Local accounts (machine-local — recreate per machine, pw `Test1234!`)
`buyer.local@`, `seller.local@` (SUPPLIER+CLIENT → defaults to BUYER context; switch the
sidebar to Seller for the seller pipeline), `admin@railtech.uz` (Platform Admin — `set_password`
if needed; real pw in `.env`). `seed_demo` → catalog/deals. AI needs `ANTHROPIC_API_KEY` (set
locally + prod; `AI_IMPORT_ENABLED` auto-derives). Network to GitHub was flaky today — retry
`git pull` if it fails.
