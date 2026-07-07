# Client base + offline КП delivery — design (2026-06-24)

Seller-managed clients (rep-created, no self-registration) → build КП → deliver by email +
public link, with an optional "register on the platform" invite. Grounded in a multi-agent
world-practice study (Salesforce / HubSpot / Pipedrive / Zoho) + current-schema audit.

## World standard (what the leaders do)
- **3 tiers:** Lead (unqualified) → **Contact** (a person, may have NO login) + **Account** (company)
  → Deal/Quote. One Account has many Contacts; Contacts persist and are reused across deals.
- **Rep-created offline client:** the rep searches for the Account first (dedupe), and if absent
  creates Account + Contact with a short form. Minimum = company name + contact name; **email is
  recommended, not required** (phone is the fallback id). No login is created.
- **Quote delivery:** modern standard = **email with a public "view & accept/download" link (no login)**
  + PDF; pure PDF-attachment is legacy; a portal download is the third option. Acceptance: e-sign /
  click-to-accept / print-sign.
- **Pitfalls to avoid:** duplicate Accounts (always search before create), Contact-without-Account,
  no dedupe on later self-registration, leaking PII.

## Current schema — gaps (file:line)
- `accounts/models/company.py:19` — `Company` is our Account; can exist without any user; has
  `email/contact_person/phone`; **no `is_registered` flag**.
- **No `Contact` model.** People are only `CompanyMember` (login) + `CustomUser`. `crm/models/deals.py:196`
  `Lead` is a website-form audit, never promoted to a Deal/Company.
- `crm/models/deals.py:37` — `Deal.client` is an FK to `CustomUser` (**requires login**);
  `crm/views/deals.py:111` `perform_create` hard-sets `company=user.primary_company, client=request.user`
  → a seller **cannot** open a deal for a new offline client.
- `crm/services/quotes.py:298` — `send_to_client` makes an **in-app Notification only, no email**; the
  PDF is gated to the logged-in `deal.client` → an offline buyer can't receive it.

## Decision (owner-confirmed)
- **Model = Account (`Company`) + new lightweight `Contact`.** Rationale: the goal is a *reusable
  client base* with ongoing communication — per-deal email fields can't provide that. Matches the
  world standard.
- **Delivery = email + public link** (PDF + tokenized no-login view/download).
- **Registration invite = yes.** The КП email carries an optional "register on the platform" link
  **pre-bound to the Contact's Company**, so signup links the new user to the existing card (solves the
  dedupe risk) and converts the offline client into an active one — the acquisition loop.

## Flow (owner-refined 2026-06-24)

Two entry points that converge on ONE unified send:

**Outbound (seller-initiated, e.g. an offline client):**
1. Seller picks "Create КП" → **must select a client to proceed** (hard gate; a КП always has a
   recipient). The picker shows the **seller's OWN client base only** — NOT a platform-wide company
   search (confidentiality: a seller never browses other tenants' clients).
2. If the client isn't in their base → **"Create client"** (short requisites: company name, INN
   optional, contact name, email/phone) → adds `Company(is_registered=False)` + `Contact(is_primary)`
   **into the seller's book**.
3. Build the КП for that client → send.

**Inbound (client submitted an RFQ):** the Deal already carries the client (company + user) → the
client-selection step is **skipped and the recipient is auto-selected** → build КП → send.

**Unified send (offline AND online, one action):** the seller clicks "Send КП"; the *channel* adapts to
the recipient automatically — registered buyer → in-app + email; offline contact → email + public link.
Plus **Download PDF** and **Copy share link** always available.

### Client-base scoping + de-dup policy (owner directive 2026-06-24)
The seller's book is **scoped to the seller COMPANY** (visible to its team — standard team CRM), not
global. It is populated two ways:
- **(a) Auto, inbound:** any client that has sent this seller an RFQ is added to the book. ⚠ "this
  seller" is precise only once **multi-seller routing** (the open tenancy keystone) lands — in today's
  single-seller model RFQs aren't routed, so the auto part activates with routing. Manual creation
  works now.
- **(b) Manual:** the seller creates the card (Company `is_registered=False` + primary Contact).

**De-dup is intentionally light (owner: "I'm not afraid of duplicates").** No global search/merge at
create time (it would also leak other tenants' clients). Within the seller's *own* book we offer a
soft "don't re-enter the same client twice" convenience, not a hard gate. Cross-seller / platform
duplicates are allowed and **reconciled by the platform admin during KYC (merge or reject)** → implies
a future admin **company-merge tool** (separate, later). Invite-on-send links an offline client to its
registered account when they join (Phase 4).

## Model design
- `accounts/Contact`: `company (FK, related_name="contacts")`, `name`, `email (blank)`, `phone (blank)`,
  `position (blank)`, `is_primary (bool)`, `created_by (FK user)`, timestamps. Validation: require
  `email` OR `phone` (world-practice rule).
- `Company.is_registered (bool, default=True)` — `False` for seller-created offline clients; flips to
  `True` when a real user joins (signal on `CompanyMember` create, or the invite-accept path).
- `Deal.client` → **nullable** (offline deals have no user); add `Deal.contact (FK Contact, null)`.
- КП delivery: a `Quote` public access token (random, single-purpose) → unauthenticated
  `GET /api/v1/public/quote/<token>/` returns the КП (client projection) + a PDF download; no margin/cost.
- Service layer only (Rule 8): `create_offline_client(...)`, `send_quote_to_contact(...)`,
  `build_quote_invite_link(...)`; views are thin.

## Phasing (each slice verified)
1. **Backend foundation:** `Contact` model + `Company.is_registered` + `Deal.client` nullable +
   `Deal.contact` + migration + `create_offline_client` service (dedupe by INN/name) + tests.
2. **КП create-for-offline + send:** seller opens a deal/quote for an offline client's company; tokenized
   public quote view/download endpoint; `send_quote_to_contact` (email template `quote_sent` with PDF +
   public link). Tests + API verification.
3. **Frontend:** "select or create client" in the КП flow (search → create dialog); after-КП actions
   (download / copy link / send email). Browser-verified.
4. **Registration invite:** КП email carries a register link pre-bound to the Company; signup links the
   user → existing Company and flips `is_registered`. Dedupe on email match.

## Non-goals (now)
E-signature, click-to-accept tracking, a full buyer portal. The public link is view/download-only for v1;
acceptance stays manual (seller marks accepted) until a later slice.
