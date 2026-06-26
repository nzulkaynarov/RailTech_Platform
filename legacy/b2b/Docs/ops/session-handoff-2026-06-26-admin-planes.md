# Session handoff — 2026-06-26 — КП engine + Admin-planes program (cross-machine)

> **READ THIS FIRST on the new machine.** Claude Code memory is machine-local; this travels via
> `git pull`. The canonical architecture is **`Docs/adr/0004-three-admin-planes-core.md`** (the
> "core") + `Docs/adr/0002`/`0003` + `Docs/ops/rbac-roles-design-2026-06-25.md`. Anti-hallucination
> rule: **most things below ALREADY EXIST — verify before building; do NOT rebuild.**

## 0. FIRST ACTION on the new machine
1. `git pull origin main`. Then **merge the open PR `feat/phase3-access-matrix-g4`** (Phase 3/G4)
   if the owner hasn't — it's verified green (470 tests) but may not be in `main` yet. Check
   `git log --oneline origin/main | grep G4`.
2. `make up` + `make migrate`; re-provision local test accounts (below). Confirm health.
3. Read ADR-0004 + this doc. Then continue at **§5 (NEXT WORK = G1+G2 operator plane)**.

## 1. The program (how we got here)
Owner is the platform owner; he demands **world-standard, eyes-on product quality** (see memory-
equivalent feedback in ADRs). Arc this session: ruthless product audit → fixed the КП cost-engine
& flows → **multi-currency + delivery lead-times + ATP auto-split + optional multi-format export +
redesigned КП document** → then a strategic **admin-planes** program crystallised in **ADR-0004**,
building out the **tenant (Company-Admin) zone** (Phases 1–3). Next: the **operator zone** (G1/G2).

## 2. What is in `main` (MERGED — do NOT redo)
- **КП cost-engine F3.8**: per-line = себестоимость (base + customs, in the line cost currency
  converted to UZS); **margin is КП-LEVEL** (`Quote.margin_percent`); freight/insurance/etc are
  document-level `QuoteCharge`; Incoterm basis auto-applies global `ChargeTemplate`s incl. FREIGHT
  (mig `crm/0038`). No per-line «Логистика»/«Маржа»/«Скидка» columns.
- **Multi-currency**: presentation = UZS (`Quote.quote_currency`); per-line cost currency
  (`QuoteItem.frozen_currency`); frozen FX snapshot (`Quote.fx_snapshot`) + manual override
  (`Quote.fx_manual`); platform FX foundation `master_data/fx.py` + `ExchangeRate` model + **CBU
  (cbu.uz) Celery-beat daily fetch** (`refresh_exchange_rates`). `convert_to_uzs`, manual wins.
- **Delivery lead times**: `QuoteItem.lead_time_days` (sourced from `SupplierOffer`) +
  `Quote.delivery_lead_time_days` (effective = max of lines). **ATP auto-split** on
  `submit_for_review` (`crm/services/availability.py` — 40 units, 14 in stock → 14@3d + 26@30d).
  `SupplierOffer.stock_quantity / in_stock_lead_time_days / order_lead_time_days`.
- **Export** is an OPTION (not a forced/auto PDF — owner directive): `crm/services/exporters.py`
  `export_quote(quote, fmt, include_costs)` → PDF|XLSX|CSV; `GET /api/v1/crm/quotes/<id>/export/?format=`;
  React `components/Shared/ExportMenu.tsx`. **Redesigned** `crm/templates/crm/quote_pdf.html`.
- **ADR-0004** (the admin-planes canon).
- **Phase 1 (tenant)**: platform **email templates** file→DB (`notifications.EmailTemplate`,
  send DB-first/file-fallback, `EmailTemplateViewSet` + preview/test-send, React
  `AdminEmailTemplatesPage`); **company document profile** (`accounts.CompanyDocumentProfile` —
  logo/legal_name/inn/address/bank/signatory/footer) wired into `quote_pdf.html` (the «Поставщик»
  block + footer are now data-driven — the hardcoded "RailTech B2B" is gone; platform fallback when empty).
- **Phase 2 (tenant)**: `accounts.CompanySettings` (КП defaults: default_delivery_basis /
  cost_currency / vat_rate / margin_percent / offer_validity_days + `doc_number_prefix`) inherited
  on new-quote create; **per-company document numbering** (`DocumentSequence` + `company` FK,
  `next_document_number(doc_type, label, company=None)` → prefixed company gets ACME-КП-2026-00001
  own counter, prefix-less + platform share the platform counter so the global `number` unique
  never collides); **«Настройки компании» hub** (`SettingsPage` tabs: Профиль документов / Дефолты
  КП / Нумерация / Шаблоны расходов / Команда).

## 3. Open PR — MERGE FIRST: `feat/phase3-access-matrix-g4` (Phase 3 / G4)
Verified green (470 backend tests, tsc, i18n). Finished the **Company-Admin access matrix**
(Role+Permission-set — the engine pre-existed): `accounts.CompanyRole` (per-company name +
`permissions` JSON + `is_system`), `accounts.constants.Permission` catalog (14 codes, 5 groups),
`member_has_permission`, `CompanyRoleViewSet` + `PermissionCatalogView`, mig `accounts/0023` seeds
5 templates + maps members. **Gaps it closed**: never-orphan on role REASSIGN
(`CANNOT_DEMOTE_LAST_COMPANY_ADMIN` 409); cost/margin redaction keyed on `quote.view_cost_margin`;
perm-i18n bug (dotted codes never localized → dots→underscores). UI «Команда и доступы» (roles +
grouped checkboxes + member role dropdown) **replaces the Buy/Sell toggles**.
**→ TENANT ZONE (G3+G4) IS COMPLETE.**

## 4. ⛔ Do NOT rebuild (these EXIST)
`Quote.margin_percent`, `fx_snapshot`/`fx_manual`, `cost_currency_default`, `delivery_lead_time_days`;
`ExchangeRate` + `master_data/fx.py`; `SupplierOffer` stock/lead fields; `crm/services/availability.py`;
`crm/services/exporters.py` + ExportMenu; `notifications.EmailTemplate`; `accounts.CompanyDocumentProfile`;
`accounts.CompanySettings`; per-company `DocumentSequence`/`next_document_number`; `accounts.CompanyRole`
+ `Permission` + `member_has_permission` + `CompanyRoleViewSet`/`PermissionCatalogView`. **Grep first.**

## 5. NEXT WORK — Operator plane: G1 + G2 (ADR-0004 roadmap)
The Platform **Operator** (`SystemRole.ADMIN`, React `PlatformAdminShell`, `ADMIN_VIEWER_CANNOT_ACT`)
is currently a **monolith** — one all-powerful ADMIN. Two gaps to close:
- **G1 — granular operator sub-roles (least privilege).** Target presets: SUPPORT, KYC_OFFICER,
  BILLING_OPERATOR, MODERATOR, SUPER_OPERATOR. Gate the operator endpoints by sub-capability:
  KYC actions (KYC_OFFICER), subscriptions/payments (BILLING_OPERATOR), role-application/content
  moderation + force-overrides (MODERATOR/SUPER_OPERATOR), users/companies (SUPER_OPERATOR).
  Likely an `OperatorRole`/capability set on the ADMIN user (mirror the tenant Permission pattern
  but PLATFORM-scoped, NOT a CompanyRole). Keep a single SUPER_OPERATOR = today's full ADMIN
  (backward compatible). Re-key the `IsPlatformAdmin`-gated viewsets onto sub-capabilities.
- **G2 — audited break-glass.** When an operator reads a tenant's PRIVATE trade data (deals/
  quotes for a force-override), require + log a **reason**, who/when/which entity, time-boxed —
  layered on the existing `ActivityLog` (entity-scoped). A "break-glass" record + an admin audit view.
**Suggested approach (proven this session):** ONE multi-agent Workflow, phase Backend (operator
capability model + gating + break-glass logging + tests) → phase Frontend (operator-role admin UI +
break-glass reason prompt). Then VERIFY yourself (esp. security: a SUPPORT operator cannot do KYC;
break-glass is logged). Confirm operator-role composition with the owner first if unsure.

## 6. Remaining after G1/G2
- **G5** — designated billing/legal "primary" per company (above never-orphan).
- **G6** — Platform Engineer (Unfold/superuser) access logging / least-privilege (break-glass for
  emergency Unfold fixes).
- Deferred product items: full schedule-lines (line tranches) for partial availability (ATP lite
  ships now via line-split); per-company numbering already done; per-seller branded EMAILS (today
  email templates are platform-level — a future tenant-vs-platform call).

## 7. The working rhythm (replicate it)
- **Multi-agent Workflow** per phase: backend core first, then frontend; agents return their
  **i18n keys in the structured output (`i18nKeys`) — they do NOT write ru/en.json** (avoids the
  parallel JSON write-race); the **integrator (you) merges the keys** into both locales, nested by
  dots, then runs i18n-symmetry. Disjoint file buckets; shared files = single writer.
- **VERIFY YOURSELF — agents over-report.** Per wave: `makemigrations --check`; full backend suite
  `docker compose exec -T backend python -m pytest -q -p no:cacheprovider --create-db`; tsc
  `docker run --rm -v "$PWD":/work -w /work node:22 bash -lc 'cd frontend && npm ci >/dev/null 2>&1; ./node_modules/.bin/tsc -b'`
  (npm ci REQUIRED — a bare `npx tsc` fails "no compiler"); `python3 scripts/check_i18n_symmetry.py`;
  **eyes-on**: render the КП PDF via `export_quote` and Read the PDF; browser walks via
  `frontend/e2e/run-in-docker.sh <spec> --workers=1` (PW_VERSION=v1.61.0-jammy, rebuild frontend first).
- Commit per phase, push a PR; the **owner merges between phases**; then continue on fresh `main`.

## 8. Gotchas / hard-won lessons
- **Numbering is a prod-500 hot path** — `DocumentSequence` is race-safe (`select_for_update`) and
  the global `number` unique can collide if a counter is un-backfilled; the per-company design keeps
  prefix-less companies on the SHARED platform counter so they can't collide. Don't break this.
- **Daphne does NOT auto-reload** — `docker compose restart backend` after .py edits. **Celery
  worker** holds stale models — restart it after model changes too.
- `pytest --create-db` can race a concurrent test DB session → use `--reuse-db` on retry.
- Eyes-on > tests: render documents and LOOK; the owner stumbles on small things tests miss.

## 9. Local setup (machine-local — recreate)
Local Postgres via `docker-compose.override.yml` (`db` service, sslmode=disable). Accounts (pw
`Test1234!`): `buyer.local@railtech.uz`, `seller.local@railtech.uz` (SUPPLIER+CLIENT → defaults to
BUYER context; switch the sidebar to Seller for the КП builder), `admin@railtech.uz` (Platform
Operator). `seller.local` company gets the `ООО Тест Продавец` profile + ACME numbering prefix from
this session's smokes (dev data, harmless). AI needs `ANTHROPIC_API_KEY`; FX needs no key (CBU public).
Prod: app-VPS `176.101.56.141` (root SSH, Unfold/Caddy/Docker), DB-VPS `10.0.0.2` (WireGuard).
