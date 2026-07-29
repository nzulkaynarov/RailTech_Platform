---
title: Техническая спецификация — RailTech B2B Ecosystem
project: RailTech B2B Ecosystem
type: technical-specification
version: 6.0 (Actualized)
status: Active
tags: [django, react, postgresql, celery, channels, websockets, rbac, minio]
date: 2026-04-17
---

# Техническая спецификация

Актуальная сводка технического стека, моделей БД и API. Отражает фактическое состояние репозитория на 2026-04-17. Для бизнес-логики см. [business-logic.md](../../business/business-logic.md), для ролей — [role-model.md](../../old/misc/role-model.md).

## 1. Технологический стек

### 1.1. Backend

| Слой | Компонент | Версия |
| --- | --- | --- |
| Runtime | Python (docker `python:3.13-slim`) | 3.13 |
| Framework | Django | 5.2+ |
| API | Django REST Framework | 3.16+ |
| Auth | `djangorestframework-simplejwt` | 5.5+ |
| ASGI | Daphne | 4.2+ |
| Real-time | `channels`, `channels-redis` | 4.3+ |
| Async | Celery | 5.6+ |
| Scheduler | `django-celery-beat` (DatabaseScheduler) | 2.9+ |
| DB driver | `psycopg2-binary`, `django-db-connection-pool[postgresql]` | 2.9+, 1.2.6+ |
| DB | PostgreSQL (Neon Cloud, `pg_trgm`, JSONB) | 15+ |
| Storage | `django-storages[s3]` + `boto3` (MinIO S3-совместимый) | 1.14.6+ / 1.42+ |
| Data | pandas, openpyxl, XlsxWriter | 2.2+ / 3.1.5+ / 3.2+ |
| PDF | WeasyPrint | 68+ |
| Admin | `django-unfold`, `django-import-export`, `django-formtools` | 0.88+ / 4.4+ / 2.5+ |
| API docs | `drf-spectacular` (только DEBUG) | 0.29+ |
| Audit | `django-pghistory` + `django-pgtrigger` | 3.9+ / 4.9+ |
| Архитектура | Service Layer (`<app>/services.py`) — см. IRON RULE 8 в CLAUDE.md | — |

### 1.2. Frontend

| Слой | Компонент | Версия |
| --- | --- | --- |
| Runtime | Node 22 (dev), nginx:alpine (serving prod build) | 22 |
| Framework | React + react-dom | 18.3.1 |
| Language | TypeScript (strict mode) | 5.6.2 |
| Bundler | Vite | 7.0+ |
| Styling | Tailwind CSS v4 (oklch, `.dark` class, `@tailwindcss/vite`) | 4.2+ |
| UI kit | shadcn/ui (64 компонента) + Radix/Base UI | — |
| Icons | lucide-react | 0.577+ |
| State | Zustand (9 сторов, `persist` на auth/theme) | 5.0+ |
| Data fetching | `@tanstack/react-query` + axios | 5.90+ / 1.13+ |
| Forms | react-hook-form + zod + `@hookform/resolvers` | 7.71 / 4.3 / 5.2 |
| i18n | i18next + react-i18next | 25.8 / 16.5 |
| Financial | decimal.js | 10.5 |
| Charts | recharts | 2.15 |
| Toasts | sonner | 2.0 |
| Theming | next-themes | 0.4 |
| Tests | vitest + @testing-library/react + jsdom | 1.1 |

### 1.3. Инфраструктура

| Компонент | Образ | Назначение |
| --- | --- | --- |
| `backend` | python:3.13-slim + Daphne (dev) / Gunicorn+Uvicorn-workers (prod) | Django ASGI + WebSocket |
| `frontend` | node:22-alpine → nginx:alpine | Static SPA build |
| `redis` (Channels) | redis:7-alpine, port 6379 | WebSocket channel layer |
| `redis-celery` | redis:7-alpine, port 6380 | Celery broker + result backend |
| `minio` | minio/minio (9000 API, 9001 Console) | 3 бакета: `railtech-public`, `railtech-private`, `railtech-temp` |
| `minio-init` | minio/mc | Разовое создание бакетов |
| `celery-worker` | python:3.13-slim | Очереди `default`, `pdf`, `imports` |
| `celery-beat` | python:3.13-slim | Периодические задачи через `django-celery-beat` |
| `nginx` (prod only) | nginx:stable-alpine | Reverse proxy, SSL, rate-limit, cache |

---

## 2. Модели БД (Domain-Driven Taxonomy)

### 2.1. Справочники (master data)

Все справочники наследуют абстракцию `AbstractLookup` (поля `code`, `name`, `sort_order`, `is_active`) и сидируются из `backend/core/data/seed_data.json`.

| Приложение | Модели |
| --- | --- |
| `accounts` | `SystemRole`, `WorkspaceRole`, `CompanyType`, `VerificationStatus`, `KYCDocType` |
| `catalog` | `DomainType`, `ProductStatus`, `StockStatus` |
| `crm` | `DealStage`, `QuoteStatus` |
| `master_data` | `Country` (+ `vat_rate`), `Currency`, `UnitOfMeasure`, `DeliveryBasis` |
| `notifications` | `NotificationType` |

### 2.2. Основные сущности

#### accounts

- **`CustomUser`**: `email` (USERNAME_FIELD), `phone`, `avatar`, `role` (FK `SystemRole`).
- **`Company`**: `name`, `inn` (unique), `types` (M2M `CompanyType`), `verification_status` (FK `VerificationStatus`), `trust_score`, `country` (FK), `logo`, `kyc_notes`.
- **`CompanyMember`**: `user`, `company`, `role` (FK `WorkspaceRole`), `is_primary`, `is_active`.
- **`KYCDocument`**: `company`, `doc_type`, `file` (MinIO private), `original_filename`, `uploaded_at`.
- **`CompanyRoleApplication`**: `company`, `requested_type`, `status`, `contract_file`, `nda_file`, `partnership_agreement`, `reviewed_by`, `review_notes`.
- **`SupplierSubscription`**: `company` (OneToOne), `plan`, `status`, `monthly_rate`, `currency`, `valid_from/until`, `next_payment_date`.

#### catalog

- **`Product`**: `name`, `sku`, `domain_type` (FK), `status` (FK), `category` (FK), `uom` (FK), `manufacturer` (FK Company), `equipment_groups` (M2M EquipmentGroup), `gost_drawing`, `specifications` JSONB.
- **`Category`**: `name`, `domain_type`, `parent` (self FK), `icon`, `sort_order`, `is_active`.
- **`EquipmentGroup`**: рекурсивный `parent` (self FK), `cached_path`, `sort_order`, `is_active`.
- **`SupplierOffer`**: `product`, `supplier`, `supplier_sku`, `base_price`, `currency`, `delivery_basis`, `stock_status`, `delivery_lead_time`, `min_order_qty`, `valid_from/until`, `is_active`.
- **`ProductImage`**: `product`, `image`, `image_url`, `is_main`, `alt_text`, `sort_order`.
- **`ProductDocument`**: `product`, `file`, `file_url`, `name`, `uploaded_at`.

#### crm (все 3 финансовые модели трекаются `@pghistory.track`)

- **`Deal`**: `company`, `client`, `manager`, `stage` (FK `DealStage`), `title`, `notes`.
- **`Quote`**: `deal`, `version`, `status`, `prepared_by`, `tax_country`, `vat_rate`, `subtotal_excl_vat`, `vat_amount`, `total_incl_vat`, `valid_until`, `pdf_file`, `frozen_at`, `approved_at`, `approved_by`.
- **`QuoteItem`**: `quote`, `product`, `offer`, `imported_raw_name`, `quantity`, `assigned_at`, `frozen_base_price`, `frozen_currency`, `logistics_cost`, `customs_duty`, `margin_percent`, `landed_cost`, `final_price_excl_vat`.
- **`QuoteItemHistory`**: immutable snapshot всех financial-полей + `change_reason`, `created_at`.
- **`Message`**: `deal`, `sender`, `text`, `message_type`, `timestamp`, `is_archived`, `archived_at`, `archive_path`.
- **`Lead`**: `name`, `company`, `phone`, `email`, `message`, `is_processed`.
- **`ActivityLog`**: `action`, `detail`, `user`, `level`, `timestamp`.

#### sourcing

- **`DomainKeyword`**: keywords для автоматической классификации позиций по `DomainType`.
- **`Attachment`**: полиморфный FK на `product` | `deal` | `message` | `quote` | `company` с DB-level `CheckConstraint` (exactly-one-FK).
- **`ImportTask`**: `celery_task_id`, `owner`, `deal`, `task_type`, `created_at` — заменяет cache-based ownership (SEC-03 fix).

#### notifications

- **`Notification`**: `user`, `type` (FK `NotificationType`), `title`, `message`, `link`, `deal` (FK), `is_read`, `created_at`.

---

## 3. API (prefix `/api/v1/`)

Маршруты регистрируются в `backend/core/urls.py` через `DefaultRouter` (ViewSets) и явные `path()` (APIViews).

### 3.1. Auth

| Метод | URL | View | Permission |
| --- | --- | --- | --- |
| POST | `auth/register/` | `RegisterView` | AllowAny |
| POST | `auth/setup-password/` | `SetupPasswordView` | AllowAny |
| POST | `auth/submit-profile/` | `SubmitProfileView` | AllowAny |
| POST | `auth/token/` | simplejwt `TokenObtainPairView` (extend_schema) | AllowAny |
| POST | `auth/token/refresh/` | simplejwt `TokenRefreshView` (extend_schema) | AllowAny |

JWT: access 30 мин, refresh 7 дней, `ROTATE_REFRESH_TOKENS=True`.

### 3.2. Accounts

| URL | ViewSet / View | Кастомные `@action` |
| --- | --- | --- |
| `accounts/companies` | `CompanyViewSet` | `verify-kyc` (POST), `upload-document` (POST), `delete-document/{doc_id}` (DELETE), `team` (GET), `invite` (POST) |
| `accounts/users` | `UserViewSet` | `change-password` (POST), `update-me` (PATCH), `me` (GET), `toggle-active` (POST), `change-role` (POST) |
| `accounts/subscriptions` | `SupplierSubscriptionViewSet` | — |
| `accounts/role-applications` | `CompanyRoleApplicationViewSet` | — |
| `accounts/me/` | `MeView` (APIView) | — |

### 3.3. Catalog

| URL | ViewSet | Кастомные `@action` / примечания |
| --- | --- | --- |
| `catalog/products` | `ProductViewSet` | `export-template` (GET), `import-excel` → см. `sourcing/import-catalog/` |
| `catalog/offers` | `SupplierOfferViewSet` | — |
| `catalog/equipment-groups` | `EquipmentGroupViewSet` | — |
| `catalog/categories` | `CategoryViewSet` | — |
| `catalog/manufacturers` | `ManufacturerViewSet` (read-only) | — |
| `catalog/domain-types` | `DomainTypeViewSet` (read-only) | — |

### 3.4. CRM

| URL | ViewSet / View | Кастомные `@action` |
| --- | --- | --- |
| `crm/deals` | `DealViewSet` | `change-stage` (POST), `export-pdf` (GET — активный Quote) |
| `crm/quotes` | `QuoteViewSet` | `generate-pdf` (POST), `send-to-client` (POST), `approve` (POST) |
| `crm/quote-items` | `QuoteItemViewSet` | — |
| `crm/messages` | `MessageViewSet` | — |
| `crm/activity-logs` | `ActivityLogViewSet` (read-only) | Фильтрация по user для non-admin |
| `crm/leads/` | `LeadCreateView` (AllowAny, публичная форма) | — |
| `crm/analytics/` | `CRMAnalyticsView` | IsManagerOrAdmin |
| `crm/analytics/dashboard/` | `DashboardAnalyticsView` | IsManagerOrAdmin |

### 3.5. Sourcing

| URL | View | Назначение |
| --- | --- | --- |
| `sourcing/requests` | `SourcingRequestViewSet` | Read-only список несопоставленных позиций |
| `sourcing/import-deal/<int:deal_id>/` | `ExcelImportView` | Excel → QuoteItem (Celery `process_excel_import`) |
| `sourcing/import-catalog/` | `CatalogImportView` (IsManagerOrAdmin) | Excel → Product PIM (Celery `process_catalog_import`) |
| `sourcing/import-status/<str:task_id>/` | `ImportStatusView` | Poll статуса через `ImportTask` |

### 3.6. Master Data, Notifications, System

| URL | ViewSet / View |
| --- | --- |
| `master-data/countries` | `CountryViewSet` (read-only) |
| `master-data/currencies` | `CurrencyViewSet` (read-only) |
| `master-data/units` | `UnitOfMeasureViewSet` (read-only) |
| `master-data/delivery-basis` | `DeliveryBasisViewSet` (read-only) |
| `notifications` | `NotificationViewSet` (read-only + mark-as-read) |
| `system-settings/` | `SystemSettingsView` |
| `analytics/page-stats/` | `PageStatsView` |
| `health/` и `api/v1/health/` | `health_check` (no auth, проверяет DB) |

### 3.7. API Docs (DEBUG only)

- `/api/schema/` — OpenAPI 3.0 schema (всегда доступен).
- `/api/docs/` — Swagger UI (только при `DJANGO_DEBUG=True`).
- `/api/redoc/` — ReDoc (только при `DJANGO_DEBUG=True`).

---

## 4. WebSocket

- **URL:** `ws://host/ws/chat/<deal_id>/` (dev), `wss://host/ws/chat/<deal_id>/` (prod через nginx).
- **Consumer:** `crm.consumers.ChatConsumer` (AsyncWebsocketConsumer).
- **Auth:** JWT через query string (`?token=...`) **или** через first-message (`{"type":"auth","token":"..."}`).
- **Room:** `chat_deal_{deal_id}`.
- **Channel layer:** Redis `redis:6379/0`.
- **Close codes:** 4001 (не аутентифицирован), 4003 (нет доступа), 4000 (generic).

Подробный словарь сообщений — [websocket-messages.md](websocket-messages.md).

---

## 5. Celery

**Broker / backend:** `redis-celery:6379/0` (отдельный инстанс от Channels).

**Очереди:**

| Очередь | Задачи |
| --- | --- |
| `default` | Общие задачи, email-уведомления, архивирование (`crm.tasks.archive_old_messages`) |
| `pdf` | WeasyPrint генерация PDF КП |
| `imports` | `sourcing.tasks.process_excel_import`, `sourcing.tasks.process_catalog_import` (time_limit 600s, soft 540s) |

**Beat:** `django_celery_beat.schedulers:DatabaseScheduler` — расписания редактируются в Django Admin.

---

## 6. Безопасность

Глобальная политика: `IsAuthenticated` (default DRF). Переопределяется в views:

| Класс | Где |
| --- | --- |
| `IsAuthenticated` | Большинство ViewSets |
| `IsAuthenticatedOrReadOnly` | Публичный каталог |
| `AllowAny` | `auth/*`, `crm/leads/`, `health/` |
| `IsManagerOrAdmin` (custom) | Analytics, CatalogImport |
| `IsOwnerOrManagerOrAdmin` (custom) | Deal/Quote детальные endpoints |
| `CustomIsAdminUser` (custom) | Admin-only operations |

**Дополнительно:**

- Excel imports: XLSX magic bytes validation (защита от подделок).
- Deal FSM: `ALLOWED_STAGE_TRANSITIONS` matrix валидирует переходы.
- Catalog signals: M2M `equipment_groups` enforced для `RAILWAY_MACHINERY` после save.
- Nginx rate limiting zones: `api_general`, `api_auth`, `ws_connect`.
- CSP, X-Frame-Options DENY, HSTS-ready headers.

Подробный аудит — [security-audit-2026-03-20.md](../../old/audits/security-audit-2026-03-20.md).

---

## 7. CI/CD

GitHub Actions (`.github/workflows/ci.yml`), 6 параллельных jobs:

1. **backend-lint** — flake8, black --check, isort --check-only.
2. **backend-test** — pytest с coverage (threshold 50%).
3. **frontend-lint** — eslint (railtechPlugin: `no-hardcoded-colors`, `no-arbitrary-text-size`); `scripts/check_i18n_symmetry.py` запускается отдельной job `i18n-symmetry`.
4. **frontend-build** — `tsc -b && vite build`.
5. **docker-build** — сборка backend и frontend images.
6. **security** — `pip audit`, `npm audit`.

**Pre-commit (husky 9 + lint-staged 15):** запускает eslint + black + isort на staged файлах. Хук инициализируется через `npm install && npx husky`.

---

## 8. Окружения

Файл `.env` (копируется из `.env.example`). Полный список переменных и fallback'ов:

| Категория | Переменные |
| --- | --- |
| DB | `DATABASE_URL` (основной) или `POSTGRES_DB/USER/PASSWORD/HOST/PORT` (fallback) |
| Django core | `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_LOG_LEVEL`, `ALLOWED_HOSTS` |
| CORS/CSRF | `CORS_ALLOWED_ORIGINS`, `CORS_ALLOW_CREDENTIALS`, `CSRF_TRUSTED_ORIGINS` |
| JWT | `JWT_ACCESS_TOKEN_LIFETIME_MINUTES`, `JWT_REFRESH_TOKEN_LIFETIME_DAYS`, `JWT_ROTATE_REFRESH_TOKENS` |
| Redis/Celery | `REDIS_URL`, `REDIS_PASSWORD`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `CELERY_TASK_ALWAYS_EAGER`, `CELERY_WORKER_CONCURRENCY` |
| Channels | `CHANNEL_LAYERS_HOST/PORT/DB` |
| Email | `EMAIL_HOST/PORT/HOST_USER/HOST_PASSWORD/USE_TLS/DEFAULT_FROM_EMAIL` |
| Frontend (build-time) | `VITE_API_URL`, `VITE_WS_URL`, `FRONTEND_URL` |
| Storage | `STATIC_ROOT`, `MEDIA_ROOT`, `MINIO_ENDPOINT/ACCESS_KEY/SECRET_KEY/PUBLIC_BUCKET/PRIVATE_BUCKET/TEMP_BUCKET/PUBLIC_DOMAIN/CONSOLE_PORT` |
| PDF | `PDF_BASE_URL` |
| Init | `SUPERADMIN_EMAIL`, `SUPERADMIN_PASSWORD`, `SEED_DATA_PATH` |

---

## 9. Тестирование

- **Backend:** `pytest` + `pytest-django`, маркеры `slow`, `integration`, `unit`. Coverage-threshold 50%.
- **Frontend:** `vitest` + `@testing-library/react` + `jsdom`.
- **Команды:** `make test` / `make test-backend` / `make test-frontend`.

---

## 10. См. также

- [master-system-document.md](master-system-document.md) — общая архитектура и топология.
- [business-logic.md](../../business/business-logic.md) — FSM и пользовательские сценарии.
- [role-model.md](../../old/misc/role-model.md) — RBAC.
- [adr/0001-admin-separation.md](../adr/0001-admin-separation.md) — разделение Unfold ↔ React Admin.
- `backend/schema.json` — OpenAPI schema. Генерируется (`manage.py spectacular`) и проверяется
  CI-джобой `api-contract` вместе с `frontend/src/api/schema.d.ts`; расхождение с кодом валит сборку.
  Ручных копий держать НЕ нужно — предыдущая, лежавшая в этом каталоге, отстала на 190+ эндпоинтов.
