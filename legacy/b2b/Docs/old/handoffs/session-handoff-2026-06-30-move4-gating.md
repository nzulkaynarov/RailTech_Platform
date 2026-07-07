# Session handoff — 2026-06-30 (late) — Move 4 monetization gating in progress

> **READ FIRST on the new machine.** `git pull origin main`, then read this +
> `Docs/adr/0006-wedge-loop-and-entitlements.md`. Supersedes
> `session-handoff-2026-06-30-move3-move4.md` (same day, earlier). Memory is machine-local — this
> doc is the cross-machine source of truth.

## Where we are
**Move 3 (AI moat) = DONE.** **Move 4 (monetization) well underway:** entitlement layer + two live
paid gates (КП send, AI draft) + the wedge metric. Deploy is GREEN again after a hotfix.

## Shipped today (all MERGED unless noted) — 11 PRs
- #167 post-merge adversarial audit (9 findings) + UX · #168 U2 privesc migration · #169 **per-routing
  ownership** (hidden competition: each routed seller works independently, buyer picks).
- #170 pricing-assist · #171 AI draft-КП  → **Move 3 done** (AI #1 match + #7 preflight were already shipped).
- #172 **entitlement layer** (`CompanyEntitlement` model, `accounts/constants.FeatureKey`,
  `FREE_FLOOR_FEATURES`, `SUBSCRIPTION_BASELINE_FEATURES`, `accounts/services/entitlements.py`:
  has_entitlement / entitlement_state / is_demo / consume_credit / grant_entitlement / can_send_kp /
  can_export_kp, mig `accounts/0032`).
- #173 **time-to-first-КП metric** (`crm/services/metrics.py` + `GET crm/analytics/time-to-first-quote/`).
- #174 handoff doc.
- #175 **gate КП send** on `kp.send` (`send_to_client` raises `KP_SEND_NOT_ENTITLED`→403).
- #176 🔴 **deploy hotfix** (see incident).
- #177 **gate AI draft** on `ai.draft` + credits (`generate_draft_quote`→`AI_DRAFT_NOT_ENTITLED`→403).

## Entitlement model (how gating works — important)
The app gates on a **FeatureKey**, never a plan name. `has_entitlement(company_id, key)` resolves:
1. key in `FREE_FLOOR_FEATURES` (ai.match, ai.preflight) → always True.
2. an explicit `CompanyEntitlement` row → ALWAYS wins (ENABLED/DISABLED/DEMO, expiry, credits).
3. else key in `SUBSCRIPTION_BASELINE_FEATURES` (kp.send, kp.export, ai.draft, roles.custom) AND the
   company has an **operational SupplierSubscription** → True. **This is why no current seller is
   locked out** — a subscription grants the baseline; explicit rows are for promo / demo / disable.
`can_send_kp` / `can_export_kp` = has_entitlement AND not is_demo (demo can build, not output).
`consume_credit` mirrors the same baseline. To grant manually: `grant_entitlement(company_id, key,
access=..., credits=..., expires_at=...)`.

## 🔴 Incident (resolved) + ⚠️ standing risk
- **Deploy was broken ALL session** by a prod `tsc -b` error (`QuoteBuilderGrid:263`, frozen_currency
  null vs undefined, from #170). Local `tsc --noEmit` is LOOSER than prod `tsc -b` and missed it. #176
  fixed it. **ALWAYS verify FE with `cd frontend && npm run build`, not `tsc --noEmit`.**
- **CI (GitHub-hosted) is billing-blocked** ("job not started — payments failed / spending limit") →
  the green-gate (incl. the `frontend-build` job that would have caught #176) does NOT run. **Deploy
  runs on a self-hosted runner**, so it deploys. Until billing is restored, there is NO automated
  pre-merge gate — verify locally (pytest + `npm run build` + i18n) before every merge.

## NEXT — Move 4 follow-ups (bounded; pick any)
1. **Gate КП export** on `kp.export` — wire `can_export_kp` into `crm/views/exports.py`
   `handle_quote_export`. ⚠ Scope to the SELLER's export only — the buyer's client-projection PDF
   download must NOT be blocked (distinguish caller; PublicQuoteView client-token path is separate).
2. **Demo-mode watermark** on the КП PDF when `is_demo(company, kp.send)` —
   `crm/templates/crm/quote_pdf.html`.
3. **FE polish** — friendly «оформите подписку, чтобы отправить/экспортировать» on the 403
   (`KP_SEND_NOT_ENTITLED` / `AI_DRAFT_NOT_ENTITLED`) + disable the buttons when not entitled (best:
   project entitlements into `MeSerializer.capabilities` so the FE reads them). i18n ru/en.
4. **React-Admin entitlement grant page** + DRF endpoint (Rule 8 — not an Unfold action).
5. **Single Deal-workspace UX** (+ FE KPI card for the #173 metric endpoint).
6. Optional refactor: split `crm/services/quotes.py` (~1.9k lines) into rfq.py/quoting.py.
- Also ADR-0005 phase C (unified buyer+seller shell — security-adjacent, X-Active-Context) and E
  (KYC-floor on the BACKEND — today cosmetic only).

## Env / verify recipe (per-machine)
`make up && make migrate` (DB through `accounts/0032` + `crm/0052`); restart celery after model
changes. Tests: `docker compose exec -T backend python -m pytest crm/ accounts/ -q -p no:cacheprovider
--reuse-db`; i18n `python3 scripts/check_i18n_symmetry.py`; **FE `cd frontend && npm run build`**.
Eyes-on harness: token in-memory + HttpOnly refresh cookie → mint a server-side access token
(simplejwt) for API checks, or inject the `refresh_token` cookie (path `/api/v1/auth/`, SECURE=False
in dev) to drive a seller session in the browser. `gh` authed on the 06-30 mac only.
