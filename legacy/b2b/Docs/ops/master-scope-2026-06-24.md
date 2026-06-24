# Master scope — debts + features (2026-06-24)

Consolidated from every backlog doc (roadmap, 3 handoffs, catalog/UI/platform audits, tech-debt,
stability, AI roadmap, ADR-0003, client-base design) via a 5-agent sweep, **status re-verified against
current code** + this session's work. 204 raw items → deduplicated below. Contradictions reconciled in §5.

**Status:** ~71 done · ~25 partial · ~108 open (raw, pre-dedup). The big truth: **most "open" critical
items are actually DONE on un-merged branches** — the first lever is merging, not building.

---

## 1. DONE but UN-MERGED — integration backlog (do this FIRST)

These are complete + tested + browser-verified this session, sitting on feature branches. Nothing new
is needed except merge + one schema regen.

| Branch | Contents | id(s) |
|---|---|---|
| `feat/idempotency-key` | Idempotency-Key middleware | F2.4 |
| `feat/optimistic-locking` | ETag/If-Match 412 on Quote/Contract/Invoice | F2.5 |
| `feat/api-codegen-drift-gate` | openapi-typescript + CI drift gate | F2.7 |
| `feat/api-versioning` | URLPathVersioning + Sunset | F2.6 |
| `feat/jwt-httponly-cookie` | refresh→HttpOnly cookie, access in memory | F2.1 |
| `feat/catalog-security-wave1` | C2 offer scoping, C3 import owner, M6 read-only, H2, H3 seller pricing UI, owner-DRAFT | C2,C3,M6,H2,H3 |
| `feat/admin-audit-remediation` | A i18n (stage/role by code), B purge retired SystemRoles, C route | UI-admin A/B/C |
| `feat/client-base-offline-kp` | Contact model, Company.is_registered/stated_inn, Deal.contact, create_offline_client (seller-scoped) | CB phase 1+2a |

⚠ **Merge-order hazards:** (1) `feat/api-codegen-drift-gate` adds a CI gate that fails if `schema.json`/
`schema.d.ts` drift — after merging the API-changing branches (F2.1 auth views, F2.6 versioning, catalog),
regenerate `spectacular` + `gen:api-types` once and commit. (2) Two `0019_*` accounts migrations exist on
parallel branches (`0019_company_is_registered_contact` on client-base vs `0019_purge_retired_system_roles`
on admin-remediation) → needs a `makemigrations --merge` node at integration. (3) The catalog & admin docs
were edited on different branches — reconcile the audit docs on merge.

---

## 2. P0 — commercial blockers (genuinely OPEN, gate go-live)

| id | item | notes / dependency |
|---|---|---|
| **MS-routing** | **Multi-seller routing — confidentiality keystone** | `seller_sees_all_deals()` still see-all (permissions.py:156). RFQ→target-seller FK/M2M + queryset scoping + buyer "pick seller" UI. **Blocks:** real multi-tenant confidentiality, the empty seller pipeline, AND client-base auto-populate-from-inbound (§3). Biggest single item. |
| **P0-payment** | Real payment provider (Click/Payme/Stripe/1C) | replaces manual record-payment placeholder |
| **P0-esign** | Qualified E-IMZO e-signature | replaces manual sign placeholder |
| **P0-db-uz** | In-country DB (UZ data-localization ЗРУ-547) | infra/legal |
| **P0-pay-idem** | Payment idempotency `UniqueConstraint(invoice, reference)` | small, do with payment work |

> Owner directive (tech-debt doc): P0 commercial blockers were **deliberately deferred** until the stability
> bar is met — this is strategy, not an omission.

---

## 3. Client base — owner's active feature (phase 1 done; build next here)

Depends on `feat/client-base-offline-kp` (phase 1+2a merged). Per owner's refined design
(`client-base-design-2026-06-24.md`):
- **CB-send (BF.2/KP2)** — unified КП send: recipient = deal.client (registered) OR deal.contact (offline);
  channel auto (in-app+email vs email+public link). `send_to_client` currently in-app only.
- **CB-public-link (KP3)** — tokenized `GET /public/quote/<token>/` view/download, no login.
- **CB-invite (KP3)** — КП email carries a register link pre-bound to the Company (acquisition loop + dedup).
- **CB-deal-for-offline** — seller opens a Deal for an offline client's company (contact, client=null).
- **CB-auto-populate** — book auto-fills from inbound RFQs → **depends on MS-routing** (can't scope "RFQ to me"
  until routing exists). Manual create works now.
- **Admin company-merge tool** — reconcile duplicate clients at KYC (owner: "dups OK, admin merges").

---

## 4. Open work by theme (deduplicated, post-merge)

**Catalog remaining (after wave-1 merge):** H4 server-side pagination (admin lists, also `M1/M2`), H5/H6
railway-group → 400 not 500, M3-M5 import (price/progress/dry-run), M7/M9/M10 hs_code+MPN round-trip, M8
form useMemo→useEffect (done on H3 branch for ProductFormSheet), dead-code tree (`PublicCatalog` + dead
`catalogApi` methods), L1-L6 polish.

**Systemic i18n (raw DB `*_name` in localized UI)** — same class fixed for admin deals/users; still open on:
`I18N-Deal` (DealQuotePage), `I18N-Quotes`, `I18N-Request`, `I18N-TeamSettings` (workspace roles),
`I18N-Users` (membership panel), `I18N-AdminCatalog` (product status). One sweep via `lib/codes.ts` label maps.

**Frontend consolidation/debt:** F3.2 flowStore→React-Query (buyer RequestDetailPage still on flowStore),
F3.3 one buyer-approval surface (⟸F3.2), F3.6 billing pages redesign, F4.1 god-components/TanStack Table,
F4.2 onNavigate prop-drilling, F4.3 auth source unify (userStore→authStore), F4.5 split >500-line modules.
F3.5 ConfirmActionDialog on irreversible actions. **PLATFORM-P0-5** list-page error states (7 pages, partial).

**UI seller dead-ends (UI-B2/B3):** gate Leads/Analytics/Clients nav by capability (403 today). *Note: handoff
says seller nav dead-ends were removed in UI-audit — verify if still present post-#14.*

**Infra/stability:** F0.3 deploy-gate on green CI (⟸ CI healthy), F0.1 external S3 (KYC/PDF off local FS),
PLATFORM-P0-8 structured JSON logging + request-id, Sentry-frontend activation, staging buffer, F1.4
Celery/Redis healthcheck, Neon→VPS backup RTO/RPO runbook, DMARC tighten.

**Testing:** F7.1 live E2E buyer↔seller (browser), F7.2 Playwright harness formalize, F7.3/coverage→50%.

**AI features (roadmap F6.x, all open, lower priority):** semantic match (заявка→catalog) #1, PIM enrich #2,
КП-vs-заявка diff #3, chat reply-assist #4, RU↔UZ normalize #5, PDF extract #6, pre-flight #7, conversational
#8. Owner-aligned pipeline F6.X (intake→match→enrich→promote). Branch from fresh main.

**Tenancy (ADR-0003):** D1-D3 done; D4 org-admin (roles + charge-templates done; RBAC field-group matrix
optional); D5 = MS-routing (§2).

---

## 5. Dependencies + contradictions reconciled

**Key blocking edges:**
- `MS-routing` → CB-auto-populate, true confidentiality, seller pipeline.
- CB phase1 (done) → CB-send → CB-invite.
- catalog wave1 (done/branch) → wave2 (H2/H3 done) → wave3 (H4) → wave4 (H5/H6/M).
- F3.1 (done) → F3.2 → F3.3 → F3.4.
- CI green → F0.3 deploy-gate.
- payment work → P0-pay-idem.

**Contradictions found & resolved:**
1. **Subscription gate** — F0.2 "done" vs PLATFORM-P0-7 "not enabled" → **DONE**; verified `assert_seller_can_operate`
   wired in quotes/contracts/billing services. P0-7 is stale.
2. **Catalog C2/C3/M6/H3** — docs/agents split between open/partial/done → **DONE** on `feat/catalog-security-wave1`
   (un-merged). Audit doc said C1/H1 "fixed" on a branch not yet merged — same pattern.
3. **F3.1 seller consolidation** — roadmap "L/open" vs handoff "merged #14" → **DONE** (commit 7311b0d).
4. **flowStore "retired"** — comment stale; RequestDetailPage (buyer) still uses it → F3.2 **PARTIAL**.
5. **Multi-seller routing** — ADR-0003 calls it the keystone, but roadmap lists no sprint for it → owner
   **deferred/reprioritized**. It still blocks client-base auto-populate — flagged, not lost.
6. **КП email delivery** — in handoff as a "business feature" with no roadmap F-task → now owned by the
   client-base design (CB-send). No longer an orphan.
7. **Sentry-for-Celery** — platform-audit §1 "not connected" vs its own correction table "connected" →
   **connected** (settings). False alarm.
8. **Duplicate ids** — same finding under C2 / Catalog-C2 / C2-offer-isolation / wave-C2-C3-M6 (agents didn't
   share an id space). Deduped here to canonical ids.

**Omissions (in no doc, captured here):** admin company-merge tool (implied by "dups merged at KYC"); the
systemic i18n sweep beyond admin; the two-`0019`-migration merge node.

---

## 6. Recommended sequence
1. **Merge the 8 done branches** (§1) + resolve the migration-merge + regenerate the API schema. Biggest
   value-per-effort: turns ~done-on-branch into shipped.
2. **Client base CB-send → CB-public-link → CB-invite** (owner's active thread; phase1 already merged).
3. **MS-routing** (the keystone — unblocks confidentiality + client-base auto-populate + seller pipeline).
4. **Catalog waves 3-4 + systemic i18n sweep** (mechanical, browser-verifiable).
5. **P0 commercial** (payment + e-sign + in-country DB) when the stability bar is met.
6. **Frontend debt (F3.x/F4.x), infra/stability, AI** — as capacity allows.
