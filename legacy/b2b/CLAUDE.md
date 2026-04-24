# RailTech B2B SaaS — Claude Code Context

## Project Overview

B2B marketplace for railway equipment (Uzbekistan). Monorepo: Django backend + React frontend + Docker infrastructure.

**Domain:** Railway machinery, general goods, services — procurement, quoting, CRM.

## Tech Stack

- **Backend:** Django 6.0, DRF, Daphne (ASGI), Channels (WebSocket), Celery + Redis, PostgreSQL (Neon Cloud)
- **Frontend:** React 18, TypeScript 5.6, Vite 7, Tailwind CSS 4, shadcn/ui, Zustand 5, React Query 5, i18next (RU/EN)
- **Infra:** Docker Compose (dev), Nginx (prod), MinIO (S3), GitHub Actions CI
- **Auth:** JWT (simplejwt) — access 30min, refresh 7d, rotation enabled
- **PDF:** WeasyPrint
- **Excel:** pandas + openpyxl

## Project Structure

```
backend/                    # Django project
  core/                     # Settings, URLs, ASGI, Celery, middleware, permissions
  accounts/                 # CustomUser, Company, CompanyMember, KYC, Subscriptions
  catalog/                  # Product (PIM), Category, EquipmentGroup, SupplierOffer
  crm/                      # Deal, Quote, QuoteItem, Message, Lead, ActivityLog
  sourcing/                 # Attachment, ImportTask, DomainKeyword, Excel import tasks
  master_data/              # AbstractLookup, Country, Currency, UOM, DeliveryBasis
  notifications/            # Notification, NotificationType
  */services.py             # Business logic layer (accounts, catalog, crm, notifications, sourcing)
frontend/                   # React app
  src/api/                  # Axios client with JWT interceptor + refresh mutex
  src/store/                # 10 Zustand stores (auth, user, cart, flow, task, theme, currency, domain, demo, loading)
  src/pages/                # Dashboard, Deals, Quotes, Products, KYC, Subscriptions, Settings, Sourcing, Analytics, etc.
  src/components/           # shadcn/ui (64 components), Admin, Catalog, Sourcing, Dashboard, Auth, Cabinet, Layout, Shared
  src/components/Layout/    # AdminShell, ClientShell, ManagerShell, CatalogShell
  src/hooks/                # useAccounts, useCatalog, useCRM, useMasterData, useSystemSettings, usePageStats, use-mobile
  src/i18n/locales/         # ru.json, en.json
  src/layouts/              # AppShell (main SPA shell with shadcn Sidebar)
nginx/                      # Production nginx.conf (rate limiting, caching, WebSocket)
docs/                       # Architecture, specs, roadmap, ADRs, audits, WebSocket docs
Docs/                       # Mockups, presentations, UI audit (legacy path)
```

## Key Architecture Decisions

- **Hybrid routing** — auth routes (`/`, `/register`, `/setup-password`) via `useAuthRoute()` hook in App.tsx; AppShell uses hash-based SPA navigation; AdminShell/ClientShell/ManagerShell use React Router
- **B2B Multi-tenancy** — via `CompanyMember` join table, not schema/DB isolation
- **Deal FSM** — DRAFT → KYC_PENDING → SOURCING → CALCULATING → QUOTE_SENT → CONTRACT_SIGNED → CLOSED_WON/CLOSED_LOST
- **Dual Redis** — redis:6379 (Channels/WebSocket), redis-celery:6380 (Celery broker+results)
- **Dual Storage** — MinIO (public/private/temp buckets) with local filesystem fallback
- **Financial precision** — `decimal.js` on frontend, `DecimalField` on backend, `QuoteItemHistory` audit trail
- **Auth model** — `CustomUser` with email as USERNAME_FIELD, `SystemRole` FK for RBAC
- **Company types** — `CompanyType` M2M on Company (CLIENT=Buyer, MANUFACTURER, SUPPLIER=Seller); returned in `/me/` as `company_types[]`
- **Frontend role mapping** — `loadFromAuth()` maps backend CompanyType codes to frontend CompanyStatus (CLIENT→BUYER, SUPPLIER→SELLER, MANUFACTURER→MANUFACTURER)
- **4 Shell layouts** — all use shadcn `<Sidebar>` with `collapsible="icon"`:
  - `AppShell` (hash-based SPA, Buyer/Seller/Manufacturer context switcher)
  - `AdminShell` (React Router, `/admin/*`)
  - `ClientShell` (React Router, `/cabinet/*`)
  - `ManagerShell` (React Router, `/crm/*`)
  - `CatalogShell` (public catalog, top navbar only — no sidebar)
- **Unified shell layout** — all shells use `p-6` content padding, `h-14` header, `<SidebarTrigger>` for mobile

## Database

- **External:** Neon Cloud PostgreSQL (no local postgres in docker-compose)
- **Connection:** `DATABASE_URL` env var parsed via `urlparse`, fallback to individual `POSTGRES_*` vars
- **Auth user:** `accounts.CustomUser` (email login)

## API Surface (prefix: `/api/v1/`)

- `auth/` — register, setup-password, submit-profile, token, token/refresh
- `accounts/` — companies (verify-kyc, upload-document, team, invite), users, me
- `catalog/` — products, offers, equipment-groups, categories, manufacturers
- `crm/` — deals (change-stage), quotes (generate-pdf, send-to-client, approve), quote-items, messages, activity-logs, analytics, leads
- `sourcing/` — requests, import-deal/{id}, import-catalog, import-status/{task_id}
- `master-data/` — countries, currencies, units, delivery-basis
- `notifications/` — CRUD + mark as read
- `health/` — health check (also at root `/health/`)

## Celery Tasks

- `sourcing.tasks.process_excel_import` — Parse Excel for deal, Smart Match, create QuoteItems (queues: default, pdf, imports)
- `sourcing.tasks.process_catalog_import` — Bulk import products to PIM catalog
- Celery Beat — `django_celery_beat.schedulers:DatabaseScheduler`

## Environment

- Config via `.env` file (loaded by python-dotenv from `BASE_DIR.parent/.env`)
- Key vars: `DATABASE_URL`, `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `REDIS_URL`, `CELERY_BROKER_URL`, `MINIO_*`, `VITE_API_URL`, `VITE_WS_URL`
- Frontend: build-time env via Vite `import.meta.env` (baked into production build)

## First-Time Setup

```bash
git clone git@github.com:nzulkaynarov/RailTech_SaaS_B2B.git && cd RailTech_SaaS_B2B
cp .env.example .env        # заполнить DATABASE_URL, DJANGO_SECRET_KEY, SUPERADMIN_PASSWORD, MINIO_SECRET_KEY
make up                      # собрать и поднять все контейнеры (~1-3 мин)
make migrate                 # применить миграции
make seed                    # загрузить справочники (валюты, роли, статусы)
docker compose exec backend python manage.py init_superadmin   # создать суперадмина из .env
```

Superadmin credentials: `SUPERADMIN_EMAIL` / `SUPERADMIN_PASSWORD` from `.env` (default email: `admin@railtech.uz`).
Command `init_superadmin` reads these env vars, creates user with `is_active=True, is_staff=True, is_superuser=True`.

## Docker Services (dev)

| Service | Container | Port | Purpose | Health Check |
|---------|-----------|------|---------|-------------|
| backend | railtech_backend | 8000 | Django/Daphne ASGI, REST API, WebSocket | `curl /health/` |
| frontend | railtech_frontend | 5173 | React SPA (prod build via nginx) | `wget /health` |
| redis | railtech_redis_channels | 6379 | Django Channels (WebSocket) | `redis-cli ping` |
| redis-celery | railtech_redis_celery | 6380 | Celery broker + result backend | `redis-cli ping` |
| minio | railtech_minio | 9000, 9001 | S3-compatible object storage | `curl /minio/health/live` |
| minio-init | railtech_minio_init | — | Bucket creation (runs once, exits) | — |
| celery-worker | railtech_celery_worker | — | Async tasks: Excel import, PDF gen | `celery inspect ping` |
| celery-beat | railtech_celery_beat | — | Scheduled tasks (DatabaseScheduler) | — |

## Web UI Endpoints (dev)

| Service | URL |
|---------|-----|
| Frontend (SPA) | http://localhost:5173 |
| Backend API | http://localhost:8000/api/v1/ |
| Swagger UI (API docs) | http://localhost:8000/api/docs/ |
| ReDoc (API docs) | http://localhost:8000/api/redoc/ |
| Django Admin (Unfold) | http://localhost:8000/admin/ |
| MinIO Console | http://localhost:9001 |
| Health Check | http://localhost:8000/health/ |

## Service Verification Commands

```bash
docker compose ps                                              # status of all containers
curl http://localhost:8000/health/                             # backend + DB health
docker compose exec redis redis-cli ping                       # Redis Channels
docker compose exec redis-celery redis-cli ping                # Redis Celery
docker compose exec celery-worker celery -A core inspect ping  # Celery worker
```

## Commands

```bash
make up                  # docker compose up -d --build
make down                # stop all
make logs                # follow logs
make migrate             # run migrations
make makemigrations      # create migrations
make seed                # loaddata seed_data
make createsuperuser     # interactive superuser creation
make test                # pytest
make test-backend        # pytest with coverage
make test-frontend       # vitest
make lint                # flake8 + black + isort + eslint
make format              # black + isort
make security            # pip audit + npm audit
make shell               # backend bash
make frontend-shell      # frontend bash
make celery-logs         # celery worker logs
make collectstatic       # django collectstatic
make clean               # remove all containers, volumes, cache (DESTRUCTIVE)
```

## Coding Conventions

- **Python:** black (120 line length), isort (profile=black), flake8; target Python 3.11
- **TypeScript:** strict mode, ESLint, path alias `@/` → `src/`
- **Styling:** Tailwind v4 utility-first, oklch color tokens, CSS variables, dark mode via `.dark` class
- **Models:** `AbstractLookup` base for reference tables (code, name, sort_order, is_active)
- **Serializers:** Nested read, flat write pattern; `_data` suffix for nested representations
- **i18n:** All UI text via `useTranslation()`, keys in `ru.json`/`en.json`
- **State:** Zustand stores with `persist` middleware for auth/theme; no Redux
- **UI:** Only shadcn/ui components + Tailwind semantic tokens. No custom CSS, no hardcoded hex colors, no `text-white`/`text-black` — use `text-foreground`/`text-primary-foreground`
- **Text sizes:** Only Tailwind scale (`text-xs`, `text-sm`, `text-base`, etc.) — NEVER `text-[9px]`, `text-[11px]` or arbitrary pixel values
- **Chart colors:** Use `bg-[var(--color-chart-N)]` for dynamic chart legend dots — this is the correct Tailwind pattern for CSS variable colors. NEVER use inline `style={{ backgroundColor }}` for chart legends
- **Sidebar:** ALL shell layouts must use shadcn `<Sidebar>` + `<SidebarProvider>` + `<SidebarInset>` — NEVER custom `<aside>` with manual collapse state
- **Zod validation messages:** For i18n, use factory pattern: `const createSchema = (t: TFn) => z.object(...)` — call inside component where `t()` is available

## Testing

- **Backend:** pytest + pytest-django, markers: slow, integration, unit; coverage threshold: 50%
- **Frontend:** vitest + @testing-library/react + jsdom
- **CI:** GitHub Actions — 6 jobs (backend-lint, backend-test, frontend-lint, frontend-build, docker-build, security)

## Auth Flow (production)

1. User opens app → `LoginPage` (or `/register` → `KYCRegistrationForm`)
2. Registration: `POST /api/v1/auth/register/` → creates `CustomUser(is_active=False)` + sends email
3. In DEBUG mode, email prints to **backend container logs** (`docker compose logs backend`). **Every email (DEBUG and prod) is also persisted in `EmailLog`** — view at `/admin/notifications/emaillog/` (Unfold → Аудит и мониторинг → Журнал email). Search by user email, filter by template / channel / status (SENT/FAILED)
4. User clicks link `/setup-password?uid=...&token=...` → `PasswordSetupPage` → sets password → `is_active=True`
5. Admin approves company via Django admin at `/admin/` (Unfold UI) → action "Подтвердить KYC (L2)"
6. User logs in with JWT → `LoginPage` → main app

**Email delivery** (as of 2026-04-23):

- Single entry point: `notifications.emails.send_templated_email(template, context, to, channel, user)`
- Three channels in `settings.EMAIL_CHANNELS`: `transactional` (registration/KYC/invites), `marketing` (reserved), `system` (ops alerts). Each channel can have own SMTP/ESP via `EMAIL_TX_* / EMAIL_MKT_* / EMAIL_SYS_*` env vars; default = single SMTP from block 7 of `.env.example`
- Templates: `backend/templates/emails/{name}.{html,txt,_subject.txt}` — edit text/styling without touching code. Current templates: `setup_password`, `invite_member`, `kyc_verified`, `role_application_approved`, `role_application_rejected`, `reset_password`

**Superadmin account:**
- Created via `python manage.py init_superadmin` using `SUPERADMIN_EMAIL` / `SUPERADMIN_PASSWORD` from `.env`
- Default email: `admin@railtech.uz`, password: set in `.env`
- NOT auto-created — must run the command manually after `make migrate` + `make seed`

## IRON RULES — VIOLATION PROHIBITED

### Rule 1: No fake data
- NEVER create mock data, static arrays, or fake API responses in production code
- EVERY endpoint MUST query the real database via Django ORM
- If test data is needed — use management commands (`core_seed`, `seed_demo`), not hardcode
- **Seed = data migrations.** Business lookup rows (SystemRole.ADMIN, DealStage.RFQ_OPEN, VerificationStatus.L2_VERIFIED, etc.) are created via `migrations.RunPython` with `get_or_create` and a reverse no-op. `loaddata` fixtures and management commands are **dev/demo-only**, not the source of truth for business codes. After `migrate` on a fresh DB, every code referenced by `services.py` / FSM / permissions MUST already exist. Any `Model.objects.get_or_create(code=...)` in hot paths (views, services, smoke scripts) is a violation — replace with `Model.objects.get(code=...)` that raises a clear error if the migration was not applied.

### Rule 2: No hardcoded values
- URLs, keys, secrets, IDs — ONLY from environment variables (.env)
- Business constants (limits, prices, settings) — ONLY from DB or config
- Roles, statuses, enum values — compare by `code` field (e.g., `stage_code === 'DRAFT'`), NEVER by translated `name`

### Rule 3: Strict naming
- JS/TS variables and functions: camelCase
- JS/TS classes and types: PascalCase
- API endpoints: kebab-case, plural nouns
- DB tables and columns: snake_case (Django convention)
- Environment variables: UPPER_SNAKE_CASE
- Boolean fields: `is_`/`has_` prefix in DB

### Rule 4: Only shadcn/ui + semantic tokens
- ONLY use components from `@/components/ui/` (shadcn/ui)
- Colors: `bg-primary`, `text-foreground`, `bg-success`, `bg-warning`, `bg-destructive`, `bg-info` — NEVER `bg-emerald-500`, `text-white`, `bg-amber-*`, `bg-red-600`
- Text sizes: ONLY Tailwind scale (`text-xs` minimum) — NEVER `text-[9px]`, `text-[8px]`, `text-[11px]`
- No custom CSS, no inline styles for static values, no `blur-[120px]` decorative hacks
- Chart colors: use `bg-[var(--color-chart-N)]` Tailwind classes, NOT inline `style={{ backgroundColor }}`
- Sidebar: use shadcn `<Sidebar>` primitives, NOT custom `<aside>` elements

### Rule 5: All text via i18n
- ALL user-facing text wrapped in `t()` from `useTranslation()`
- Labels stored in `frontend/src/i18n/locales/ru.json` and `en.json`
- Store files (Zustand) hold i18n KEYS, not raw text — translate in components

### Rule 6: Always read before writing
- ALWAYS read the file with Read tool before editing
- ALWAYS check that imports exist, types are correct, fields match DB schema
- NEVER assume file contents or code structure

### Rule 7: Frontend-backend sync
- Every frontend feature must call a real backend API endpoint
- `userStore.loadFromAuth()` maps backend CompanyType → frontend CompanyStatus
- Use `stage_code` (DB code) for logic, `stage_name` only for display

### Rule 8: Business logic lives in services.py only

- ALL business logic (state transitions, validations, side effects, email sends, Celery dispatches, multi-model updates) MUST live in `<app>/services.py` as plain functions
- `admin.py` actions and `views.py` ViewSets are THIN WRAPPERS — they only:
  1. Authorize the request
  2. Validate input (via DRF serializer or admin form)
  3. Call ONE service function
  4. Return / display the result
- NEVER duplicate logic between `admin.py` action and `views.py` endpoint — both call the same service
- NEVER put `Model.objects.update(...)`, status changes, or notifications inline in admin actions — extract to service first
- See `Docs/adr/0001-admin-separation.md` for the full rationale (Django Unfold = engineers; React Admin = business users)

**Wrong:**
```python
@admin.action
def verify_kyc(self, request, queryset):
    for c in queryset:
        c.verification_status = VerificationStatus.objects.get(code='L2_VERIFIED')
        c.save()
        send_mail("Verified", ...)  # ← business logic in admin
```

**Right:**
```python
# accounts/services.py
def verify_company_kyc(company, approver, level_code):
    company.verification_status = VerificationStatus.objects.get(code=level_code)
    company.save(update_fields=['verification_status'])
    send_kyc_notification(company, approver)
    return company

# accounts/admin.py
@admin.action(description="Подтвердить KYC (L2)")
def verify_kyc_action(self, request, queryset):
    for c in queryset:
        services.verify_company_kyc(c, request.user, 'L2_VERIFIED')

# accounts/views.py
@action(detail=True, methods=['post'])
def verify_kyc(self, request, pk=None):
    services.verify_company_kyc(self.get_object(), request.user, request.data['level'])
```

### Admin separation — where to add new features

- **New business features → React Admin** (`/admin/*` in SPA). Django Unfold is for engineers only.
- Unfold is reserved for: master data CRUD (lookups), read-only audit inspection, Celery beat schedule, Django auth groups, emergency data fixes by DBA.
- Adding a new `@admin.action` with business logic? STOP — implement it as a React page + DRF endpoint instead. The action can come later as a thin wrapper if engineers need it.

## Role Responsibilities (ADR-0002)

Canonical source: `Docs/adr/0002-role-responsibilities.md`. Quick reference when planning a feature — pick the right layer first.

**Three layers (not interchangeable):**
- **SystemRole** on `CustomUser.role` — only `ADMIN` (Platform Admin, no memberships) and `USER` (everyone else). Enforced by `accounts/migrations/0010_platform_admin_model`.
- **WorkspaceRole** on `CompanyMember.role` — `OWNER`, `SALES_MANAGER`, `LOGIST`, `CONTRACT_MANAGER`, `FOREIGN_TRADE_SPECIALIST`, `PROCUREMENT_MANAGER`, `BUYER_MANAGER`. Each is restricted to matching CompanyType via `applicable_to_types`.
- **Per-member capabilities** on `CompanyMember.can_sell` / `can_buy` — distributed by `OWNER`.

| Layer | Tool | Owns | Does NOT |
|---|---|---|---|
| **Platform Engineer** (`is_superuser=True`) | Unfold + terminal | Deploy, migrations, master data CRUD, Celery Beat, emergency fixes, `init_superadmin` | Business operations on behalf of companies |
| **Platform Admin** (`SystemRole.ADMIN`, no memberships) | `PlatformAdminShell` in SPA | Users / Companies / KYC L1→L2→L3 / Subscriptions / Role applications / Force-change Deal stage / Force-approve Quote / Force-cancel Contract | Becoming a `CompanyMember`. Buy / sell / sign / pay / bid from any company — backend returns `ADMIN_VIEWER_CANNOT_ACT` |
| **SUPPLIER / MANUFACTURER team** (`SystemRole.USER` + WorkspaceRole in SUPPLIER/MFG) | `AppShell` SELLER context | Submit SupplierBid, build / send Quote, sign contracts, update fulfillment, sales analytics (only with `can_sell`) | Operations on other companies; platform moderation |
| **CLIENT team** (`SystemRole.USER` + WorkspaceRole in CLIENT) | `AppShell` BUYER context | Open RFQ, import Excel, accept / reject SupplierBid, sign contract as buyer, record payment, acceptance (only with `can_buy`) | Operations on other companies; seller-side actions |

**Escalation path:** company member → company OWNER → Platform Admin → Platform Engineer. Don't escalate to Platform Engineer until the React Admin loop (KYC, subscriptions, role apps) has been checked — ~90% of "it broke" is solvable by Platform Admin without touching Unfold.

**When adding a new feature:**
1. Find the layer that should own it in `0002-role-responsibilities.md`.
2. Business action on behalf of a company → guard with `is_platform_admin_viewer` + `is_member_of(user, company_id, capability='sell'|'buy')` in `services.py`. Subscription-gated seller writes → add `company_has_operational_subscription(company_id)`.
3. Platform moderation action → React Admin page + DRF endpoint, never a new `@admin.action` with business logic (Rule 8).
4. Never hard-code "Sales Manager" / "Account Manager" as `SystemRole` — they were removed by migration `accounts/0010_platform_admin_model`. Those names live only as WorkspaceRole codes now.

## ANTI-HALLUCINATION — What does NOT exist

### Tables that DON'T exist
- NO `payments` table — payment not yet implemented
- NO `sessions` table — sessions handled by Django middleware
- NO `roles` table — roles are `SystemRole` (in accounts app), NOT a separate table

### Endpoints that DON'T exist

- NO `POST /api/v1/catalog/products/import_excel/` — use `sourcing/import-catalog/` instead

### Endpoints that DO exist (common confusion)

- `POST /api/v1/accounts/users/{id}/toggle-active/` — `@action` in `accounts/views.py` (method is POST, not PUT)
- `GET /api/v1/catalog/products/export-template/` — `@action` in `catalog/views.py` (kebab-case URL)
- `GET /api/v1/crm/deals/{id}/export-pdf/` — `@action` in `crm/views.py` — returns active quote PDF (kebab-case URL)

### Fields that DON'T exist
- `users` table has NO `username` field for login — uses `email` as USERNAME_FIELD
- `deals` table has NO `discount` field
- `products` table has NO `price` field — prices are in `SupplierOffer` (separate table)
- Frontend `Product` type from `data/products.ts` is LEGACY — real products come from `catalogApi.getProducts()`

## Data Transformations

| DB (snake_case) | API Response (snake_case) | Frontend Store |
|-----------------|--------------------------|----------------|
| `first_name` | `first_name` | `firstName` (mapped in loadFromAuth) |
| `stage.code` | `stage_code` | `stage_code` (use for logic) |
| `stage.name` | `stage_name` | `stage_name` (use for display only) |
| `company.types` | `company_types[]` | `activeStatus` (CLIENT→BUYER, SUPPLIER→SELLER) |
| `verification_status.code` | `verification_status` | `kycStatus` |

Transformation happens in: `userStore.loadFromAuth()` and DRF serializers.

## Self-Check Before Commit

1. [ ] New/changed endpoint queries real DB? (no mocks, no hardcode)
2. [ ] Request/response fields match DB schema?
3. [ ] Naming follows conventions? (camelCase in JS, snake_case in DB)
4. [ ] All text wrapped in `t()`? No hardcoded Russian/English strings?
5. [ ] Colors use semantic tokens? (bg-primary, text-success, NOT bg-emerald-500)
6. [ ] Text sizes use Tailwind scale? (text-xs, text-sm, NOT text-[9px])
7. [ ] Using shadcn/ui components? (Button, Input, Table, Sidebar, NOT raw HTML)
8. [ ] Errors handled, not silently swallowed? (toast for user-facing, NOT alert())
9. [ ] Stage/status compared by `code`, not by translated `name`?
10. [ ] Frontend build passes? (`docker compose build frontend`)
11. [ ] No `as any`, `@ts-ignore` unless absolutely necessary with comment?
12. [ ] New i18n keys added to BOTH `ru.json` AND `en.json`? (no desync)
13. [ ] Run `/design-check` and `/check-i18n` skills for automated verification?

## Common Pitfalls

- Frontend is a **production build** served by nginx — `import.meta.env.DEV` is always `false` in Docker
- Auth URL routes (`/`, `/register`, `/setup-password`) handled by `useAuthRoute()` in App.tsx; main app pages use `#hash` navigation
- `DATABASE_URL` query params (like `channel_binding=require`) are passed as DB OPTIONS
- Volume mount `./backend:/app` enables hot-reload for backend; frontend needs rebuild (`docker compose up -d --build frontend`)
- `data/products.ts` exports an EMPTY array — it's legacy, use `catalogApi` for real data
- **Neon Cloud sleep** — free Neon projects suspend after inactivity. If backend shows "Connection refused", check Neon Console, wake the project, then `docker compose restart backend celery-worker celery-beat`. `dj-db-conn-pool` caches dead connections — only a container restart resets the pool
- **Superadmin is NOT auto-created** — must run `docker compose exec backend python manage.py init_superadmin` after migrations. Credentials come from `.env` (`SUPERADMIN_EMAIL`/`SUPERADMIN_PASSWORD`). Don't hardcode passwords in CLAUDE.md or README — always reference `.env`
- **No demo/simulation shortcuts** — no demo onboarding, no hardcoded test flows, no bypass of backend. For testing use real registration flow or create users via `init_superadmin`. Admin operations go through Django Unfold at `/admin/`
- **Don't assume code structure** — always read files before editing. Wrong assumptions (missing imports, wrong types, demo code bypassing backend) cost rebuild cycles. Verify imports exist, types match, and patterns match current code
- **Shell layouts live in two places** — `src/layouts/AppShell.tsx` (main) and `src/components/Layout/` (AdminShell, ClientShell, ManagerShell, CatalogShell)
