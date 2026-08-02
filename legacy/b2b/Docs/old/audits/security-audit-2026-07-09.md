# Аудит безопасности, конфиденциальности и утечки пользовательских данных — RailTech B2B

**Дата:** 2026-07-09 · **Ветка:** main @ `e52777f` (после #271) · **Метод:** мультиагентный аудит (9 направлений × finder → adversarial-верификация каждой находки → синтез; 38 агентов). READ-ONLY. Frontend включён.

**Итог:** 28 сырых находок → 23 прошли верификацию → **20 после дедупликации** (3 high, 6 medium, 4 low, 7 info). 16 CONFIRMED, 4 PLAUSIBLE.

## Общая оценка

RailTech's authentication, tenancy scoping on the standalone Quote endpoints, and cost-structure redaction primitives are individually well-built, but the platform's headline "hidden competition" confidentiality invariant (ADR-0003 §5) is broken on multiple secondary surfaces because the per-seller routing scope enforced on the canonical Quote read/write paths is not consistently replicated on deal-nested serializers, the contract-generation service, the chat/timeline channels, and the target-sellers field. The result is a cluster of cross-tenant and buyer-facing commercial-confidentiality leaks (rival КП totals, seller margin, FX cost-conversion rates, competitor identity, negotiation content) that let a co-routed or merely-subscribed seller reconstruct or read a competitor's crown-jewel pricing — the exact intel the marketplace monetizes hiding. A parallel theme is missing authorization binds on write/action paths (quote create, contract generate, stage transition) that skip the routing/KYC/capability checks their sibling paths enforce. No unauthenticated RCE, SQL injection, auth bypass, or cross-tenant PII-database breach was found; the highest-impact issues all require an authenticated, legitimately-onboarded seller or buyer and leak business-confidential (not personal) data. The remaining findings are lower-severity hardening gaps: user-enumeration inconsistency, an authenticated blind SSRF via unvalidated brand color, uncapped paid-AI spend, and several PII-at-rest / third-party-processor governance smells that contradict the project's own login_guard hashing policy.

## Системные темы

1. Routing scope enforced inconsistently across surfaces — the per-seller hidden-competition filter is correctly applied on the canonical QuoteViewSet but is NOT replicated on the deal-nested serializers (rank 2), the contract-generation service (rank 1), the chat/timeline channels (rank 4), or the target_sellers field (rank 5). The keystone ADR-0003 §5 invariant holds on the front door and leaks on every side door. 2) QuoteSerializer redaction denylist is incomplete — \_SELLER_ONLY_FIELDS pops only charges/charges_total at the Quote level, so margin_percent, fx_snapshot and fx_manual leak to the buyer (rank 3) and rival final-price fields leak to co-routed sellers (rank 2); the item-level serializer got its denylist right, the Quote-level one did not. 3) Write/action paths skip the authorization bind that read paths and sibling viewsets enforce — QuoteViewSet.perform_create (rank 6), generate_contract_from_quote (rank 1) and change_stage (rank 7) all omit seller_company_routed_to_deal even though QuoteItem/QuoteCharge create, sign_contract, generate_act and fulfillment all enforce it. 4) Business gates enforced in the primary flow are bypassable via parallel endpoints — change-stage sidesteps submit_request's KYC/capability/data-quality gates (rank 7), and compose/enrich sit entirely outside the FeatureKey entitlement + KYC tier model (rank 13). 5) Least-privilege breaks at the operator plane via permission-map fall-through — OperatorScoped degrades to pass-through for actions absent from operator_permissions (rank 8). 6) Enumeration handling is inconsistent — forgot-password is carefully neutral-200 but register is a deterministic oracle (rank 11) and forgot-password still has a timing side channel (rank 16). 7) PII-at-rest / third-party-processor governance gaps that contradict the project's own login_guard hashing policy — Sentry has no body scrubber (rank 12), the reset throttle stores plaintext email keys (rank 18), and AI ships unredacted counterparty PII abroad (rank 15). 8) Config/documentation drift — three CORS/CSRF env vars are documented but dead (rank 20), and dev CORS reflects any credentialed origin (rank 19).

## Находки (по убыванию severity)

### #1 — 🔴 HIGH · CONFIRMED

**generate_contract_from_quote lets any subscribed seller read/mutate any deal's contract (competitor pricing leak + dual-party notification spam)**

- **Файл:** `backend/crm/services/contracts.py:46` · _rbac-entitlements_
- **Эксплойт:** Seller B (any can_sell member of a KYC-L2+ SUPPLIER company with an operational subscription, never routed to the target deal) enumerates quote_id and POSTs /api/v1/crm/contracts/generate-from-quote {quote_id: N}. The service authorizes on is_seller + assert_seller_can_operate only and never calls seller_company_routed_to_deal, so it returns ContractSerializer(contract).data for competitor A's deal — including total_amount (A's winning КП total incl VAT), number, deal, quote, currency and signer identities. For an APPROVED quote it returns the existing winner's contract; for a SENT quote it CREATES one on the live deal, flips DRAFT→PENDING_CLIENT, re-enqueues a PDF render, and re-notifies BOTH real parties («требуется ваша подпись») on every call. Broadest-reach seller-side leak: attacker need not be co-routed.
- **Фикс:** Add a routing bind after loading the quote: require getattr(actor,'is_superuser',False) or seller_company_routed_to_deal(actor, quote.deal_id) else return MEMBER_REQUIRED_FOR_ACTION, mirroring sign_contract_by_manager (contracts.py:260-267). Stop returning full contract data to unrelated callers. Add a regression test asserting an unrouted subscribed seller is 403'd.

### #2 — 🔴 HIGH · CONFIRMED

**Deal detail/list nested quotes + active_quote + export-pdf are not per-seller scoped — a co-routed seller reads a rival's full КП (prices, totals, margin, PDF)**

- **Файл:** `backend/crm/views/deals.py:94` · _multitenancy-idor_
- **Эксплойт:** Buyer routes an RFQ to competing sellers A and B (two DealSellerRouting rows); both build separate Quote rows (prepared_by=self, version+1). DealViewSet.get_queryset (deals.py:94-102) prefetches ALL quotes with no prepared_by filter, and DealDetailSerializer.quotes/active_quote (serializers.py:536-537) + DealListSerializer.active_quote (492) serialize them — bypassing the per-seller filter QuoteViewSet.get_queryset (quotes.py:184-196) enforces. Seller B GET /api/v1/crm/deals/{id}/ (or the deals LIST via active_quote, or export-pdf streaming deal.active_quote.pdf_file, deals.py:525-552) receives A's total_incl_vat, subtotal_excl_vat, vat_amount, per-line final_price_excl_vat/discount_percent/lead_time_days, valid_until, delivery terms, КП number and PDF path — then undercuts. QuoteSerializer only redacts charges/charges_total here, not the final-price fields.
- **Фикс:** Scope the nested quotes exactly as QuoteViewSet.get_queryset does: build the Deal prefetch with a request-context Prefetch filtered to the viewer's own seller companies (or prepared_by IS NULL) for seller contexts, and gate DealDetailSerializer.active_quote/quotes and DealViewSet.export_pdf to the viewer's own prepared quotes. Add a regression test: seller A GET on a deal routed to A+B returns no quote whose prepared_by belongs to B.

### #3 — 🔴 HIGH · CONFIRMED

**QuoteSerializer under-redaction leaks seller margin_percent + FX cost-conversion rates to the buyer — reconstructs seller landed cost (defeats the cost-gate; re-opens the #269 leak on the JSON surface)**

- **Файл:** `backend/crm/serializers.py:426` · _pii-data-leakage_
- **Эксплойт:** QuoteSerializer.\_SELLER_ONLY_FIELDS = ("charges","charges_total") is the ONLY tuple popped by to_representation (443-449), but Meta.fields also includes margin_percent (383), fx_snapshot (379) and fx_manual (380). A buyer on their own deal calls GET /api/v1/crm/quotes/{id}/ or GET /api/v1/crm/deals/{id}/ (active_quote/quotes, incl. the seller's DRAFT КП). The response carries the whole-КП markup margin_percent (e.g. 22.00) and the frozen/negotiated FX rate map fx_snapshot={"USD":"12650"}/fx_manual. Combined with the already-visible per-line final_price_excl_vat and discount_percent, the buyer computes landed_cost = final_price / ((1+margin/100)(1−discount/100)) and divides UZS prices by the FX rate to recover the seller's foreign-currency procurement cost — the exact datum item-level redaction, economics gating, and the margin-free/FX-stripped PDF (PR #269) exist to hide. fx_manual is a договорной rate not derivable from public FX data.
- **Фикс:** Add margin_percent, fx_snapshot and fx_manual to QuoteSerializer.\_SELLER_ONLY_FIELDS so they are popped for non-cost-authorized viewers (mirroring QuoteItemSerializer.\_SELLER_ONLY_FIELDS, which already redacts item margin_percent). Add a buyer-GET test asserting these keys are absent from active_quote.

### #4 — 🟠 MEDIUM · CONFIRMED

**Competing sellers share one deal chat thread + timeline — buyer↔rival negotiation and КП events leak across co-routed sellers**

- **Файл:** `backend/crm/services/messaging.py:74` · _multitenancy-idor_
- **Эксплойт:** The Message model (crm/models/deals.py:211-235) has only deal+sender FKs — one shared thread per deal, no per-seller/routing dimension. On a deal routed to competing sellers A and B, user_can_access_deal_chat (messaging.py:74-101) grants any routed seller access and MessageViewSet.get_queryset (messages.py:56-58) returns all messages where deal_id ∈ seller_visible_deal_ids. Seller B GET /api/v1/crm/messages/?deal={id} (X-Active-Context: SELLER) reads every buyer↔A message and can POST into the thread A sees; notify_new_message even pushes an 80-char preview of A's messages to B's owner. TimelineView.\_deal_scope (timeline.py:91-101) reuses the same boundary, leaking A's КП-sent/accepted ActivityLog to B. Contradicts the DealSellerRouting docstring's «competing sellers are siloed (no cross-seller leak)». Distinct from the known billing-doc leak (#275).
- **Фикс:** Add a seller_company (routing) dimension to Message and scope send_deal_message + MessageViewSet.get_queryset and TimelineView.\_deal_scope so a routed seller sees only its own DealSellerRouting thread/timeline (buyer sees a thread per counterparty). If deal-level shared chat is genuinely intended for multi-seller deals, document it and correct the routing docstring/ADR.

### #5 — 🟠 MEDIUM · CONFIRMED

**target_sellers_data exposes every co-routed competitor's identity to each seller (hidden-competition break)**

- **Файл:** `backend/crm/serializers.py:508` · _pii-data-leakage_
- **Эксплойт:** DealListSerializer.get_target_sellers_data (508-510) and DealDetailSerializer.get_target_sellers_data (559-561) return [{id, name} for every seller in obj.target_sellers.all()] with no viewer gating. A seller routed to a deal (in seller_visible_deal_ids) calls GET /api/v1/crm/deals/ or /deals/{id}/ and receives the full list of all seller companies the buyer fanned the RFQ out to — learning exactly which competitors are bidding on the same заявка. Contradicts the code's own \_viewer_routing docstring («cross-seller identity leakage is structurally impossible») and the DealSellerRouting «Competition is HIDDEN» invariant; enables collusion signalling and targeted undercutting.
- **Фикс:** Gate target_sellers_data by viewer: return the full list only to the buyer company / platform admin; for a seller viewer return only their own company (or omit the field). Add a test exercising the co-routed-seller viewer path (test_ms_routing.py only covers the buyer view with single-seller routing).

### #6 — 🟠 MEDIUM · CONFIRMED

**QuoteViewSet.perform_create has no routing check — a seller injects a Quote onto any deal (writable deal FK, cross-tenant write)**

- **Файл:** `backend/crm/views/quotes.py:214` · _multitenancy-idor_
- **Эксплойт:** QuoteViewSet.perform_create (quotes.py:201-234) takes the target deal straight from the request body (deal = validated_data.get('deal')) — deal is a writable serializer field with default queryset Deal.objects.all() — and gates only on can_edit_quote_pricing(user), a platform-wide 'seller with quote.edit_pricing on ANY of their companies' test NOT bound to the deal. Unlike QuoteItemViewSet/QuoteChargeViewSet.perform_create (803/953), it never calls \_assert_seller_owns_quote_deal. A seller enumerates deal ids and POSTs /api/v1/crm/quotes/ {"deal": <victim_deal_id>, "quote_currency":"UZS"} for a deal their company was never routed to. Because version=max+1, the rogue empty quote becomes the deal's active_quote — the victim buyer's DealDetailSerializer.active_quote/total_value flips to total 0, and it pollutes the deal for legitimately-routed sellers. Repeatable platform-wide (integrity/DoS, not a read escalation).
- **Фикс:** In QuoteViewSet.perform_create, after resolving deal, call \_assert_seller_owns_quote_deal(self.request, deal) (or seller_company_routed_to_deal(user, deal.id)) before serializer.save(), mirroring the sibling viewsets; superuser bypass only.

### #7 — 🟠 MEDIUM · CONFIRMED

**change-stage FSM endpoint bypasses the KYC floor, can_buy capability and buyer/seller side gating (+ co-routed seller can kill a shared deal)**

- **Файл:** `backend/crm/views/deals.py:201` · _rbac-entitlements_
- **Эксплойт:** transition_deal_stage (crm/services/deals.py:90-183) blocks only is_platform_admin_viewer and validates the FSM matrix — NO can_buy/can_sell, NO KYC, NO buyer-vs-seller check. (a) An unverified (below-L2) buyer-company member builds a DRAFT deal + items, POSTs /crm/deals/{id}/route (also not KYC-gated) to attach seller routing rows, then POSTs /crm/deals/{id}/change-stage {stage_code:'RFQ_OPEN'} — a parallel path to submit_request that skips its four gates (KYC_REQUIRED_TO_SUBMIT, ONLY_BUYER_CAN_SUBMIT_REQUEST, ≥1/no-incomplete-line, ≥1-recipient), fanning the заявка to sellers below KYC L2. (b) On a multi-seller routed deal, losing seller B POSTs change-stage {stage_code:'CLOSED_LOST'} (valid from RFQ_OPEN/QUOTE_SENT), mutating the single global Deal.stage and killing the shared deal for winning seller A and the buyer — a hidden-competition griefing vector.
- **Фикс:** Gate change_stage in the service: enforce company_kyc_verified before leaving DRAFT into RFQ_OPEN/SOURCING, require is_member_of(deal.company_id, capability='buy') for buyer-driven transitions (or restrict to a documented forward set), and forbid a co-routed seller from mutating the shared deal stage.

### #8 — 🟠 MEDIUM · CONFIRMED

**Narrow platform operators (e.g. SUPPORT) can invite members, change roles and grant can_sell/can_buy on any company (OperatorScoped mapping gap)**

- **Файл:** `backend/accounts/views/company.py:122` · _rbac-entitlements_
- **Эксплойт:** CompanyViewSet.get_permissions routes team-management actions through [IsAuthenticated, OperatorScoped] for a platform operator, but invite/set_member_role/update_member_capabilities are absent from operator_permissions (company.py:79-89), so OperatorScoped.\_required_permission returns None and degrades to pass-through (any operator). The in-action guards (656-658, 713, 759) treat is_platform_admin as a full staff bypass. A least-privilege SUPPORT operator (OperatorRole granting only \*.view) POSTs /accounts/companies/{id}/update-member-capabilities {member_id, can_sell:true} (or set-member-role / invite) on an arbitrary tenant: OperatorScoped waves the unmapped action through and the guard treats them as staff, so a read-only operator invites users, reassigns workspace roles, and grants can_sell (handing a tenant member the cross-tenant seller queryset) — violating ADR-0004 G1 least-privilege. Only update/partial_update are correctly mapped to companies.manage.
- **Фикс:** Add explicit operator_permissions entries (e.g. companies.manage / users.manage) for invite/set_member_role/update_member_capabilities so OperatorScoped enforces a real sub-capability, or refuse operators outright on these member-only endpoints (only company members should reach team management).

### #9 — 🟠 MEDIUM · CONFIRMED

**Unvalidated brand accent_color → CSS injection into WeasyPrint → authenticated blind internal SSRF on every seller PDF render**

- **Файл:** `backend/crm/templates/crm/_document_base.html:36` · _injection-ssrf-files_
- **Эксплойт:** update_document_profile (accounts/services/document_profile.py:78) setattr's accent_color from raw request.data with no hex/format validation (only varchar(20) survives). document_brand_context passes it raw as accent, and \_document_base.html interpolates it into a <style> block (--accent: {{accent}};) and inline background attrs — Django autoescape does not neutralize CSS metachars ( ) : / . //. A company OWNER (or settings.edit holder) PATCHes /api/v1/accounts/companies/{id}/document-profile/ {"legal_name":"x","accent_color":"url(http://10.0.0.2)"} (exactly 20 chars). On the next render of ANY of that seller's documents (КП/contract/invoice/act — all extend the base and call HTML(string=...).write_pdf() with no url_fetcher/base_url), the WeasyPrint render in the PDF/Celery worker issues a server-side GET to the internal DB-VPS over WireGuard via the always-rendered .rule background. Empirically reproduced. Fits internal RFC1918/localhost shorthands (10.0.0.2, 10.0.0.3, 127.1); file:// LFI attempts and a fetcher-timeout worker-hang DoS also apply. Blind and length-limited.
- **Фикс:** 1) Validate accent_color to ^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$ in update_document_profile before persisting. 2) Render every WeasyPrint document with a custom url_fetcher that allowlists only local storage/same-origin asset paths and refuses file:// and non-allowlisted hosts. 3) Sanitize accent in document_brand_context (fall back to the default when it fails the hex pattern) to neutralize historical bad rows at render time.

### #10 — 🟡 LOW · PLAUSIBLE · **уже известно: PR #274**

**assign_role_to_member never-orphan guard misses the legacy OWNER (company_role IS NULL) — sole admin can be orphaned**

- **Файл:** `backend/accounts/services/roles.py:144` · _rbac-entitlements_
- **Эксплойт:** assign_role_to_member (roles.py:129-153) invokes its never-orphan block only when member.company_role_id and member.company_role.is_system, and \_is_sole_active_system_admin counts only is_system holders. A legacy OWNER whose admin rights come from the WorkspaceRole OWNER fallback with company_role IS NULL is neither guarded nor counted. Assigning that sole legacy OWNER a non-system CompanyRole («Наблюдатель») skips the guard AND drops them from \_admin_floor_q, leaving the company with zero admins able to manage KYC/billing/team. Sibling paths (remove_company_member/set_member_workspace_role/toggle_user_active) correctly use the unified \_admin_floor_q; only assign_role_to_member diverges. Reachability is unproven on a normally-migrated DB (migration 0030 backfilled all NULL members, HEAD e52777f); the only residual source is an operator add_company_member row minted in the 2026-06-30→2026-07-08 window before that path seeded company_role. Fix exists on unmerged branch (PR #274 / commit 2662fbd).
- **Фикс:** Replace the assign_role_to_member guard with the unified never-orphan floor (compute currently-admin and would-stay-admin via accounts.services.members.\_admin_floor_q / company_active_admins, exactly as set_member_workspace_role does) and block CANNOT_DEMOTE_LAST_COMPANY_ADMIN when the target is the sole floor-admin. Land PR #274.

### #11 — 🟡 LOW · CONFIRMED

**Registration endpoint is a user-existence oracle (400 vs 201) — contradicts the deliberate anti-enumeration on forgot-password**

- **Файл:** `backend/accounts/views/auth.py:82` · _authn-jwt-session_
- **Эксплойт:** create_pending_user (accounts/services/auth.py:63-64) returns USER_EMAIL_ALREADY_EXISTS when CustomUser.objects.filter(email=email).exists(), and RegisterView surfaces it as HTTP 400 {"detail":"USER_EMAIL_ALREADY_EXISTS"} (auth.py:82) versus HTTP 201 for a fresh email — a clean unauthenticated existence oracle. This contradicts ForgotPasswordView's neutral-200 anti-enumeration design. The register scope is throttled 5/hour per IP only (no per-email/global cap, counts both 201 and 400), so IP rotation yields a validated roster of which companies/individuals hold accounts for spear-phishing / credential-stuffing. A secondary defect: the check is case-sensitive (email=) vs the reset path's email\_\_iexact, permitting case-variant duplicate accounts.
- **Фикс:** Return a neutral success response for registration regardless of whether the email exists (always 201, and send an 'account already exists / reset your password' email out-of-band to an existing address), mirroring ForgotPasswordView. Normalize (trim+lowercase / iexact) the email before the existence check.

### #12 — 🟡 LOW · CONFIRMED

**Backend Sentry has no before_send scrubber — domain PII (INN, phone, bank requisites) in request bodies ships to the EU-region ingest on 500s**

- **Файл:** `backend/core/settings.py:861` · _secrets-config-logging_
- **Эксплойт:** sentry_sdk.init() sets send_default_pii=False (suppresses cookies/IP/user) but registers no before_send and no max_request_body_size override. The Django integration attaches the parsed request body (DRF's request.data) to every captured 500 unconditionally, and the default EventScrubber denylist matches only key names like password/secret/token — NOT this app's field names inn/stated_inn/bank_account/mfo/phone/legal_name/director. So an unhandled 500 in a KYC upload, company document-profile submit, or invoice/act/payment endpoint ships those PII values under request.data to the DE-region Sentry ingest (o<org>.ingest.de.sentry.io, whitelisted in the Caddy CSP), readable by anyone with Sentry project access and outside Uzbek data-residency assumptions. Triggers on genuine server errors; no attacker action required.
- **Фикс:** Add a before_send/before_send_transaction callback that strips request.data/body and extends the scrub denylist with domain PII keys (inn, phone, bank_account, iban, mfo, director, passport); or set request_bodies='never'/max_request_body_size='never' on the Django integration so bodies are never attached.

### #13 — 🟡 LOW · CONFIRMED

**Paid AI endpoints (compose/enrich) gated only by IsAuthenticated + 20/min throttle — no entitlement, KYC floor, or global AI-spend cap**

- **Файл:** `backend/sourcing/views_ai_conversational.py:61` · _ai-layer_
- **Эксплойт:** ComposeRequestView (fires TWO Claude calls) and ProductEnrichView are gated only by permission_classes=[IsAuthenticated] + the AI_IMPORT_ENABLED flag + a per-user ScopedRateThrottle of 20/min, and are absent from the FeatureKey/entitlement model — no per-company metering, no KYC/tier floor (a pre-KYC T0 account can call them with arbitrary text), and no global AI-spend circuit breaker (only the manual AI_IMPORT_ENABLED env flag). An attacker registers, verifies email, and scripts POST /api/v1/sourcing/compose-request/ + /api/v1/catalog/products/enrich/ at up to 20/min each (~60 paid opus-4-8 calls/min per account), multiplied by throwaway accounts (register throttle 5/hour/IP is IP-rotation-defeatable), running up the Anthropic bill indefinitely with no per-company ceiling. (chat_reply and quote_diff, by contrast, are properly gated by routing/deal-party checks and are not freely abusable.) Monetary/operational damage; no data exposure.
- **Фикс:** Meter compose/enrich against per-company entitlements/credits like ai.draft, add a KYC/tier floor consistent with the navigation tiers, and add a settings-driven global daily AI-spend circuit breaker that short-circuits paid calls when exceeded.

### #14 — ⚪ INFO · PLAUSIBLE

**Buyer-controlled request text can steer unattended AI product auto-bind into a seller's draft КП (confidence-only gate)**

- **Файл:** `backend/crm/services/draft_quote.py:131` · _ai-layer_
- **Эксплойт:** generate_draft_quote → \_resolve_ai_catalog_matches feeds the buyer's raw request-line fields (imported_raw_name/name_canonical/gost_drawing/mpn) into match_lines_to_catalog and auto-binds the top candidate into a new seller QuoteItem whenever the LLM-reported confidence ≥ AI_DRAFT_MATCH_CONFIDENCE (0.9) — the only gate is a number the model returns, influenceable by buyer text. A buyer crafts a line that trigram-matches an undesired product and embeds nudging text; a routed seller who clicks one-click generate-draft-КП gets it auto-bound and, if they send without reviewing, ships a КП for the wrong item. Heavily bounded: product_id is hard-validated against the per-line DB trigram shortlist (no arbitrary/foreign product injection), the bind lands only in the acting seller's own draft, the price comes from the seller's own SupplierOffers (not AI/buyer input), the structured-output schema + anti-overconfidence system prompt make confidence inflation unproven, and seller review before send is the real backstop. No cross-tenant data and no attacker-set price.
- **Фикс:** Treat model confidence as advisory, not an authorization gate: require the deterministic GOST/MPN exact match for true auto-bind, and surface fuzzy AI matches as pre-selected-but-unconfirmed suggestions the seller must accept. At minimum add an ai_auto_bound flag on the QuoteItem itself (currently only the separate AIMatchOutcome table records it) so review can't miss auto-bound lines.

### #15 — ⚪ INFO · PLAUSIBLE

**Confidential B2B data (chat text, names, full signed-contract/invoice PDFs incl. bank details & INN) sent to Anthropic with no redaction or consent flag**

- **Файл:** `backend/sourcing/services_ai_extract.py:155` · _ai-layer_
- **Эксплойт:** extract_document_fields (via file_to_payload) base64-encodes the ENTIRE uploaded signed contract / counter-invoice PDF — whose schema deliberately extracts bank_details (банк, р/с, МФО/SWIFT, ИНН) — and ships the raw bytes to Anthropic's vision API; suggest_chat_reply sends the last 20 chat messages verbatim plus sender full names and buyer company name. There is no consent surface, no field redaction, and no DPA/zero-retention gate; AI is enabled solely by ANTHROPIC_API_KEY + env flag. This is data the acting user is already authorized to see, so it is NOT a cross-tenant leak — it is a cross-border / third-party-processor governance exposure for an Uzbekistan B2B marketplace. No adversary, no privilege boundary crossed; a legal/data-residency posture item, not an exploitable bug.
- **Фикс:** Add an explicit consent surface for AI features, document Anthropic as a processor in the DPA/privacy policy, and confirm contractual zero-retention terms. Redact obviously-sensitive fields where feasible (note the vision path largely cannot pre-redact a scanned page, but the reconcile flow only needs totals/currency/date, not the bank/INN block).

### #16 — ⚪ INFO · CONFIRMED

**Password-reset neutral-200 defeated by a synchronous-SMTP timing side channel**

- **Файл:** `backend/accounts/services/auth.py:113` · _authn-jwt-session_
- **Эксплойт:** send_password_reset_email returns immediately for an unknown/inactive email (a few ms) but for an existing active user synchronously generates a token and BLOCKS on an in-request SMTP send (notifications/emails.py:176 message.send(fail_silently=False), no Celery/on_commit handoff). ForgotPasswordView always answers a neutral 200, so response latency re-introduces the account enumeration the neutral body was designed to prevent. Marginal: the register endpoint already yields the same account-existence fact deterministically in one request, and PasswordResetEmailThrottle caps samples to ~3/hour per target email, so the timing channel adds essentially no attacker capability. Mislabeled as DoS — it is an info-leak, and the synchronous SMTP is throttle-bounded, not a resource-exhaustion vector.
- **Фикс:** Dispatch the reset email off-thread (Celery task via transaction.on_commit, like the КП/quote emails) so the handler returns in constant time; optionally add a small constant latency floor.

### #17 — ⚪ INFO · PLAUSIBLE

**Public КП magic-link token never expires and has no revocation path**

- **Файл:** `backend/crm/services/quotes.py:745` · _public-unauth-dos_
- **Эксплойт:** The public КП token is minted once with secrets.token_urlsafe(32) (256-bit, strong) and reused idempotently across re-sends; it is rotated only by issuing a whole new Quote version — no TTL, no revoke action, and PublicQuoteView gates solely on frozen_at (ignores the already-computed valid_until and EXPIRED status). Anyone who later obtains the URL (buyer forwards the emailed link, edge/proxy access log, shared-computer browser history) can re-open the client-projection PDF — seller identity, buyer line items/quantities, КП number, final client pricing — indefinitely; the seller cannot invalidate a leaked link short of re-versioning. Exploitation is wholly gated on an out-of-band leak the app doesn't control; the token is unguessable and throttled 30/min, and the PDF carries no internal cost/margin data. No DoS (ARCH-03 renders off-thread). Mislabeled dimension.
- **Фикс:** Honor the existing valid_until in PublicQuoteView.get (bounded lifetime after frozen_at), and add an explicit revoke/rotate action on the Quote so a seller can invalidate a leaked link without re-versioning. At minimum document the link permanence.

### #18 — ⚪ INFO · CONFIRMED

**PasswordResetEmailThrottle stores the raw target email as a Redis cache key (PII at rest)**

- **Файл:** `backend/accounts/throttles.py:24` · _secrets-config-logging_
- **Эксплойт:** PasswordResetEmailThrottle.get*cache_key() builds the throttle key from the raw lowercased email (cache_format % {ident: email}), writing ':1:throttle_password_reset_email*<victim@email>' verbatim into the shared default Redis (DB 0) for the ~1h window. This contradicts the project's own login*guard, which sha256-hashes the email precisely to avoid PII-at-rest / key injection. An operator/insider with read access to the loopback-only Redis (or a Redis backup/dump) runs KEYS/SCAN 'throttle_password_reset_email*\*' and reads the plaintext addresses that recently requested a reset. Not remotely exploitable, not a DoS (mislabeled dimension); low-grade PII/behavioral-signal disclosure the login_guard design explicitly set out to avoid.
- **Фикс:** Hash the email before using it as the throttle cache key (reuse login_guard.\_identifier's sha256 approach) so the throttle keeps per-target semantics without storing plaintext PII.

### #19 — ⚪ INFO · CONFIRMED

**Dev CORS reflects any Origin with credentials (CORS_ALLOW_ALL_ORIGINS=DEBUG + CORS_ALLOW_CREDENTIALS=True)**

- **Файл:** `backend/core/settings.py:294` · _secrets-config-logging_
- **Эксплойт:** CORS_ALLOW_ALL_ORIGINS = DEBUG (294) with CORS_ALLOW_CREDENTIALS = True (295): under DEBUG, django-cors-headers reflects the request Origin into Access-Control-Allow-Origin and sets Access-Control-Allow-Credentials: true, so any website can make credentialed cross-origin XHR to the local dev API and read responses (including reading a fresh access token from a credentialed refresh, subject to SameSite). Correctly scoped OFF in production (DEBUG=False → explicit allowlist), so zero prod exposure; only local seed/demo data is at risk. A dev-hygiene smell.
- **Фикс:** Keep the explicit dev allowlist (localhost:5173 / 127.0.0.1:5173) even under DEBUG rather than CORS_ALLOW_ALL_ORIGINS=DEBUG, so credentialed CORS is never open to arbitrary origins.

### #20 — ⚪ INFO · CONFIRMED

**Documented CORS_ALLOWED_ORIGINS / CSRF_TRUSTED_ORIGINS / CORS_ALLOW_CREDENTIALS env vars are dead — hardcoded in settings, never read**

- **Файл:** `backend/core/settings.py:296` · _secrets-config-logging_
- **Эксплойт:** CORS*ALLOWED_ORIGINS (296-310), CORS_ALLOW_CREDENTIALS (295) and CSRF_TRUSTED_ORIGINS (322-332) are hardcoded Python literals; settings.py never reads these three names from env, yet .env.example advertises them as operator-tunable (lines 71/77/80) and prod .env is rendered from GitHub secrets. Not attacker-exploitable — the hardcoded allowlists are narrow railtech.uz domains — but it is false-confidence config drift: an incident responder who tries to lock CORS/CSRF down via the documented .env knobs finds the change silently ignored (only a code edit takes effect), delaying containment; a new domain rollout appears mysteriously CSRF-blocked. Same class as the already-deleted JWT*\* vars (DOC-02).
- **Фикс:** Either read these three settings from env (mirroring the ALLOWED_HOSTS pattern, with the current lists as defaults), or delete the misleading CORS/CSRF entries from .env.example so config documentation matches the code.

## Что проверено и выглядит надёжно

Several controls were verified as solid by the finders and are worth crediting: (1) The item-level cost-structure redaction works — QuoteItemSerializer and QuoteChargeSerializer correctly strip frozen_base_price, logistics_cost, customs_duty, item margin_percent, landed_cost and charge cost_amount via can_view_quote_costs_for for non-cost viewers (the Quote-LEVEL leak at rank 3 is the gap the item level got right). (2) The standalone QuoteViewSet/QuoteItemViewSet get_querysets correctly exclude a competitor's quotes (the audit-H1 hidden-competition filter) — the leaks are all on OTHER surfaces that failed to replicate it. (3) Most seller write/action paths DO bind routing: sign_contract_by_manager, generate_act, update_fulfillment_status, generate_draft_quote, claim/assign, and QuoteItem/QuoteCharge create all call seller_company_routed_to_deal / \_assert_seller_owns_quote_deal — only quote-create and contract-generate diverge. (4) The object permission (IsCompanyMemberOrPlatformAdmin) and seller_visible_deal_ids correctly scope deals to routed sellers / own company. (5) Never-orphan is unified across remove_company_member, set_member_workspace_role and toggle_user_active via \_admin_floor_q, and migration 0030 backfilled legacy NULL-role members (only assign_role_to_member diverges). (6) ForgotPasswordView implements a deliberate neutral-200 anti-enumeration response plus a per-target-email throttle. (7) login_guard sha256-hashes the email to avoid PII-at-rest — a good pattern the reset throttle failed to follow. (8) Sentry send_default_pii=False correctly suppresses cookies, client IP and authenticated-user identity. (9) The public КП token is cryptographically strong (256-bit token_urlsafe), throttled 30/min, and ARCH-03 renders WeasyPrint off-thread so the anonymous endpoint streams a pre-rendered file (no inline-render DoS). (10) The AI layer keeps LLM calls out of the request path (202 + polling), single-attempt paid jobs re-check entitlement before the paid call, and AI product auto-bind hard-validates product_id against the per-line DB trigram shortlist (no arbitrary/foreign product injection). (11) suggest_chat_reply and quote_diff are properly gated by routing/deal-party checks (unlike compose/enrich) with a TOCTOU re-check in the worker. (12) CORS_ALLOW_ALL_ORIGINS=DEBUG collapses off in production; GitHub Actions are SHA-pinned and CI security gates (pip-audit + npm audit) are hard. No unauthenticated RCE, SQLi, auth bypass, JWT-forgery, or cross-tenant PII-database breach was reported.

## Frontend (по отдельному запросу)

Направление frontend-security проверено полностью и вернулось **чистым**: access-токен живёт только в JS-модуле (`api/accessToken.ts`), НЕ в localStorage; refresh — только в HttpOnly-cookie; `authStore` персистит лишь `{isAuthenticated, role, user}` (без токенов); `queryClient.clear()` на login/logout (защита от кросс-тенант кэша на общем браузере); refresh-мьютекс. XSS-поверхность минимальна — единственный `dangerouslySetInnerHTML` (`components/ui/chart.tsx`) вставляет build-time CSS, не пользовательский ввод; srcDoc-iframe превью документа без `allow-scripts`. **Вывод: утечки конфиденциальности живут не во фронте, а в ответах backend-API** (#2, #3) — фронт их прячет в UI, но данные приходят и видны в DevTools/Network. Единственная фронт-заметка — свой профиль (email/phone/INN) в localStorage (info, стандартная практика, отклонено верификацией).

## Приоритет устранения

1. **Немедленно (HIGH, кросс-тенант/утечка коммерческой тайны):** #1 (routing-bind в `generate_contract_from_quote`), #2 (per-seller scoping вложенных quotes в Deal-сериализаторах + export-pdf), #3 (добавить `margin_percent`/`fx_snapshot`/`fx_manual` в `QuoteSerializer._SELLER_ONLY_FIELDS`).
2. **Затем MED:** #4 (сегрегация чата/таймлайна по продавцу), #5 (`target_sellers_data` только покупателю), #6 (routing-bind в `QuoteViewSet.perform_create`), #7 (KYC/capability-гейты в `change_stage`), #8 (operator_permissions для invite/set-role/capabilities), #9 (валидация `accent_color` + `url_fetcher` allowlist в WeasyPrint).
3. **Смержить открытые fix-PR:** #274, #275, #276 (main их всё ещё содержит).
4. **Hardening (low/info):** #11 (enumeration в register), #12 (Sentry before_send scrubber), #13 (entitlement/лимит на compose/enrich), #16-20.

---

_Сгенерировано мультиагентным аудитом (Claude Code). Каждая находка независимо верифицирована на текущем main. Файл-анкеры от `e52777f` — при правках перепроверять (Rule 6)._
