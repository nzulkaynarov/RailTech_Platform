# RailTech B2B — E2E UX/UI Audit (eyes-on + code sweep), 2026-07-03

Method: local eyes-on through the browser at **1366px (laptop)**, 1568px, and ~mobile,
across the seller flow (dashboard → deals → deal-detail → **КП builder** → notifications),
plus a 5-dimension static code sweep (orphan routes, notifications, adaptivity, i18n labels,
dead code). Owner's reported observations were all reproduced, plus more. Seed: buyer + seller
(KYC L2 + ACTIVE sub) companies, 8 published railway products with UZS offers.

Status legend: ✅ fixed inline (quick-win, this pass) · 🔨 needs real work ("big feature").

---

## P0 — Blockers

### N1 · Notifications deep-link to generic lists, never the document 🔨
Every actionable alert ("new КП", "signature required", "approval required", "delivery overdue")
drops the user on `/crm/deals` or `/cabinet/deals`, and the FE routes by substring
(`link.includes('quote')`) instead of a resource id. The point of the notification is lost.
*Where:* `backend/crm/services/{contracts,quotes,approvals}.py`, `crm/tasks.py`,
`notifications/signals.py`; `frontend/src/components/Layout/NotificationCenter.tsx:56-66`.
*Fix:* add structured FKs to the Notification model (`quote_id/contract_id/deal_id/fulfillment_id`),
serialize them, emit `#deal/{id}` / `#quote/{id}` hashes; rewrite `notificationTargetPage()` to route on id.

### N2 · Notification copy is vague and identical for both parties 🔨
Messages state a status but not the required action/reason/consequence. Worst: contracts —
buyer and seller both get "требуется подпись сторон", so **neither knows whose signature is
outstanding**. Approvals don't say why (margin below floor / ВЭД). Expiry omits the date.
*Fix:* add `recipient_role`/`context_type`, personalize per recipient
("Требуется ваша подпись: договор #{n}" vs "Договор #{n} подписан вами, ожидает продавца").

---

## P1 — Major

### A1 · КП builder clips on 1366px laptops 🔨 (VISUALLY CONFIRMED)
The fixed 320px (`w-80`) economics rail + ~616px of hardcoded column widths exceed the ~750px
left on a 1366 screen → the page goes into an **invisible horizontal overflow**. Observed:
«Кол-во» truncates «200»→«20»; «Базовая цена» truncates «9500000»→«950» and «UZS»→«UZ»;
the «На согласование» / «Чат с покупателем» buttons and the top-bar icons (bell/settings) are
cut off the right edge. Fits only ≥~1500px.
*Where:* `frontend/src/components/Admin/QuoteBuilderGrid.tsx:370,807,554-585,647-680`.
*Fix:* collapsible/responsive rail (slide-over below ~1400px); real horizontal scroll on the
table (`min-w-0`) or collapse cost columns below 1200px into the expandable row; widen the price
cell + stack the currency picker.

### E1 · Deal-detail («Детали заявки») ALSO overflows at 1366px 🔨 (NEW, eyes-on)
The right-side chat panel is clipped and a horizontal scrollbar appears — same class of issue as
A1, on `#request-detail/{id}`. *Fix:* make the chat a responsive/collapsible column below ~1400px.

### E2 · Top-bar actions clip on wide inner pages at 1366px 🔨 (NEW)
On the builder/deal-detail the header's right icons (notifications, settings) are pushed off-screen
by the page's horizontal overflow. Resolved once A1/E1 overflow is fixed.

### R1 · Orphan page: `SourcingImportPage` unreachable ✅ (PR #224)
Wired end-to-end but in no menu — reachable only by typing `#sourcing-import` (import now lives
inline in the request dialog). OnboardingTour step 1 deep-linked to this dead hash.
*Resolved (world-standard decision):* inline contextual import is canonical, so the standalone
orphan was deleted (page + route + breadcrumb + all App.tsx registrations); the dead `#sourcing-import`
hash now falls back gracefully to the dashboard; the tour step-1 target is `null` (no dead nav) and
its stale "Smart Match" copy was corrected.

### L1 · "Котировки" vs "Коммерческие предложения" vs "КП" — one doc, three names ✅
This is the owner's "there's a Quotes page but I couldn't find how to reach it": the nav item and
the page title used different words. **Fixed inline** — standardized RU on «Коммерческие предложения / КП»
(`crmQuotes`, `pages.quotes.sellerTitle`, `quotesAndPricing`).

### L2 · Deals empty state reversed the workflow ✅
"Создайте первый запрос на КП" told sellers to create a request. **Fixed inline** — neutral,
accurate hint ("Здесь появятся сделки — из входящих заявок покупателей или созданных вами.").

### E3 · Seller «Сделки» surfaces «Новая заявка (RFQ)» (a buyer action) 🔨 (NEW)
Leaks from dual CLIENT+SUPPLIER companies; semantically odd on a seller page.
*Fix:* gate the RFQ-create CTA to the buyer context.

### D1 · `TopLoadingBar` dead component ✅
Complete NProgress-style bar, zero imports. **Deleted inline.**

---

## P2 — Polish

- **P-1 · Notification counter** shows only a capped "9+" — no action-vs-info split, weak unread
  styling, no "all caught up". 🔨
- **P-2 · КП builder detail inputs cramped** (`w-40/w-32/w-24`); product name truncates
  `max-w-[260px]` with no tooltip; qty input has no min width. Partly folded into A1. 🔨
- **P-3 · Missing workflow helper text** — approval-chain jargon, send-irreversibility/versioning,
  "RFQ = приглашение поставщикам ответить". 🔨
- **P-5 · 14 unused shadcn/ui primitives** (accordion, aspect-ratio, button-group, calendar, carousel,
  context-menu, drawer, hover-card, menubar, native-select, navigation-menu, resizable,
  selectable-card, slider) — zero refs. **Deleted inline.** ✅
- **E4 · Seller dashboard KPI «Позиций в каталоге: 0»** despite 8 published products with the
  seller's offers — misleading empty KPI. ✅ (PR #224) Root cause: the backend counted
  `Product.owner_company` (shared PIM) instead of the seller's own offers. Now counts the seller's
  **active `SupplierOffer`s** ("Active listings", the world-standard seller KPI) and is surfaced on
  the dashboard metric strip (eyes-on: reads 8).
- **E5 · Mobile (~550px)** — cards/sidebar adapt well ✅, but data tables horizontal-scroll
  (columns clip); a card layout below `sm` would read better. ✅ (PR #224) New generic
  `ResponsiveDataTable` renders the shadcn table at `sm+` and a divided label:value card list below
  `sm`; applied to Сделки + Коммерческие предложения (eyes-on: cards + working actions menu on mobile).
- **A1-partial · Fixed-width Select triggers** (`DeliveryBasisSelect` `w-[240px]`,
  `QuoteChargesSection` `w-[200px]`) pushed dropdowns off the right edge. **Fixed inline**
  (`w-full max-w-[240px]` / `w-full sm:w-[200px]`). ✅

---

## Fixed inline this pass (quick-wins)
L1 naming · L2 empty state · D1 TopLoadingBar delete · P-5 14 dead primitives delete ·
A1-partial Select width swaps. (tsc / eslint / i18n all green.)

## Deferred to the "big feature" (needs real work)
**A1** builder responsive restructure (rail + table + price column) · **E1/E2** deal-detail + header
adaptivity · **N1+N2** notification model FK + role personalization + deep-links · **P-1** counter ·
**P-3** helper text · **R1** orphan-import decision · **E3** RFQ-CTA context gate · **E4** catalog KPI ·
**E5** mobile table cards.
