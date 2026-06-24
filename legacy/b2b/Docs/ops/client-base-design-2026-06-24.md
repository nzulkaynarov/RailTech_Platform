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

## Flow (matches the owner's hypothesis)
1. Seller picks "Create КП" → **searches a company** (by name/INN).
2. If absent → **"Create client"**: short requisites form (company name, INN optional, contact name,
   email/phone) → creates `Company(is_registered=False)` + `Contact(is_primary=True)`.
3. Seller builds the КП for that client's company.
4. On finish: **Download PDF**, **Copy share link**, or **Send email** (PDF + public link + optional
   register-invite). Registered buyer → in-app + email; offline client → email only.

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
