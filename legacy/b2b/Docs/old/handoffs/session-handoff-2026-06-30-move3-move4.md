# Session handoff — 2026-06-30 (marathon) — Move 2 audit + Move 3 (AI moat) done + Move 4 started

> **READ FIRST on the new machine** (Claude Code memory is machine-local; this travels via git).
> `git pull origin main`, then read this + `Docs/adr/0006-wedge-loop-and-entitlements.md`.
> Continues `session-handoff-2026-06-30-wedge-and-nav.md`.

## TL;DR
A long session. Closed the post-merge adversarial-audit findings on Move 2/U2, implemented the
owner's **hidden-competition** model (per-seller ownership), **completed Move 3 (the AI moat)**, and
**started Move 4 (monetization + wedge metric)**. Discovery: AI #1 (catalog match) and AI #7
(preflight) were ALREADY shipped — so the real Move 3 gaps were pricing-assist + draft-КП (now done).

## Shipped — 7 PRs
**Merged to `main`:**
1. **#167** post-merge adversarial audit (multi-agent Workflow → 9 findings in merged Move 2/U2):
   cross-seller release/assign isolation, `notify_new_message`→`assigned_to`, DealsKanban gate-on-id,
   `assigned_to_name` cross-tenant redaction, claim no-op (SLA anchor), on_commit WS push,
   `_assignment_response` 500; + UX «Настройки КП» icon button in the collapsed КП-rail.
2. **#168** U2 privesc — migration `accounts/0031` demotes over-granted non-OWNER is_system admins by
   WorkspaceRole (never-orphan preserved). [owner decision: option a]
3. **#169** **per-routing ownership** [owner decision: hidden competition — each routed seller works the
   заявка independently, buyer picks]. Ownership moved off the single `Deal.assigned_to` FK → per
   `DealSellerRouting` (`assigned_to`/`assigned_at`, mig `crm/0052`, data copied forward). claim/release/
   assign scoped to the actor's own company; serializer `assigned_to*` per-viewer-routing; notify
   per-routing. `Deal.assigned_to` left **VESTIGIAL** (drop in a follow-up once confirmed dead).
4. **#170** Move 3 **pricing-assist** — `crm/services/pricing_assist.py` + `GET crm/quotes/{id}/pricing-assist/`
   + КП-builder «Цены из офферов» button. Autofills line cost/currency/lead-time from the seller's own
   SupplierOffer.
5. **#171** Move 3 **AI draft-КП** — `crm/services/draft_quote.py` + `POST crm/deals/{id}/generate-draft-quote/`
   + builder empty-state «AI-черновик КП» button. Copies buyer request lines → fresh seller DRAFT quote
   + prefills matched via pricing-assist.
6. **#172** Move 4 **entitlement layer** (monetization keystone) — `CompanyEntitlement`(company,
   feature_key, access ENABLED/DISABLED/DEMO, limit, credits, expires_at, mig `accounts/0032`) +
   `accounts/constants.FeatureKey` + `FREE_FLOOR_FEATURES` + `accounts/services/entitlements.py`
   (`has_entitlement`/`entitlement_state`/`is_demo`/`consume_credit`/`grant_entitlement`). **Nothing
   gated yet — foundation only.**

**Open PRs (merge these):**
7. **#173** Move 4 **time-to-first-КП metric** — `crm/services/metrics.py` + `GET crm/analytics/time-to-first-quote/`
   (routed_at → earliest sent КП frozen_at; median/avg/p90; admin=all, seller=own).
- (this doc PR) the handoff.

Every PR: backend tests + tsc + i18n symmetric + (where applicable) live-API eyes-on.

## Move status
- **Move 0/1/2 — done.** Move 2 hardened by #167/#169.
- **Move 3 (AI moat) — DONE.** match (#1, pre-existing) + pricing-assist (#170) + draft-КП (#171) +
  preflight (#7, pre-existing).
- **Move 4 — STARTED:** entitlement foundation (#172) + wedge metric (#173).

## NEXT — Move 4 remaining (each a focused effort; large)
1. **Gate features on entitlements.** Gate КП `send`/`export` on `FeatureKey.KP_SEND`/`KP_EXPORT`,
   AI draft/match on credits (`consume_credit`). ⚠ Needs a **granting policy** first (who gets KP_SEND
   by default — else you lock out every current seller). The handoff calls for **splitting
   `crm/services/quotes.py` (~1.9k lines) into rfq.py/quoting.py BEFORE gating** so the free RFQ loop
   and the paid КП layer separate cleanly. Then **demo-mode** = an entitlement state (КП build free +
   watermark PDF, gate send/export) + a **React-Admin grant page** (Rule 8: DRF endpoint + page,
   NOT an Unfold action with business logic).
2. **Single Deal-workspace UX** — merge deal-detail + КП-builder into one seller screen; surface the
   **time-to-first-КП KPI card** here (the #173 endpoint exists; FE card deferred to here on purpose).
3. **ADR-0005 phases C** (unified buyer+seller shell — security-adjacent: `X-Active-Context` scopes
   backend data) and **E** (KYC-floor on the BACKEND — today cosmetic only; Layer-0 gap).

## Env (per-machine; may not carry over)
- docker stack up; `gh` installed+authed (this mac); local dev DB migrated through `crm/0052` +
  `accounts/0032`; vite dev :5174; `make migrate` + restart celery after model changes.
- Eyes-on harness: tokens are in-memory + an HttpOnly refresh cookie, so there's **no localStorage
  JWT-inject** — API-level verification mints a server-side access token (simplejwt) and curls the
  backend as that user. The running backend serves volume-mounted code but **may hold stale modules** —
  `docker compose restart backend` after big pulls (caught a real stale-code 403 this session).
