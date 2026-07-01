# Session handoff — 2026-07-01 EOD — Move 4 polish COMPLETE · quotes.py split · KYC-floor · FE dead-code

> **READ FIRST on the new machine.** `git pull`, then read this. Memory is machine-local; this git
> doc is the cross-machine source of truth. Supersedes `session-handoff-2026-06-30-EOD.md`.
> **Two branches are UNMERGED and ready to merge (see below).** Everything else is in `main`.

## State
Move 4 monetization polish (items 1–4 from the 06-30 EOD handoff) is **DONE**. All four polish PRs
were merged into `main` (the 6 `feat/move4-*` branches are ancestors of main — verified). On top of
that, this session added the **quotes.py architectural split**, the **backend KYC-floor (ADR-0006
Phase E)**, and a **frontend dead-code pass** — these sit on two open branches awaiting merge.

## ⬜ MERGE THESE FIRST (2 open branches, both verified locally, disjoint file sets)
1. **`refactor/split-quotes-rfq`** (backend; 3 commits) — merge before `main` diverges further.
   - `refactor(crm)`: split `crm/services/quotes.py` — the **free buyer-RFQ** logic moved to a new
     leaf module **`crm/services/rfq.py`** (buyer_add/update/remove_request_item(s),
     merge_request_lines, buyer_update_request_meta, route_request_to_sellers, submit_request,
     route_deal_from_catalog, REQUEST_EDITABLE_STAGES); the **paid КП engine stays in quotes.py**
     (QuoteCalculationService, QuoteLifecycleService, apply_company_quote_defaults, etc.). Facade
     re-exports in `crm/services/__init__.py` keep the public `crm.services.X` API 100% stable.
     Callers repointed: `crm/tests/test_buyer_add_request_item.py`, `test_ms_routing.py`,
     `sourcing/tasks.py`. This realizes the owner's "features carved out separately, core separate".
   - `feat(kyc)` **ADR-0006 Phase E — backend KYC floor**: new
     `accounts/services/kyc.company_kyc_verified(company_id)` + `KYC_VERIFIED_CODES = {L2_VERIFIED,
     L3_CONTRACTED}`. `submit_request` now raises `PermissionDenied("KYC_REQUIRED_TO_SUBMIT")` below
     L2. **Register + browse + build a DRAFT заявка stays free; only SUBMIT requires L2.** This makes
     «после KYC = минимум» real on the backend — it was FE-cosmetic only (the Layer-0 gap). FE
     message added: `apiErrors.KYC_REQUIRED_TO_SUBMIT` (ru/en). Test: `crm/tests/test_kyc_floor.py`.
   - `test(notifications)`: fixed a **stale red test** the full-suite pass surfaced —
     `test_seller_notified_when_request_opens` was RED on `main` (the "Новая заявка" fan-out moved to
     routing-scoped `DealSellerRouting` in Move 2 but the fixture created no routing → 0≠1). CI is
     billing-blocked so it slipped in. Fixed the fixture to route the deal. **Full backend suite now
     557 green.**
2. **`chore/frontend-dead-code`** (frontend; 1 commit; off `main`, independent of #1) — Docker
   builder build (`tsc -b` + vite) GREEN, i18n symmetric. Removed grep-proven dead FE code tied to
   **sunset concepts** (no behavior change): `hooks/useStatusChoices.ts` + `api/statusChoicesApi.ts`
   (Phase-2 status lookup, self-consuming); `crmApi.assignDeal` (deal.manager assignment — superseded
   by `claimDeal`/routing claim); `crmApi.submitLead` (lead-creation stub; listLeads/convertLead stay);
   `sourcingApi.getRequests/getRequestDetail` + `SourcingRequest` interface (legacy sourcing-requests,
   consolidated into Deals).

## 🟨 OWNER DECISION — dead FUNCTIONALITY, deliberately NOT deleted
The FE dead-code survey flagged these as "unreferenced", but each is a **live-but-unwired capability**,
not dead code — deleting silently would remove a real feature or roadmap work. Decide per item:
- **Reassign-product feature** — `components/CRM/ReassignProductDialog.tsx` (+ `useMatchCandidates` /
  `useReassignProduct` / `crmApi.reassignProduct` / backend `crm/quote-items/{id}/reassign-product/`,
  which is LIVE). The dialog is the ONLY FE surface and is **never mounted** → the whole reassign flow
  is unreachable in the UI. **Re-wire (add the entry button in the КП-builder) OR cut the chain.**
- **`supportApi.deleteTicket`** — live support feature, delete action just unwired.
- **`adminApi.openBreakGlass`** — G2 audited break-glass (admin-planes roadmap); WIP scaffolding, keep.
- **`accountsApi.getCompanyTypes`** — live company-type lookup, no picker wired yet.
- **FE→BE orphan endpoints** now with zero FE callers after the cleanup: `crm/status-choices/` and
  `sourcing/requests/`. Candidates for a **dedicated backend removal pass** (viewset+serializer; check
  for other consumers first — not touched here because BE removal is riskier).

## ⛔ NEXT — needs a RUNNING-APP eyes-on channel (do NOT ship blind)
Both remaining big items are god-component UI refactors. Memory rule (CRITICAL): never ship UI verified
only by `tsc`/tests. This machine can't run React natively (no node/`rollup-darwin`) and I cannot enter
admin credentials to drive admin pages. Get a verify channel first (seller login + Playwright, or a
Docker preview, or `npm install` on a capable box).
- **#3b Single Deal-workspace UX** — merge deal-detail + КП-builder into one seller screen; surface the
  **time-to-first-КП KPI card** there (already shipped standalone on the SellerDashboard this session —
  `Dashboard.tsx` `TimeToFirstQuoteCard`, endpoint `crm/analytics/time-to-first-quote/`).
- **ADR-0005 Phase C** — unify buyer+seller into one shell. **Security-adjacent:** `X-Active-Context`
  currently scopes backend data; unifying the shell needs a page-derived-context redesign so a buyer
  can't see seller-scoped data. Keep every server-side gate (can_sell/can_buy + CompanyType-floor +
  cost redaction + routing-scope + ADMIN_VIEWER_CANNOT_ACT) — the shell blur is cosmetic only.

## ⚠️ Standing notes (unchanged)
- **CI (GitHub-hosted) billing-blocked** — pre-merge green-gate does NOT run. Verify locally before
  every merge: `docker compose exec -T backend pytest crm/ accounts/`, `python3
  scripts/check_i18n_symmetry.py`, and the FE prod build via **`docker build --target builder -f
  frontend/Dockerfile frontend`** (runs `npm run build` = prod `tsc -b` + vite; this host has no node).
- Migrations through `accounts/0033` + `crm/0052` (no new migrations this session — Phase E is a
  service-layer gate, no schema change). Restart celery after model changes (none here).
