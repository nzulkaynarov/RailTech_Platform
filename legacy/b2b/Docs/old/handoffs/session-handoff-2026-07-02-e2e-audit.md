# Session handoff — 2026-07-02 — full E2E lifecycle audit + fixes

**READ THIS FIRST after `git pull` on the other machine.** This is the cross-machine
canon for the E2E-audit work (memory is machine-local; this doc travels via git).

---

## ⛔ DO THIS FIRST: merge the 4 open PRs

All four are **MERGEABLE** against current `main` (HEAD = `#198` F7). They are the tail of
a full hands-on lifecycle audit — each is fixed AND eyes-on verified in the running app.

| PR | Branch | Finding | Notes |
|----|--------|---------|-------|
| **#199** | `fix/contract-seller-name-f8` | **F8** contract named "RailTech" not the seller | backend + template + model migration `0053` + 2 tests + schema regen |
| **#200** | `fix/kyc-no-evidence-warning-f4` | **F4** KYC L2 approvable with 0 docs/no INN | frontend-only |
| **#201** | `fix/kp-pricing-ux-f5-f6` | **F5/F6** КП line grid stale on margin/Incoterm change | frontend-only |
| **#202** | `fix/quote-currency-uzs-f7-latent` | **F7-latent** «Валюта КП» could be non-UZS | frontend-only |

**⚠️ Merge ORDER matters (only friction):** all 4 touch `frontend/src/i18n/locales/ru.json`
+ `en.json`. They add DIFFERENT keys, so merge **one at a time**; after the first merges,
click **"Update branch"** on the remaining PRs so GitHub folds in the i18n delta. If any
shows a real conflict, it's a trivial JSON key add — resolve by keeping both.

CI gates that matter (verify green before merge): **api-contract** + **i18n-symmetry**
(both were passing when handed off). #199 already carries the schema regen (a `verbose_name`
change flows into the OpenAPI schema — lesson re-learned; always regen after model label edits).

---

## What this session did

Owner directive: full E2E audit "с самого начала до закрытия сделки… выявить технические и
бизнесовые проблемы, предотвратить негатив, сохранить репутацию." Walked the whole loop by
hand on a **clean local stack** as buyer / platform-operator / seller, eyes-on every step.

Findings doc (verbose, per-finding repro + fix): **`Docs/ops/e2e-audit-2026-07-02-findings.md`**.

### The 8 findings — ALL fixed

| # | Sev | What | PR |
|---|-----|------|----|
| **F1** | HIGH | No `<Toaster>` mounted anywhere → **every** `toast.*` (~30 sites) silently did nothing | #197 (merged) |
| **F2** | HIGH | «Отправить заявку поставщику» silent dead-end for free-text заявки (NO_RECIPIENTS 400, invisible w/o F1) → added supplier-picker dialog | #197 (merged) |
| **F3** | MED | `token/refresh/` 500 on valid-but-dead token (user gone) + never cleared cookie → 401 + clear | #197 (merged) |
| **F7** | **CRIT** | **UZS-priced КП shown to buyer as «$141M» / «1.76 trillion сум».** currencyStore assumed USD; flipped to UZS-canonical (formatMoney), default UZS, live toggle, catalog own-currency, backend `quote_currency=UZS` default | #198 (merged) |
| **F8** | HIGH | Contract (legal doc) named platform "RailTech" as the seller party | #199 (open) |
| **F4** | MED | KYC L2 approvable with 0 docs/no INN → now warning + REQUIRED reason (kept allowed per owner policy, but audited exception) | #200 (open) |
| **F5** | MED | КП line grid showed stale per-line margin/Сумма until a server round-trip after a margin/Incoterm change | #201 (open) |
| **F6** | LOW | per-line «Маржа» cell looked editable (it's quote-level) → tooltip hint | #201 (open) |
| **F7-latent** | LOW | «Валюта КП» dropdown allowed non-UZS → re-mislabel in builder/PDF; locked to UZS | #202 (open) |

Also this session, MERGED earlier: #191 (security Horizon-1), #192 (e2e suite green),
#193 (ARCH-02 drop per-JWT product cache), #194 (Phase C Slice B unified nav), #195 (KYC
delete confirm UX-01), #196 (WS token hardening batch 2).

---

## ⭐ Eyes-on harness (reuse verbatim — this is how to verify UI on this host)

Cannot type passwords / mint tokens to transcript, but CAN drive the authenticated
Claude-in-Chrome tab. Recipe:

1. **Mint a session:** `RefreshToken.for_user(u)` via `docker compose exec backend python -c …`;
   write JSON to `railtech_frontend:/usr/share/nginx/html/__e2e/<name>.json` (a scratch dir
   served by nginx). In the page: `document.cookie = 'refresh_token=<t>; path=/api/v1/auth/;
   max-age=604800; SameSite=Lax'` then reload. The SPA's `initAuth` → `/me` → interceptor
   refresh picks up the cookie.
2. **Switching users mid-session:** once the SPA runs a full session the server sets an
   **httpOnly** refresh cookie that `document.cookie` CANNOT overwrite. → do a real **UI
   logout** (user menu → Выйти) FIRST, then set the new cookie + reload. (fetch-logout w/o
   the access token 401s and does NOT clear it.)
3. **FE deploy without Docker Hub** (nginx base won't pull on this host): `docker build
   --target builder -t <img> ./frontend` (node:22-alpine is cached; runs `tsc -b` + vite) →
   `docker create`/`docker cp` the `dist/` into the running `railtech_frontend` html dir
   (preserve `__e2e`). Browser HTTP-caches index → clear caches / cache-bust query to load
   the new hashed bundle.
4. **`#hash` deep-links bounce to #dashboard on cold load** (App.tsx route guard) → navigate
   **in-app** (click nav → row → button), don't deep-link.
5. Type-check fast without a full build: `docker run --rm -v $(pwd):/app -w /app node:20-slim
   node_modules/.bin/tsc --noEmit -p tsconfig.app.json`. vitest: `npx vitest run …` (node is
   on PATH now). i18n: `python3 scripts/check_i18n_symmetry.py`.

## Local test data (carte blanche — created via shell)

- Users (all `@e2e-audit.uz`, active): `buyer.owner` (OWNER of **ООО Аудит Закупки**, CLIENT),
  `seller.owner` (OWNER of **ООО РельсМаш Поставка**, SUPPLIER, L2, has BASIC ACTIVE
  SupplierSubscription), `operator` (SystemRole.ADMIN, no memberships).
- Deal #1 «Закупка колёсных пар и колодок Q3 2026»: full cycle walked (RFQ→КП→approve→send→
  buyer-accept→contract CT-2026-00001→buyer-signed). **Quote #1 was reset to DRAFT, margin 30%**
  during the F5 eyes-on (leave as-is or re-send; local only).
- Gotchas: `manage.py core_seed` refuses on DEBUG=False; lookups (SystemRole/DealStage/UOM/
  DeliveryBasis) come from migrations but **Country/Currency are NOT migration-seeded** — seed
  via shell. `CustomUser` has a legacy unique `username` (empty-string collision) → set
  `username=email` when creating raw. A signal **auto-grants CLIENT type to any SUPPLIER**
  company (a seller can also buy) → no pure-seller companies by default.

---

## NEXT (my recommended order)

1. **Merge #199→#202** (see top). Then the E2E audit is fully closed.
2. **Security/reputation backlog** (from the earlier `Docs/audit-2026-07-02-security-arch-ux.md`,
   NOT the E2E audit): my suggestion is **INF-03 CSP + security headers** next (prod has no
   CSP), then **SEC-04** (`NUM_PROXIES` for throttle integrity — needs a coordinated Caddy XFF
   overwrite), **INF-06** (pin GH Actions to SHA). Note: ARCH-07 (`except Exception`) was
   already checked and needs NO change (all sites log/re-raise — not the anti-pattern).
3. **Phase C Slice C** (ADR-0005 unified shell): eyes-on the unified nav for **pure-buyer** and
   **pure-seller** logins (Slice B was verified on the dual user only). Provision those users
   under carte blanche.

## Anti-hallucination — do NOT rebuild
- currencyStore is now UZS-canonical (F7). Do not "fix" it back to USD. All quote/deal/contract
  money is UZS; catalog uses `formatMoney(price, offer.currency_data.code)`.
- Contract/КП seller name resolves via `_quote_seller_company` + `_seller_document_profile`
  (crm/services/quotes.py). Don't reintroduce a "RailTech" fallback.
- KYC no-doc approval is ALLOWED by owner policy (`require_documents=False` in
  accounts/views/company.py); F4 only ADDED a warning + required reason on the frontend.
