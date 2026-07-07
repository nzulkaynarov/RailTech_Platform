# Release smoke checklist (~10 min)

Run this by hand against the target environment **after every deploy** (staging
first once it exists, otherwise prod). It mirrors the automated golden path —
if the automated `test_golden_path.py` is green, this should pass; the manual
pass catches UI/integration issues automated layers can't see.

Environment: `https://b2b.railtech.uz`  ·  API: `https://b2b.railtech.uz/api/v1/`

## 0. Health (30s)
- [ ] `GET /health/` returns 200 (`curl -fsS https://b2b.railtech.uz/health/`)
- [ ] SPA loads, no console errors, no raw `i18n.key.like.this` text on screen
- [ ] Switch RU ⇄ EN — labels translate, nothing shows a raw key

## 1. Auth (1 min)
- [ ] Log in as a known buyer user → lands on dashboard, no white screen
- [ ] Log out → returns to login
- [ ] (If testing registration) register a new email → verification email is
      received OR appears in `/admin/notifications/emaillog/`

## 2. Buyer — single RFQ (2 min)
- [ ] Create a deal / RFQ from the buyer workspace
- [ ] Add at least one line item (manually or from catalog)
- [ ] Open the RFQ to suppliers — stage shows `RFQ_OPEN`

## 3. Buyer — mass RFQ via Excel (2 min)  ← core value
- [ ] Upload an `.xlsx` with several rows on a deal
- [ ] Import task completes (watch `/admin/sourcing/importtask/` or the UI status)
- [ ] Quote items are created; Smart Match attached products where it could

## 4. Seller — bid (1 min)
- [ ] Log in as a seller with an operational subscription
- [ ] See the RFQ, submit a bid with prices
- [ ] (As buyer/manager) accept the bid → deal moves to `CALCULATING`

## 5. Quote (КП) lifecycle (2 min)
- [ ] Build/recalculate the quote → totals (subtotal, VAT, total) look correct
- [ ] Send КП to client → deal `QUOTE_SENT`, PDF downloads and renders
- [ ] As buyer, approve КП → deal `CONTRACT_SIGNED`

## 6. Contract → invoice → close (1 min)
- [ ] Contract generated from approved quote; double-sign (client + manager) → `SIGNED`
- [ ] Invoice generated; record payment → invoice `PAID`
- [ ] Fulfillment accepted → deal `CLOSED_WON`

## 7. Admin moderation (30s)
- [ ] Platform Admin can verify a company's KYC (button reacts, status updates)
- [ ] Admin force-approve a quote requires a reason and is logged in ActivityLog

## If anything fails
1. Note the step, the user/company, and the exact error (screenshot the console).
2. Check Sentry (once live) for the stack trace.
3. Reproduce in `test_golden_path.py` if it's a backend-flow break — add the
   failing case there so CI catches it next time.
4. Roll back by re-running the previous green deploy (or `git revert` + push).
