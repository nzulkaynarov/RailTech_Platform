# RailTech B2B SaaS — Claude Code Context

_Last full refresh: 2026-07-06 (HEAD c6cb04f, post PR #229); partial touch-ups: 2026-08-01 (heads crm 0090; направление «Документы» ЗАКРЫТО: шаблоны юр-видов E1–E4 + артефакты регистров D2 — PR #496–#506); 2026-07-27 («Документы 2.0», PR #383–#418); 2026-07-12 (2FA/sessions, Settings Hub). Verify against code when in doubt — Rule 6._

## Project Overview

B2B marketplace for railway equipment (Uzbekistan). Monorepo: Django backend + React frontend + Docker infrastructure.

**Domain:** Railway machinery, general goods, services — procurement, quoting (КП), CRM.
**Wedge product (ADR-0006):** the заявка → КП → контракт loop; AI acceleration is the monetized moat.

## Tech Stack

- **Backend:** Django 6.0, DRF, Daphne (ASGI), Channels (WebSocket), Celery + Redis, PostgreSQL 17 (self-hosted on a dedicated DB-VPS; Neon retired 2026-06-19)
- **Frontend:** React 18, TypeScript 5.6, Vite 7, Tailwind CSS 4, shadcn/ui, Zustand 5, React Query 5, i18next (RU/EN)
- **Infra:** Docker Compose (dev), **Caddy (prod edge on the app-VPS — owns TLS, CSP headers, XFF)**, nginx only *inside* the frontend container serving the SPA, GitHub Actions CI + self-hosted deploy runner, Sentry (backend + SPA)
- **Storage:** Django FileSystemStorage by default (== prod); MinIO is **opt-in** via compose profile `with-minio` (prod VPS CPU lacks x86-64-v2)
- **Auth:** JWT (simplejwt) — access 30min, refresh 7d in HttpOnly cookie, rotation enabled; per-account login lockout (`accounts/services/login_guard.py`); optional **2FA (TOTP)** — secret Fernet-encrypted at rest (key derived from `SECRET_KEY`), single-use login ticket + replay-tracked codes, step-up password to enable/disable (`accounts/services/two_factor.py`); **active sessions** list + revoke (`accounts/services/sessions.py`, endpoints under `/auth/`)
- **AI:** Anthropic API, model `claude-opus-4-8` (see AI Layer below)
- **PDF:** WeasyPrint (off-thread via Celery for the public КП path)
- **Excel:** pandas + openpyxl

## Project Structure

```
backend/                    # Django project
  core/                     # settings, urls, asgi, celery + cross-cutting: csp, idempotency,
                            #   optimistic_locking, versioning, audit, file_streaming, health,
                            #   dashboard, admin_mixins, validators (upload: size/type/ext/magic-bytes)
  accounts/                 # CustomUser, Company, CompanyMember, CompanyRole, OperatorRole, KYC,
                            #   Subscriptions + CompanyEntitlement, CompanyDocumentProfile, Contact
  accounts/views/           # applications, auth, company, lookups, operators, roles, users
  accounts/services/        # applications, auth, clients, company_settings, document_profile,
                            #   entitlements, kyc, login_guard, members, operators, permissions,
                            #   profile, roles, subscriptions
  catalog/                  # Product (PIM), Category, EquipmentGroup, SupplierOffer
  catalog/views/            # ai (PIM enrichment), lookups, offers, products
  crm/                      # Deal, DealSellerRouting, Quote, QuoteItem, Contract, Fulfillment,
                            #   Invoice/Act/Payment, Message, Lead, ActivityLog, ChargeTemplate
  crm/views/                # ai, ai_diff, analytics, billing, deals, exports, leads, messages, quotes
  crm/services/             # _params, ai_chat, ai_diff, approvals, assignment, availability, billing,
                            #   charges, contracts, deals, draft_quote, exporters, fulfillment,
                            #   messaging, metrics, numbering, pricing_assist, quotes, rfq
  sourcing/                 # Attachment, ImportTask, DomainKeyword; services_ai*.py (AI import/
                            #   preflight/conversational), views_ai_conversational.py
  master_data/              # AbstractLookup, Country, Currency, UOM, DeliveryBasis
  notifications/            # Notification (FK → deal; deep-links derive from it), EmailLog, EmailTemplate
  {crm,accounts,catalog}/models/   # Packages split by domain. Same-app FKs use string refs ("app.Model")
frontend/                   # React app
  src/api/                  # Axios client with JWT interceptor + refresh mutex; schema.d.ts (generated)
  src/store/                # 6 Zustand stores: auth, user, cart, task, theme, currency
  src/layouts/              # AppShell.tsx + PlatformAdminShell.tsx — the ONLY two shells
  src/config/navigation.tsx # buildNavigation(capabilities) — single capability-driven nav (ADR-0005)
  src/pages/                # ~40 pages incl. 16 Admin* pages (Entitlements, OperatorRoles, AccessLog,
                            #   EmailTemplates, KYC, ...) + PlatformAdminDashboard, Dashboard (Operations
                            #   Inbox), DealQuotePage, RequestDetailPage, Contracts/Fulfillments/
                            #   Invoices/Acts/Payments, SettingsPage (unified Settings Hub — profile,
                            #   security/2FA, company, documents, defaults, numbering, templates, team;
                            #   ProfilePage removed, `#profile` aliases `#settings?section=profile`)
  src/config/settingsSections.tsx # buildSettingsSections(gate) — capability-gated Settings Hub sections
  src/components/           # ui (shadcn), Admin, Auth, Billing, CRM, Cabinet, Dashboard, DataTable,
                            #   Settings (Settings Hub sections + team/ package), Sourcing,
                            #   Shared (OnboardingTour, ErrorBoundary — mounted in main.tsx + App.tsx),
                            #   ResponsiveDataTable.tsx (root),
                            #   Layout (ChatDrawer, CommandPalette, DocumentSearchDialog,
                            #   NotificationCenter, SupportButton — NOT shells)
  src/hooks/                # useAccounts, useAdmin, useBilling, useCRM, useCapabilities, useCatalog,
                            #   useMasterData, usePageStats, useSupport, useSystemSettings, useUrlState,
                            #   useViewerMode, use-mobile (exports useMediaQuery)
  src/i18n/locales/         # ru.json, en.json
deploy/caddy/               # Caddy edge config FRAGMENT (prod applies it manually — see Production)
# (root nginx/ removed 2026-07-12 — was dead; the SPA's nginx.conf lives in frontend/)
Docs/                       # Docs by audience (reorg 2026-07-07 — map: Docs/README.md):
  dev/                      #   adr/ (0001–0006), architecture/ (MSD, techspec, diagrams, schema.json,
                            #   websocket), ops/ (RUNBOOK, deploy/observability/staging/smoke/e2e…,
                            #   3 latest session-handoffs), specs/ (только живые ТЗ; выполненные — в old/specs/)
  business/                 #   ROADMAP, business-logic, ux-ui-brief, presentations/, mockups/
  user/                     #   end-user guides (stub — app Help lives in code, HelpPage.tsx)
  old/                      #   archive: handoffs/, audits/, roadmaps/, checkups/, misc/ (frozen)
                            # NOTE: macOS is case-insensitive — docs/ and Docs/ are the SAME dir
```

## Key Architecture Decisions

ADR index (`Docs/dev/adr/`): **0001** admin separation · **0002** role responsibilities · **0003** multi-tenant admin planes · **0004** three admin planes core (G1–G6) · **0005** unified capability-driven navigation · **0006** wedge loop + entitlements (Moves 0–4, KYC floor).

- **Hybrid routing** — auth routes (`/`, `/register`, `/setup-password`) via `useAuthRoute()` in App.tsx; everything else is hash-based SPA navigation in App.tsx (`#dashboard`, `#deal-quote/{id}`, `#admin-*` for the operator plane; shells receive `activePage`/`onNavigate` as props). NO React Router anywhere — the unused `react-router-dom` dependency was removed from package.json (2026-07-16)
- **2 shells only** — `AppShell` (all company users; buyer/seller context is **page-derived**, the manual context switcher was retired in ADR-0005 Phase C) and `PlatformAdminShell` (Platform Operators). Both use shadcn `<Sidebar>` `collapsible="icon"`, `p-6` content, `h-14` header
- **Unified navigation (ADR-0005)** — single `buildNavigation(capabilities)` in `frontend/src/config/navigation.tsx`; `/me` returns a `capabilities` object (kyc_level, can_buy/can_sell, subscription, CompanyRole permissions, operator_permissions). Tiers: T0 (pre-KYC: Dashboard+Catalog only) / T1 (KYC L2) / T2 (subscription). Items are HIDDEN, not disabled. Default context: BUYER; React-Query cache invalidated on context flip
- **B2B Multi-tenancy** — via `CompanyMember` join table, not schema/DB isolation
- **Multi-seller routing (keystone, ADR-0003 §5)** — заявка fan-out via `DealSellerRouting` (per-seller-company ownership, "hidden competition"); seller querysets scoped by `seller_visible_deal_ids`; claim/assignment in `crm/services/assignment.py`
- **Deal FSM** — DRAFT → KYC_PENDING → RFQ_OPEN → SOURCING → CALCULATING → QUOTE_SENT → CONTRACT_SIGNED → CLOSED_WON/CLOSED_LOST (`ALLOWED_STAGE_TRANSITIONS` in `crm/services/deals.py`; terminal states manager-reopenable). Move 0 auto-transitions: send КП → QUOTE_SENT; client approves КП → CONTRACT_SIGNED (+ Contract materialized); dual contract sign → CLOSED_WON (dispatches `auto_invoice_on_closed_won`)
- **Путь «после контракта» (волны F1–F3, G1–G3; спеки `spec-post-contract-flow-gap-2026-07-29.md` + `spec-post-contract-open-questions-2026-07-30.md`)**:
  - **Карточка сделки = хаб.** `GET crm/deals/{id}/documents/` (сервис `crm/services/deal_documents.py`) отдаёт договор/счета/платежи/акты/отгрузку + сторону зрителя + подсказку следующего шага. Паттерн smart-buttons карточки заказа Odoo. `next_step` — ПОДСКАЗКА, не гейт.
  - **Стороны считает СЕРВЕР, не `activeStatus`** (тот = первый тип компании и ломался у компании, которая и покупает, и продаёт): `viewer_can_pay`/`viewer_can_manage` (счёт), `viewer_can_sign`/`viewer_can_reject` (акт), `viewer_can_ship`/`viewer_can_accept` (отгрузка). Считаются ОДИН раз на запрос через `DealSideResolver` — есть тест на отсутствие N+1.
  - **Акт ДВУСТОРОННИЙ**: выпускает исполнитель (`issuer_*`), принимает или возвращает с причиной заказчик (`acceptor_*`). Выпустивший НЕ может принять свой же акт (`ACT_ACCEPTOR_SIDE_REQUIRED`). Клик без E-IMZO — не юридическая подпись, поэтому формулировка «согласовано в системе» и тег `[MANUAL_MODE]`.
  - **Триггер акта — ФАКТ ПОСТАВКИ, не оплата.** Авто-выпуск при выигрыше сделки удалён: закрывающий документ ни в одном эталоне не рождается от подписания сделки (Odoo — валидация отгрузки, SAP — приёмка получателем; IFRS 15/ASC 606 — выручка по передаче контроля).
  - **`OVERDUE` намеренно НЕ проставляется**: просрочка вычисляется из `due_date` + остатка, как у Stripe/Odoo/QuickBooks. Хранится только `Invoice.payment_reminder_sent_at` — состояние процесса напоминаний.
  - **Срок оплаты** считается от даты ВЫСТАВЛЕНИЯ (`issue_invoice`), берётся из `CompanySettings.payment_terms_days`, иначе `DEFAULT_INVOICE_DUE_DAYS`. Ручную дату бережёт флаг `Invoice.due_date_is_manual`.
  - **Письма на отрезке — ровно 4** (`crm/services/deal_emails.py`): счёт выставлен, оплата получена, напоминание о просрочке, акт ждёт подтверждения. Черновик/смена статуса/доставка/приёмка письма НЕ порождают (закреплено тестом).
- **Entitlement layer (ADR-0006 Move 4)** — `FeatureKey` codes in `accounts/constants.py`: `quote.send`, `quote.export`, `ai.match`, `ai.draft`, `ai.preflight`, `roles.custom`. `FREE_FLOOR_FEATURES={ai.match, ai.preflight}`; `SUBSCRIPTION_BASELINE_FEATURES={quote.send, quote.export, ai.draft, roles.custom}` (granted by operational `SupplierSubscription`; explicit `CompanyEntitlement` rows OVERRIDE — promo grant or DEMO downgrade → watermarked PDF). Service: `accounts/services/entitlements.py` (`has_entitlement`, `quote_send_entitled`, `consume_credit`, `is_demo`)
- **KYC floor (ADR-0006 Phase E)** — below L2: register + browse + DRAFT заявка only. Buyer submit raises `KYC_REQUIRED_TO_SUBMIT`; seller send/export requires KYC L2+ (`SELLER_KYC_REQUIRED`, checked before `SUBSCRIPTION_REQUIRED`). KYC-verified codes = `{L2_VERIFIED, L3_CONTRACTED}` (`accounts/services/kyc.py`)
- **AI layer (ARCH-01, 2026-07-07)** — **no LLM call ever runs in the request path.** The 8 interactive AI endpoints validate synchronously (clamps, visibility, 503 AI_DISABLED) then enqueue `sourcing.run_ai_job(feature, payload)` on the dedicated Celery queue `ai` (own `celery-worker-ai` service; the main worker does NOT consume `ai`) and answer **202 {task_id}**; the SPA polls `GET /api/v1/sourcing/ai-status/<task_id>/` (ownership = `AIJob` row, IDOR guard like ImportTask) via `frontend/src/lib/aiJob.ts`. `run_ai_job` is SINGLE-ATTEMPT (max_retries=0, no autoretry — handlers are paid-per-call and draft_quote writes + consumes a credit; documented deviation from the Celery convention). extract-document stages uploads in `default_storage` `ai_extract_tmp/` — file bytes never go through the Redis broker. ONE client factory `_client()` in `sourcing/services_ai.py` (anthropic.Anthropic, `AI_REQUEST_TIMEOUT`=60s); only the Celery bulk import (`extract_request_items`) uses `AI_MAX_RETRIES`. Features: match/preflight/extract/compose (sourcing), chat_reply/quote_diff/draft_quote (crm), enrich (catalog). Draft-КП auto-match: deterministic exact GOST/MPN (only if exactly 1 PUBLISHED product) then fuzzy AI auto-bind at confidence ≥ `AI_DRAFT_MATCH_CONFIDENCE` (0.9); AI failures are logged no-ops; the AI match runs OUTSIDE the write transaction and the worker re-checks the entitlement before the paid call
- **Public КП sharing** — unauthenticated `GET /api/v1/public/quotes/<token>/` (throttle `public_quote` 30/min; only frozen SENT quotes). PDF cache miss → enqueue `crm.tasks.render_document_pdf` + **202 + Retry-After**; browsers get a self-refreshing interstitial (`templates/public/quote_generating.html`). No SPA page in front of it by design
- **Документы юр-видов по шаблонам (E1–E4 + D2, PR #496–#506)** — договор/счёт/акт/квитанция/накладная печатаются по `DocumentTemplate` компании с откатом на платформенный образец (образцы — миграциями, Rule 1). Структурные блоки `{{doc.*}}` собирает сервер (`crm/services/document_blocks.py` — ЕДИНЫЙ каталог блоков/скаляров/формулировок); активация шаблона юр-вида требует обязательных блоков (`REQUIRED_TEMPLATE_BLOCKS`, ошибка `TEMPLATE_MISSING_REQUIRED_BLOCKS` называет недостающее). E3: `frozen_template_body` — документ печатает редакцию шаблона времени выпуска, блоки (ПЭП-штампы) живые. E4: `CompanyWordingVariant` + `Contract/Act.wording_selections` — менеджер меняет пункт ВЫБОРОМ согласованного варианта (`select-wording`, до первой подписи), не свободным текстом. D2: платёж/отгрузка остаются регистрами, печатаются их артефакты — квитанция (серия RCP) и накладная (позиции без цен, подписи «двух рук»); оба в «Недавних документах» и ⌘K-поиске
- **Currency: UZS-canonical** — `currencyStore` formats UZS, `Quote.quote_currency` defaults to UZS, КП presentation currency is locked to UZS (cost engine outputs UZS). Do NOT revert to USD
- **Financial precision** — `decimal.js` on frontend, `DecimalField` on backend, `QuoteItemHistory` audit trail; SAP-style cascading charges (`crm/services/charges.py`); optimistic locking on QuoteViewSet (`core/optimistic_locking.py`)
- **Dual Redis** — redis:6379 (Channels/WebSocket), redis-celery:6380 (Celery broker+results)
- **Auth model** — `CustomUser` with email as USERNAME_FIELD; `SystemRole` FK (ADMIN/USER) + optional `operator_role` FK (`OperatorRole`, ADR-0004 G1)
- **Company types** — `CompanyType` M2M on Company (CLIENT=Buyer, MANUFACTURER, SUPPLIER=Seller); returned in `/me/` as `company_types[]`; `loadFromAuth()` maps to frontend CompanyStatus (CLIENT→BUYER, SUPPLIER→SELLER, MANUFACTURER→MANUFACTURER)

## Database

- **Prod:** self-hosted **PostgreSQL 17** on a dedicated **DB-VPS** (private `10.0.0.2`, reached from the app-VPS `10.0.0.3` over the hoster's private LAN — interface `ens8`, NOT WireGuard; the box's `wg0` is an unrelated dead tunnel; `sslmode=require`). Native apt/PGDG install, NOT Docker. **Neon Cloud retired (2026-06-19).** Two DBs: `railtech` (prod) and `railtech_test` (testing). Prod `DATABASE_URL` lives ONLY in the GitHub Actions production secret. Daily `pg_dump` backups via cron on the DB-VPS → `/var/backups/railtech-db/` (14-day retention). See [[reference-vps-b2b]] memory.
- **Local dev:** a local **Postgres container** is added via `docker-compose.override.yml` (gitignored, auto-loaded by `make up`; prod/staging use explicit `-f ...prod.yml` so never load it). Backend reaches it as `db:5432`; `.env` → `DATABASE_URL=postgresql://railtech:railtech@db:5432/railtech?sslmode=disable`.
- **Connection:** `DATABASE_URL` env var parsed via `urlparse` (query params → DB `OPTIONS`, `sslmode` defaults to `require`), fallback to individual `POSTGRES_*` vars
- **Auth user:** `accounts.CustomUser` (email login)
- **Migration heads (2026-08-04):** `accounts/0043`, `crm/0092`, `catalog/0014`, `sourcing/0007`, `master_data/0013`, `notifications/0010`, `core/0004`. master_data: `0011` (HSCode — классификатор ТН ВЭД), `0012` (единицы измерения на HSCode), `0013` (beat-график недельного автосинка ТН ВЭД с tarif.customs.uz). Recent crm: `0085` (образцы счёта/договора + починка образца акта), `0086` (ActivityLog «одно слово»: инвойс→счёт, контракт→договор), `0087` (`frozen_template_body` на Contract/Invoice/Act — E3-снапшот), `0088` (`CompanyWordingVariant` + `wording_selections` — библиотека формулировок E4), `0089`/`0090` (квитанция RCP + накладная — D2, виды RECEIPT/DELIVERY_NOTE). Recent accounts: `0043` (D1 wording-поля)

## API Surface (prefix: `/api/v1/`)

- `auth/` — register, setup-password, submit-profile, token (login lockout applies), token/refresh
- `accounts/` — companies (verify-kyc, upload-document, team, invite, update-member-capabilities), users (toggle-active), me (returns `capabilities`), system-roles/workspace-roles/company-roles (operator views live in the accounts app but are mounted under `admin/`)
- `catalog/` — products (export-template), offers, equipment-groups, categories, manufacturers, AI enrichment
- `crm/` — deals (change-stage, claim, export-pdf, AI draft КП, **`documents/` — цепочка документов сделки одним ответом**), quotes (generate-pdf, send-to-client, approve, internal review chain), quote-items, messages, activity-logs, analytics (incl. time-to-first-quote), leads, exports, AI chat-assist + КП-diff, billing (invoices/acts/payments; **`acts/{id}/reject/` — возврат акта заказчиком с причиной**)
- `admin/` — entitlements, operator-roles, operator-permissions, break-glass (audited), platform admin CRUD
- `public/` — quotes/<token>/ (unauthenticated КП, 202-pattern), public media whitelist
- `sourcing/` — requests, import-deal/{id}, import-catalog, import-status/{task_id}, ai-status/{task_id} (poll for ALL interactive AI jobs), match-catalog, preflight-check, extract-document, compose-request — AI endpoints answer 202 {task_id} (ARCH-01)
- `master-data/` — countries, currencies, units, delivery-basis
- `notifications/` — CRUD + mark as read (structured FKs for deep-links)
- `health/` — health check (also at root `/health/`)

Full schema: `backend/schema.json` + generated `frontend/src/api/schema.d.ts` — оба под гейтом `api-contract` (CI перегенерирует их и падает на расхождении, поэтому им можно верить). **Any model label/verbose_name change flows into the OpenAPI schema — regenerate (spectacular + `gen:api-types`) or the `api-contract` CI gate fails.**

## Celery Tasks

- `sourcing.tasks.process_excel_import` / `process_catalog_import` — bulk imports, routed to queue `imports` via `CELERY_TASK_ROUTES`
- `sourcing.run_ai_job` (`sourcing/tasks_ai.py`) — ALL interactive AI work (ARCH-01), queue `ai`, single-attempt; registered via `autodiscover_tasks(related_name="tasks_ai")` in `core/celery.py`
- `crm.tasks`: `render_document_pdf` (ALL document PDFs render off-thread — request paths answer 202, ARCH-03), `send_quote_email`, `archive_old_messages`, `check_overdue_deliveries`, `auto_invoice_on_closed_won` (создаёт ТОЛЬКО счёт-черновик и отгрузку — акт здесь НЕ выпускается, см. ниже), `expire_stale_quotes`, `send_payment_reminders` (одно письмо по просроченному счёту; хранит факт отправки, а НЕ статус OVERDUE)
- Two workers: `celery-worker` (`default,pdf,imports`) + `celery-worker-ai` (`ai` only — real isolation from long imports). Both must mount the SAME media volume as backend (prod: `backend_media_prod`) — pdf tasks save files backend streams. Celery Beat — `django_celery_beat.schedulers:DatabaseScheduler`

## Environment

- Config via `.env` file (python-dotenv from `BASE_DIR.parent/.env` outside Docker; compose `env_file` inside)
- Key vars: `DATABASE_URL`, `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `REDIS_URL`, `CELERY_BROKER_URL`, `VITE_API_URL`, `VITE_WS_URL`, `FRONTEND_URL`
- Security: `DRF_NUM_PROXIES` (dev=0, prod=1 — SEC-04), `CSP_REPORT_ONLY` (code default true; prod sets false), `LOGIN_LOCKOUT_DISTINCT_IPS`/`_WINDOW`/`_COOLDOWN`, `PRODUCTION` (gates secure cookies/HSTS), `SENTRY_DSN`/`VITE_SENTRY_DSN`
- AI: `ANTHROPIC_API_KEY` (empty = AI off), `AI_IMPORT_MODEL` (claude-opus-4-8), `AI_IMPORT_ENABLED`, `AI_IMPORT_CHUNK_ROWS`, `AI_IMPORT_MAX_BYTES`, `AI_REQUEST_TIMEOUT`, `AI_MAX_RETRIES` (Celery only), `AI_DRAFT_MATCH_CONFIDENCE`
- MinIO (`MINIO_*`) — only when running `--profile with-minio`
- Frontend: build-time env via Vite `import.meta.env` (baked into production build)
- **Prod `.env` is rendered from GitHub secrets via a heredoc in `deploy-b2b.yml` — manual edits on the VPS are overwritten on every deploy**

## First-Time Setup

```bash
git clone git@github.com:nzulkaynarov/RailTech_SaaS_B2B.git && cd RailTech_SaaS_B2B
cp .env.example .env        # заполнить DJANGO_SECRET_KEY, SUPERADMIN_PASSWORD (DATABASE_URL уже локальный)
# docker-compose.override.yml в .gitignore — на свежем клоне его НЕТ. Создать из шаблона:
cp docker-compose.override.yml.example docker-compose.override.yml   # локальный postgres:17 `db`
make up                      # собрать и поднять все контейнеры (~1-3 мин; первый билд дольше).
                             # Локально entrypoint.sh сам выполняет migrate --noinput при старте
                             # (AUTO_MIGRATE=true по умолчанию) — make migrate идемпотентен.
                             # На проде AUTO_MIGRATE=false: миграции применяет deploy-workflow
                             # явным шагом ПОСЛЕ pg_dump backup-gate (INF-04)
make migrate                 # применить миграции (создают и business-коды — Rule 1)
make seed                    # core_seed: справочники (валюты, страны) + демо-пользователи
docker compose exec backend python manage.py init_superadmin   # создать суперадмина из .env
```

Superadmin credentials: `SUPERADMIN_EMAIL` / `SUPERADMIN_PASSWORD` from `.env` (default email: `admin@railtech.uz`).
Command `init_superadmin` reads these env vars and creates the user (`is_active/is_staff/is_superuser=True`). An EXISTING account is left untouched (SEC-10 — redeploys must not undo password rotations); rotate explicitly with `--reset-password`.

## Docker Services (dev)

| Service | Container | Port | Purpose | Health Check |
|---------|-----------|------|---------|-------------|
| backend | railtech_backend | 8000 | Django/Daphne ASGI, REST API, WebSocket | `curl /health/` |
| frontend | railtech_frontend | 5173 | React SPA (prod build via in-container nginx) | `wget /health` |
| db (override) | railtech_db | 5432 | PostgreSQL 17 (local dev only, gitignored override) | `pg_isready` |
| redis | railtech_redis_channels | 6379 | Django Channels (WebSocket) | `redis-cli ping` |
| redis-celery | railtech_redis_celery | 6380 | Celery broker + result backend | `redis-cli ping` |
| celery-worker | railtech_celery_worker | — | Queues default,pdf,imports: Excel import, PDF gen | `celery inspect ping` |
| celery-worker-ai | railtech_celery_worker_ai | — | Queue `ai` only: interactive AI jobs (ARCH-01) | `celery inspect ping` |
| celery-beat | railtech_celery_beat | — | Scheduled tasks (DatabaseScheduler) | — |
| minio / minio-init | railtech_minio | 9000, 9001 | **Opt-in only**: `docker compose --profile with-minio up` | `curl /minio/health/live` |

All ports are loopback-only (`127.0.0.1:`) — Docker's iptables rules bypass ufw.

## Web UI Endpoints (dev)

| Service | URL |
|---------|-----|
| Frontend (SPA) | http://localhost:5173 |
| Backend API | http://localhost:8000/api/v1/ |
| Swagger UI / ReDoc | http://localhost:8000/api/docs/ · /api/redoc/ |
| Django Admin (Unfold) | http://localhost:8000/admin/ |
| Health Check | http://localhost:8000/health/ |
| MinIO Console (with-minio profile only) | http://localhost:9001 |

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
make seed                # core_seed: dev/demo справочники + тест-пользователи (НЕ loaddata)
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

## Production Deployment

- **App-VPS** hosts Docker stack + host **Caddy** as the edge (TLS, CSP headers, X-Forwarded-For overwrite). Domain: `b2b.railtech.uz`; SPA served from `/var/www/railtech-b2b`
- Deploy: self-hosted GitHub runner, `.github/workflows/deploy-b2b.yml` (`-f docker-compose.yml -f docker-compose.prod.yml`); prod `.env` rendered from GitHub production secrets (heredoc) — includes `CSP_REPORT_ONLY=false`, `DRF_NUM_PROXIES=1`, `PRODUCTION=true`
- **Caddy config is applied MANUALLY**: repo fragment `deploy/caddy/b2b.railtech.uz.caddy` → `/etc/caddy/conf.d/b2b.caddy`, validate, `systemctl reload caddy`. Caddy's site-level headers REPLACE Django's for the whole origin — `core/csp.py` is only a fallback for /api+/admin
- **Deploy race:** two quick merges can cancel the newer run — after back-to-back merges verify the deployed bundle hash on the box matches main HEAD
- **Staging does not exist yet** (needs DNS + `staging` GitHub environment + Caddy block); nightly Playwright e2e targets prod with prod-safe specs only
- CI security gates are HARD: pip-audit + `npm audit --audit-level=high`; all GitHub Actions SHA-pinned

## Coding Conventions

- **Python:** black (120 line length), isort (profile=black), flake8; target Python 3.12 (Django 6.0 требует ≥3.12 — образ и CI на 3.12)
- **Backend deps (INF-05):** `backend/requirements.txt` + `requirements-dev.txt` are GENERATED, hashed pip-compile locks — never hand-edit them. Change a floor/cap in `requirements.{in,dev.in}`, then recompile: `pip-compile --generate-hashes --no-strip-extras requirements.in -o requirements.txt` (+ the `-dev` variant with `-c requirements.txt`) in a linux py3.12 env with `gcc`+`libpq-dev` (pip-tools 7.5.3). The CI `deps-lock` gate fails on drift. psycopg2 is built from source (not `-binary`, INF-09).
- **TypeScript:** strict mode, ESLint, path alias `@/` → `src/`
- **Styling:** Tailwind v4 utility-first, oklch color tokens, CSS variables, dark mode via `.dark` class
- **Models:** `AbstractLookup` base for reference tables (code, name, sort_order, is_active)
- **Serializers:** Nested read, flat write pattern; `_data` suffix for nested representations
- **i18n:** All UI text via `useTranslation()`, keys in `ru.json`/`en.json`
- **State:** Zustand stores with `persist` middleware for auth/theme; no Redux
- **UI:** Only shadcn/ui components + Tailwind semantic tokens. No custom CSS, no hardcoded hex colors, no `text-white`/`text-black` — use `text-foreground`/`text-primary-foreground`
- **Text sizes:** Only Tailwind scale (`text-xs` minimum) — NEVER `text-[9px]`, `text-[10px]`, `text-[11px]` or arbitrary pixel values
- **Chart colors:** Use `bg-[var(--color-chart-N)]` for dynamic chart legend dots — NEVER inline `style={{ backgroundColor }}`
- **Sidebar:** shells use shadcn `<Sidebar>` + `<SidebarProvider>` + `<SidebarInset>` — NEVER custom `<aside>` with manual collapse state
- **Tables:** new list pages use `ResponsiveDataTable` (mobile card fallback); rows must be keyboard-accessible
- **Zod validation messages:** For i18n, use factory pattern: `const createSchema = (t: TFn) => z.object(...)` — call inside component where `t()` is available
- **Query optimization:** Use `aggregate(total=Count('id'), active=Count('id', filter=Q(...)))` for dashboard stats — NEVER fire individual `.count()` queries in loops
- **Celery tasks:** ALL tasks must have `time_limit=600, soft_time_limit=540, max_retries=3, autoretry_for=(Exception,), retry_backoff=True`. Exception: bulk-import tasks in `sourcing/tasks.py` use `time_limit=1800, soft_time_limit=1700` (50k-row catalogs) — retry/backoff still apply
- **AI calls:** NEVER call the Anthropic client from an HTTP handler — new interactive AI features go through `enqueue_ai_job(feature, payload, user)` (202 + `ai-status` polling; add the handler to `sourcing/tasks_ai.py` FEATURE_HANDLERS). The job task is single-attempt; AI match/enrich failures inside services are logged no-ops, never user-facing 500s
- **Uploads:** every new upload path must call the `core/validators.py` helpers incl. magic-byte content check (`assert_content_matches_extension`)
- **API errors:** always `{"detail": "<CODE>"}` (DRF-native shape; codes compared by value on the frontend) — NEVER `{"error": ...}`. Guarded by `core/tests/test_error_shape.py`
- **Exception handling:** Use specific exceptions (`ValidationError`, `OSError`, `ValueError`) — NEVER bare `except Exception`
- **Variable naming:** Descriptive names always — NEVER single-letter variables in business logic
- **Function length:** Max 50 lines for production code. **File length:** max 500 lines — split into packages. **Parameters:** max 5 — use dataclasses beyond that

## Performance Conventions

- Dashboard endpoints: `aggregate()` queries + per-user cache (30-60s TTL)
- List endpoints: always `select_related`/`prefetch_related`, never N+1
- Smart Match: requires GIN trigram indexes on `Product.name` and `gost_drawing`
- Edge/nginx: NEVER cache authenticated API responses (Authorization header bypass); no per-JWT page caches
- Request path must not block ASGI workers: PDF render and AI retries go to Celery (202 pattern for public КП)
- Channel layers: `capacity=300`, `expiry=60`
- Frontend bundle: split vendor chunks (react, charts, i18n, state, radix, http)

## Testing

- **Backend:** pytest + pytest-django, markers: slow, integration, unit; coverage threshold: 30% enforced on CI (`--cov-fail-under=30`). Current state (2026-07-07): **~672 tests, ~78% coverage**. CI runs `pytest --create-db` on an ephemeral Postgres, **с миграциями** (`--nomigrations` снят 2026-08-03): по Rule 1 справочники и платформенные образцы шаблонов сеются данными-миграциями, поэтому база без них — другая база (22 теста падали на пустых `DealStage`/`ContractStatus`). Джоба также компилирует каталог (`compilemessages`) — `.mo` в git нет, а тест каталога проверяет реальный перевод. Local tests run against the local Docker Postgres (`db` from `docker-compose.override.yml`, `sslmode=disable`); `--reuse-db` masks seed gaps — reproduce CI failures with `--create-db`.
- **Frontend:** vitest 4 + @testing-library/react + jsdom — 13 test files, 93 tests (stores/hooks/utils + component tests for AdminDataTable/DealsKanban/GenerateQuoteDialog/DashboardWidgets; shared `src/test/renderWithProviders.tsx` with a real ru.json i18n instance). Runs on the developer machine and in the CI `frontend-test` job — NOT in Compose (the frontend container is a prod nginx build).
- **CI:** GitHub Actions — jobs: i18n-symmetry, backend-lint, backend-test, migration-check, api-contract (spectacular + openapi-typescript drift), frontend-lint, frontend-test (vitest), frontend-build, security (pip-audit + npm audit, HARD gates), docker-build. Nightly Playwright e2e is a separate workflow (targets prod, prod-safe specs).
- **Known test debt:** none named — the last items (frontend component tests, PR #234; backend fulfillment/messaging services, PR #228) are paid. Playwright e2e specs remain thin (nightly, prod-safe subset only).

## Auth Flow (production)

1. User opens app → `LoginPage` (or `/register` → `KYCRegistrationForm`)
2. Registration: `POST /api/v1/auth/register/` → creates `CustomUser(is_active=False)` + sends email
3. In DEBUG mode, email prints to **backend container logs** (`docker compose logs backend`). **Every email (DEBUG and prod) is also persisted in `EmailLog`** — view at `/admin/notifications/emaillog/` (Unfold → Аудит и мониторинг → Журнал email)
4. User clicks link `/setup-password?uid=...&token=...` → `PasswordSetupPage` → sets password → `is_active=True`
5. KYC verification: Platform Operator approves via React Admin (`/admin/*` KYC page). Approval WITHOUT documents is ALLOWED by owner policy (requires warning + justification) — do NOT "fix" this as a bug
6. User logs in with JWT → refresh token in HttpOnly cookie. **Login lockout:** ≥`LOGIN_LOCKOUT_DISTINCT_IPS` (10) distinct failing IPs for one email within 15 min → generic 429 for 15 min (`accounts/services/login_guard.py`)

**Email delivery:** single entry point `notifications.emails.send_templated_email(template, context, to, channel, user)`; channels `transactional`/`marketing`(reserved)/`system` in `settings.EMAIL_CHANNELS` (per-channel SMTP via `EMAIL_TX_*/EMAIL_MKT_*/EMAIL_SYS_*`). Templates: `backend/templates/emails/{name}.{html,txt,_subject.txt}`.

**Superadmin:** created via `python manage.py init_superadmin` from `SUPERADMIN_EMAIL`/`SUPERADMIN_PASSWORD` in `.env`. NOT auto-created — run manually after `make migrate` + `make seed`.

## PRODUCT RULES — владелец, 2026-07-21 (обязательны наравне с IRON RULES)

Контекст: точечные фиксы по спискам наблюдений дали «визуальный мусор и тупики» вместо целостного продукта. Цель платформы — чтобы пользователи почувствовали разницу между ручной и автоматизированной работой, а руководители видели стабильность. Отсюда:

1. **Benchmark-first.** Перед любой продуктовой задачей (не механическим рефактором) — короткий разбор, как это решено в эталонах (Odoo Sales/CPQ, Salesforce CPQ, Bitrix24, PandaDoc/Qwilr для КП). Применяется именованный паттерн; кастом допустим ТОЛЬКО если эталона нет, и это проговаривается владельцу явно.
2. **Никаких новых блокировок, гейтов, SLA-метрик** без явного запроса владельца. Трение убираем, не добавляем.
3. **Наблюдения владельца — симптомы, не бэклог.** «Смущает X / непонятно Y» → сначала собрать целевой путь пользователя целиком, показать gap-анализ, утвердить картину — потом код одной связной волной. Не закрывать наблюдения поштучными PR.
4. **Definition of Done — пройденный глазами сценарий** (заявка → КП → отправка → клиент открыл → согласовал) без тупиков, со скриншотом/GIF владельцу. «Тесты зелёные, PR смержен» — НЕ done.
5. **Меню тактических опций — тоже кастом.** Прежде чем предлагать владельцу варианты механик, показать, как задачу решает мировой опыт.
6. **Стековые PR** мержить сверху-вниз с ретаргетом на main, либо каждый с удалением базовой ветки — иначе контент не доходит до main (инцидент 2026-07-21, re-land #373).

## IRON RULES — VIOLATION PROHIBITED

### Rule 1: No fake data
- NEVER create mock data, static arrays, or fake API responses in production code
- EVERY endpoint MUST query the real database via Django ORM
- If test data is needed — use management commands (`core_seed`), not hardcode
- **Seed = data migrations.** Business lookup rows (SystemRole.ADMIN, DealStage.RFQ_OPEN, VerificationStatus.L2_VERIFIED, etc.) are created via `migrations.RunPython` with `get_or_create` and a reverse no-op. `loaddata` fixtures and management commands are **dev/demo-only**. After `migrate` on a fresh DB, every code referenced by services / FSM / permissions MUST already exist. Any `Model.objects.get_or_create(code=...)` in hot paths is a violation — use `Model.objects.get(code=...)` that raises clearly if the migration was not applied.

### Rule 2: No hardcoded values
- URLs, keys, secrets, IDs — ONLY from environment variables (.env)
- Business constants (limits, prices, settings) — ONLY from DB or config
- Roles, statuses, enum values — compare by `code` field (e.g., `stage_code === 'DRAFT'`), NEVER by translated `name`

### Rule 3: Strict naming
- JS/TS variables and functions: camelCase; classes and types: PascalCase
- API endpoints: kebab-case, plural nouns
- DB tables and columns: snake_case; env vars: UPPER_SNAKE_CASE; booleans: `is_`/`has_` prefix

### Rule 4: Only shadcn/ui + semantic tokens
- ONLY use components from `@/components/ui/` (shadcn/ui)
- Colors: `bg-primary`, `text-foreground`, `bg-success`, `bg-warning`, `bg-destructive`, `bg-info` — NEVER `bg-emerald-500`, `text-white`, `bg-amber-*`, `bg-red-600`
- Text sizes: ONLY Tailwind scale (`text-xs` minimum)
- No custom CSS, no inline styles for static values, no decorative hacks
- Sidebar: shadcn `<Sidebar>` primitives, NOT custom `<aside>`

### Rule 5: All text via i18n
- ALL user-facing text wrapped in `t()` from `useTranslation()`; keys in BOTH `ru.json` and `en.json`
- Store files (Zustand) hold i18n KEYS, not raw text — translate in components

### Rule 6: Always read before writing
- ALWAYS read the file with Read tool before editing; verify imports, types, DB fields
- NEVER assume file contents or code structure

### Rule 7: Frontend-backend sync
- Every frontend feature must call a real backend API endpoint
- Use `stage_code` (DB code) for logic, `stage_name` only for display

### Rule 8: Business logic lives in services only

- ALL business logic (state transitions, validations, side effects, email sends, Celery dispatches, multi-model updates) MUST live in `<app>/services/` (or `services.py`) as plain functions
- `admin.py` actions and `views.py` ViewSets are THIN WRAPPERS: authorize → validate → call ONE service function → return
- NEVER duplicate logic between an admin action and a DRF endpoint — both call the same service
- See `Docs/dev/adr/0001-admin-separation.md` (Django Unfold = engineers; React Admin = business users)

**Right:**
```python
# accounts/services/kyc.py
def verify_company_kyc(company, approver, level_code): ...

# accounts/admin.py — thin wrapper calls services.verify_company_kyc(...)
# accounts/views/company.py — thin @action calls the SAME service
```

### Admin separation — where to add new features

- **New business features → React Admin** (`#admin-*` pages in the SPA, PlatformAdminShell). Django Unfold (`:8000/admin/`) is for engineers only.
- Unfold is reserved for: master data CRUD (lookups), read-only audit inspection, Celery beat schedule, Django auth groups, emergency data fixes by DBA.
- Adding a new `@admin.action` with business logic? STOP — implement it as a React page + DRF endpoint instead.

## Roles & Permissions (ADR-0002 → refined by ADR-0003/0004)

Canonical sources: `Docs/dev/adr/0002-role-responsibilities.md` (layers), `0003` (planes + never-orphan), `0004` (operator sub-roles, break-glass).

**Layers (not interchangeable):**
- **SystemRole** on `CustomUser.role` — only `ADMIN` (Platform Operator, no memberships) and `USER`
- **OperatorRole** on `CustomUser.operator_role` (ADR-0004 G1) — granular operator sub-roles: `SUPPORT`, `KYC_OFFICER`, `BILLING_OPERATOR`, `MODERATOR`, `SUPER_OPERATOR`; permissions like `users.manage`, `kyc.verify`, `moderation.force_override` (catalog in `accounts/constants.py`); audited break-glass endpoint for escalation
- **CompanyRole** (per-tenant custom roles, ADR-0004 G4) — permission codes drive КП access: `quote.build`, `quote.send`, `quote.view_cost_margin`, `quote.edit_pricing`, `quote.review`, `quote.approve_final` (internal chain) vs `quote.approve` (buyer accept). Company-admin hub is gated by permission, not by WorkspaceRole
- **WorkspaceRole** on `CompanyMember.role` — `OWNER` (displayed as «Администратор компании»), SALES_MANAGER, LOGIST, etc. Never-orphan invariant: ≥1 active OWNER per company (`CANNOT_REMOVE_LAST_COMPANY_ADMIN`). **ADR-0005 Phase E U3 deprecation COMPLETE (PR #255):** WorkspaceRole is now a label/derivation layer only — no business authz branches on `has_workspace_role`/`WorkspaceRoleCode` (all gating is `member_has_permission` on CompanyRole; never-orphan checks on `is_system`)
- **Per-member capabilities** `CompanyMember.can_sell`/`can_buy` — distributed by OWNER

| Layer | Tool | Owns | Does NOT |
|---|---|---|---|
| **Platform Engineer** (`is_superuser`) | Unfold + terminal | Deploy, migrations, master data, Celery Beat, emergency fixes | Business ops on behalf of companies |
| **Platform Operator** (`SystemRole.ADMIN` + OperatorRole) | `PlatformAdminShell` | Users / Companies / KYC L1→L2→L3 / Subscriptions / Entitlements / Role applications / Force-overrides per OperatorPermission | Becoming a `CompanyMember`; any buy/sell/sign/pay — backend returns `ADMIN_VIEWER_CANNOT_ACT` |
| **SUPPLIER / MANUFACTURER team** | `AppShell` (seller context) | Respond to routed заявки (claim via DealSellerRouting), build/send КП (entitlement + KYC gated), sign contracts, fulfillment (with `can_sell`) | Other companies' data; platform moderation |
| **CLIENT team** | `AppShell` (buyer context) | Open заявка (KYC L2+ to submit), import Excel, accept/reject КП, sign as buyer, record payment (with `can_buy`) | Other companies' data; seller-side actions |

**When adding a feature:** pick the owning layer first; guard business actions with `is_platform_admin_viewer` + membership capability + entitlement/KYC checks in services; platform moderation → React Admin page + DRF endpoint (never a business `@admin.action`). Never hard-code "Sales Manager"/"Account Manager" as SystemRole.

## ANTI-HALLUCINATION — verify before you code

### Things that DO exist (commonly assumed missing)
- `Payment`, `Invoice`, `InvoiceItem`, `Act` models (`crm/models/billing.py`) + Payments/Invoices/Acts pages. (Real payment-provider integration — Click/Payme — is NOT implemented; these are ledger records)
- `POST /api/v1/accounts/users/{id}/toggle-active/` (POST, not PUT); `GET /api/v1/catalog/products/export-template/`; `GET /api/v1/crm/deals/{id}/export-pdf/`
- `CompanyEntitlement`, `OperatorRole`, `CompanyRole`, `DealSellerRouting`, `Contact` (offline clients, `Deal.contact`), `CompanyDocumentProfile` models
- **Leads page IS live** — `AdminLeadsPage` (`#admin-leads`, operator plane, `useLeads` → `crm/views/leads.py`); **Clients/Suppliers pages ARE live** — `CounterpartiesPage` (buyer/seller counterparty book, ADR CRM relationship layer). The `crm/analytics/dashboard/` endpoint (incl. time-to-first-quote, `crm/views/analytics.py`) feeds the Operations Dashboard via `dashboardApi` — there is no *standalone* Analytics page, analytics render inside `Dashboard.tsx`

### Things that DON'T exist
- NO авто-выпуска акта при выигрыше сделки — `auto_invoice_on_closed_won` создаёт ТОЛЬКО счёт-черновик и отгрузку (G1). Акт выпускает продавец кнопкой по факту поставки
- NO задачи, проставляющей `InvoiceStatusCode.OVERDUE` — код в справочнике есть, но статус НЕ проставляется намеренно: просрочка вычисляется из `due_date` + остатка
- NO `SupplierBid` model / bids flow — replaced by multi-seller routing + quotes (only historic migrations mention it); no `bids.py` in crm/views or crm/services
- NO `L3_VERIFIED` KYC code — it's `L3_CONTRACTED` (phantom code; verified set = {L2_VERIFIED, L3_CONTRACTED})
- NO session auth on `/api/v1/` — pure JWT. (`django.contrib.sessions` IS installed and `django_session` exists, but serves only the Unfold `/admin/` login)
- NO separate `roles` table — `SystemRole` lives in accounts
- NO `POST /api/v1/catalog/products/import_excel/` — use `sourcing/import-catalog/`
- NO *standalone* frontend Analytics page — analytics render inside the Operations Dashboard (`Dashboard.tsx` via `dashboardApi` → `crm/analytics/dashboard/`). (Leads and Clients/Suppliers pages DO exist — see the "DO exist" list above.)
- NO `SourcingImportPage` — deleted; import lives inline in the request dialog
- `users` table has NO `username` login field (email is USERNAME_FIELD); `deals` has NO `discount` field; `products` has NO `price` field (prices in `SupplierOffer`)
- NO `data/products.ts` — deleted entirely; products come only from `catalogApi.getProducts()`

## Data Transformations

| DB (snake_case) | API Response | Frontend Store |
|-----------------|--------------|----------------|
| `first_name` | `first_name` | `firstName` (mapped in loadFromAuth) |
| `stage.code` | `stage_code` | `stage_code` (use for logic) |
| `stage.name` | `stage_name` | `stage_name` (display only) |
| `company.types` | `company_types[]` | `activeStatus` (CLIENT→BUYER, SUPPLIER→SELLER) |
| `verification_status.code` | `verification_status` | `kycStatus` |

Transformation happens in: `userStore.loadFromAuth()` and DRF serializers.

## Self-Check Before Commit

1. [ ] New/changed endpoint queries real DB? (no mocks, no hardcode)
2. [ ] Request/response fields match DB schema? OpenAPI schema + `schema.d.ts` regenerated if models/serializers changed?
3. [ ] Naming follows conventions? (camelCase in JS, snake_case in DB)
4. [ ] All text wrapped in `t()`? Keys in BOTH `ru.json` AND `en.json`?
5. [ ] Colors use semantic tokens? Text sizes on Tailwind scale?
6. [ ] Using shadcn/ui components (incl. `ResponsiveDataTable` for lists)?
7. [ ] Errors handled, not silently swallowed? (toast for user-facing, NOT alert())
8. [ ] Stage/status/entitlement compared by `code`, not by translated `name`?
9. [ ] Seller/buyer actions gated in services (KYC floor, entitlement, capability)?
10. [ ] Frontend build passes? (`docker compose build frontend`)
11. [ ] No `as any`, `@ts-ignore` unless absolutely necessary with comment?
12. [ ] Run `/design-check` and `/check-i18n` skills for automated verification?

## Common Pitfalls

- Frontend is a **production build** served by in-container nginx — `import.meta.env.DEV` is always `false` in Docker; frontend changes need rebuild (`docker compose up -d --build frontend`)
- Auth URL routes (`/`, `/register`, `/setup-password`) via `useAuthRoute()`; main app pages use `#hash` navigation. Cold-load hash deep-links (`#request-detail/3`, `#deal-quote/7`) РАБОТАЮТ — `evaluatePageGuard` откладывает гейты до bootstrap (раньше отскакивало в `#dashboard`; починено, email-ссылки W1 на это опираются)
- **Celery does NOT auto-reload** (only Daphne does). After ANY model/migration change: `docker compose restart celery-worker celery-beat` — otherwise tasks run stale code. Prod is safe (deploy does `up -d --build`)
- `DATABASE_URL` query params (like `sslmode=require`) are passed as DB OPTIONS
- **api-contract CI gate**: model `verbose_name`/label edits change the OpenAPI schema — regenerate spectacular schema + `gen:api-types` in the same PR
- **Request-path AI**: never add retries or unbounded timeouts to HTTP-handler AI calls (`max_retries=0` convention); heavy AI work → Celery
- **DB-VPS connectivity** (prod) — private LAN (`ens8`, `ip route get 10.0.0.2`) down / `pg_hba.conf` / Postgres offline are the usual suspects; `dj-db-conn-pool` caches dead connections — restart backend + celery containers to reset the pool
- **Superadmin is NOT auto-created** — run `init_superadmin` manually; credentials from `.env`, never hardcode
- **No demo/simulation shortcuts** — no hardcoded test flows, no backend bypass. Test via real registration or `init_superadmin`
- **Don't assume code structure** — read files before editing; the codebase moves fast and docs (including this file) lag
- **docs/ vs Docs/**: canonical git tree is `Docs/` — on macOS they alias to one directory, on Linux/CI they don't. Always add docs under `Docs/`, in the right audience folder: `Docs/dev/` (adr/architecture/ops/specs), `Docs/business/`, `Docs/user/`; archive superseded/point-in-time docs to `Docs/old/`. Map: `Docs/README.md`
- KYC L2 approval without documents is owner policy (warning + justification required) — not a bug to fix
