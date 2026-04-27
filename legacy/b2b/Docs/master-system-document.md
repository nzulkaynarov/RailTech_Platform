---
title: Master System Document — RailTech B2B Ecosystem
aliases: [ТЗ RailTech, Архитектура Платформы, MSD]
project: RailTech B2B Ecosystem
type: master-specification
version: 6.0 (Actualized)
status: Active
tags: [architecture, b2b, crm, django, react, postgresql, websockets, celery, minio]
date: 2026-04-17
---

# Master System Document: Экосистема RailTech B2B

Документ описывает полную архитектуру, бизнес-логику и технические требования универсальной B2B-платформы комплексного снабжения ООО «RailTech» (Узбекистан, г. Ташкент). Система автоматизирует цикл B2B-продаж: от лидогенерации до выставления Коммерческих предложений (КП) с учётом юнит-экономики импорта.

> Версия **6.0** отражает фактическое состояние монорепозитория на 2026-04-17 после sprints 0/0.5 (security hardening, shadcn/ui migration), cleanup 2026-04 (единый AppShell, удаление демо-кода) и ADR-0001 (разделение админок).

---

## 1. Топология системы

Фронтенд реализован как **единое SPA** (`AppShell`) с hash-based навигацией и контекстным переключателем роли (Buyer / Seller / Manufacturer). Исторические Shell-компоненты (`AdminShell`, `ClientShell`, `ManagerShell`, `CatalogShell`) объединены в `AppShell` после апрельского рефакторинга.

1. **Лендинг (`railtech.uz`)** — статический маркетинговый сайт (вне текущего репозитория).
2. **B2B SPA (`app.railtech.uz`)** — React 18 + TypeScript 5.6 + Vite 7, Tailwind v4, shadcn/ui. Точка входа — `frontend/src/layouts/AppShell.tsx`. Навигация контекстно-зависимая по активному статусу пользователя (`userStore.activeStatus`).
3. **Django API / WebSocket (`api.railtech.uz`)** — Django 5.2 + DRF + Daphne (ASGI) + Channels 4.3. Префикс REST `/api/v1/`, WebSocket `/ws/chat/<deal_id>/`.
4. **Django Unfold Admin (`/admin/`)** — инженерный инструмент для справочников и аварийных операций (ADR-0001).

---

## 2. Бизнес-логика (User Journey)

### 2.1. Изоляция данных и безопасность

Жёсткая политика `IsOwnerOrManagerOrAdmin` + override `get_queryset` во всех ViewSet:

- **CLIENT** — видит только сделки своей компании (`Deal.company == user.company_member.company`).
- **SALES_MANAGER / ACCOUNT_MANAGER** — `Q(manager=user) | Q(manager__isnull=True)`.
- **ADMIN** — полный доступ.

WebSocket-consumer (`crm.consumers.ChatConsumer`) дополнительно проверяет `deal.manager == user` или `deal.client == user` или членство в `CompanyMember` компании-владельца.

### 2.2. Domain-Aware Smart Match (Excel → PIM)

1. **Каталог (PIM)**: добавление товаров напрямую из базы кнопкой «В запрос». Массовый импорт прайс-листов — `POST /api/v1/sourcing/import-catalog/` (Celery-таск `process_catalog_import`).
2. **Импорт спецификации сделки**: `POST /api/v1/sourcing/import-deal/<deal_id>/` → Celery-таск `process_excel_import`, который:
   - Валидирует XLSX-magic bytes (защита от поддельных файлов).
   - Парсит через `pandas` + `openpyxl`.
   - Сопоставляет позиции с `Product` через PostgreSQL `pg_trgm` (Similarity > 0.3).
   - Создаёт `QuoteItem` с `product=null` для нераспознанных строк.
3. **Sourcing Hub** — менеджер вручную мапит несопоставленные `QuoteItem` через `PATCH /api/v1/crm/quote-items/{id}/`.
4. **Approve Quote** — клиент нажимает «Принять КП» (`POST /api/v1/crm/quotes/{id}/approve/`), сделка переходит в `CONTRACT_SIGNED`.

### 2.3. Юнит-экономика (Physical Landed Cost)

Все цифры хранятся как `DecimalField` + immutable audit trail `QuoteItemHistory`:

1. **FCA / базовая ставка**: `frozen_base_price` + `frozen_currency` (FK Currency).
2. **Накладные**: `logistics_cost + customs_duty` (для домена `SERVICES` игнорируются).
3. **Landed Cost**: `FCA + Logistics + Customs`.
4. **Маржирование**: `Landed Cost × (1 + margin_percent / 100) = final_price_excl_vat`.
5. **НДС**: `final_price_excl_vat × (1 + vat_rate)` — сохранён в `Quote.total_incl_vat`.

PDF КП рендерится через `WeasyPrint` по шаблону `crm/templates/quote_pdf.html` (Celery-таск в очереди `pdf`).

### 2.4. Real-time Contextual Chat (WebSockets)

`crm.consumers.ChatConsumer` (AsyncWebsocketConsumer) на Django Channels + Redis Channel Layer (порт `6379`). Изоляция по `room_group_name = chat_deal_{deal_id}`. JWT проверяется middleware или first-message (см. [websocket-messages.md](websocket-messages.md)).

Архив старых сообщений (>90 дней) — Celery-таск `crm.tasks.archive_old_messages` сохраняет JSONL в MinIO private bucket и удаляет из БД.

---

## 3. Архитектура БД (Domain-Driven Taxonomy)

### 3.1. Доменные типы (`DomainType`, seed)

1. **RAILWAY_MACHINERY** — строгий реестр, требует `equipment_groups` (M2M с `EquipmentGroup`). Enforcement — сигнал `post_save` в `catalog/signals.py`.
2. **GENERAL_GOODS** — плоский каталог, JSONB-поле `specifications`.
3. **SERVICES** — свои UoM, игнорирует логистику и таможню в расчёте.

### 3.2. Иерархия техники

`catalog.EquipmentGroup` — рекурсивная `ForeignKey('self')` с `cached_path` для быстрых выборок.

### 3.3. Ключевые модели

| Модель | Приложение | Ключевые поля |
| --- | --- | --- |
| `CustomUser` | accounts | `email` (USERNAME_FIELD), `phone`, `avatar`, `role` (FK SystemRole) |
| `Company` | accounts | `name`, `inn` (unique), `types` (M2M CompanyType), `verification_status` (FK), `trust_score`, `country` (FK), `logo` |
| `CompanyMember` | accounts | `user`, `company`, `role` (FK WorkspaceRole), `is_primary`, `is_active` |
| `SupplierSubscription` | accounts | `company` (OneToOne), `plan`, `status`, `monthly_rate`, `valid_from/until` |
| `CompanyRoleApplication` | accounts | `company`, `requested_type`, `status`, `contract_file`, `nda_file` |
| `Product` | catalog | `name`, `sku`, `domain_type`, `status`, `category`, `uom`, `manufacturer`, `equipment_groups` (M2M), `specifications` JSON |
| `SupplierOffer` | catalog | `product`, `supplier`, `base_price`, `currency`, `delivery_basis`, `stock_status`, `valid_from/until` |
| `Deal` | crm | `company`, `client`, `manager`, `stage` (FK DealStage), `title`, `notes` + pghistory |
| `Quote` | crm | `deal`, `version`, `status`, `subtotal_excl_vat`, `vat_amount`, `total_incl_vat`, `pdf_file`, `approved_at` + pghistory |
| `QuoteItem` | crm | `quote`, `product`, `offer`, `quantity`, `frozen_base_price`, `logistics_cost`, `customs_duty`, `margin_percent`, `landed_cost`, `final_price_excl_vat` + pghistory |
| `QuoteItemHistory` | crm | immutable snapshot (`change_reason`, `created_at`) |
| `Message` | crm | `deal`, `sender`, `text`, `timestamp`, `is_archived`, `archive_path` |
| `Attachment` | sourcing | полиморфный FK (exactly-one FK enforcement через `CheckConstraint`) |
| `ImportTask` | sourcing | `celery_task_id`, `owner`, `deal`, `task_type` — заменяет volatile cache-ownership |

### 3.4. Ролевая модель (RBAC)

| Слой | Модели | Коды из seed |
| --- | --- | --- |
| **Системные роли** | `SystemRole` (FK `CustomUser.role`) | ADMIN, SALES_MANAGER, ACCOUNT_MANAGER, CLIENT, GUEST |
| **Workspace-роли** | `WorkspaceRole` (FK `CompanyMember.role`) | OWNER, ACCOUNTANT, PROCUREMENT_MANAGER |
| **Типы компании** | `CompanyType` (M2M `Company.types`) | CLIENT, MANUFACTURER, SUPPLIER, LOGISTICS_PROVIDER |
| **KYC** | `VerificationStatus` (FK `Company.verification_status`) | L1_UNVERIFIED, PROFILE_SUBMITTED, L2_VERIFIED, L3_CONTRACTED, REJECTED |

---

## 4. Технический стек

### Backend

- **Runtime:** Python 3.13 (docker image `python:3.13-slim`).
- **Core:** Django 5.2+, DRF 3.16+, `djangorestframework-simplejwt` 5.5+, `django-cors-headers` 4.9+, `django-filter` 25.2+.
- **ASGI / Real-time:** Daphne 4.2+, `channels` 4.3+, `channels-redis` 4.3+.
- **Async:** Celery 5.6+ (очереди `default`, `pdf`, `imports`), `django-celery-beat` 2.9+.
- **DB:** PostgreSQL (Neon Cloud), `psycopg2-binary`, `django-db-connection-pool[postgresql]`.
- **Storage:** MinIO (S3-совместимое) через `django-storages[s3]` + `boto3`; fallback — локальная ФС.
- **Data processing:** pandas 2.2+, openpyxl 3.1.5+, XlsxWriter 3.2+.
- **PDF:** WeasyPrint 68+.
- **Admin:** `django-unfold` 0.88+, `django-import-export` 4.4+, `django-formtools` 2.5+.
- **API docs:** `drf-spectacular` 0.29+ (только в DEBUG — `/api/docs/`, `/api/redoc/`, `/api/schema/`).
- **Audit:** `django-pghistory` 3.9+ + `django-pgtrigger` 4.9+ (Deal, Quote, QuoteItem).

### Frontend

- **Core:** React 18.3, TypeScript 5.6, Vite 7, Tailwind CSS v4 (oklch, `@tailwindcss/vite`).
- **UI:** shadcn/ui (64 компонента в `src/components/ui/`) + Radix/Base UI + lucide-react.
- **State:** Zustand 5 (9 сторов: `auth`, `user`, `cart`, `currency`, `domain`, `flow`, `loading`, `task`, `theme`). `persist` middleware на `auth` и `theme`.
- **Data:** `@tanstack/react-query` 5.90+ + axios 1.13.
- **Formы:** react-hook-form 7.71 + zod 4.3 + `@hookform/resolvers`.
- **i18n:** i18next 25.8 + react-i18next 16.5 (ru, en — `scripts/check_i18n_symmetry.py` проверяет паритет).
- **Utilities:** decimal.js (финансовая точность), recharts (графики), sonner (toasts), date-fns, next-themes.

### Инфраструктура

- **Dev stack:** `docker compose up -d --build` — 8 контейнеров (см. README §«Сервисы в Docker»).
- **Prod stack:** `docker-compose.prod.yml` добавляет `nginx:stable-alpine` (reverse proxy, SSL-ready) + Gunicorn/Uvicorn-workers для backend (4 воркера).
- **CI/CD:** GitHub Actions (6 jobs): backend-lint (flake8/black/isort), backend-test (pytest, coverage ≥ 50%), frontend-lint (eslint + i18n sync), frontend-build (vite), docker-build, security (pip-audit + npm audit).
- **Pre-commit:** husky 9 + lint-staged 15; локальный hook + кастомные ESLint-правила `railtechPlugin` (`no-hardcoded-colors`, `no-arbitrary-text-size`).

---

## 5. Потоки данных

### 5.1. Excel-импорт сделки

```text
Client → POST /api/v1/sourcing/import-deal/{deal_id}/  (multipart)
        ↓
ExcelImportView → XLSX magic bytes check → base64 → Celery
        ↓
process_excel_import (queue=imports)
        ↓
pandas parse → pg_trgm similarity match → QuoteItem batch insert
        ↓
ImportTask.status = SUCCESS → poll via GET /api/v1/sourcing/import-status/{task_id}/
```

### 5.2. Генерация КП

```text
Manager → POST /api/v1/crm/quotes/{id}/generate-pdf/
        ↓
Celery queue=pdf: WeasyPrint(quote_pdf.html) → MinIO private bucket
        ↓
Quote.pdf_file = presigned URL (15-мин подпись)
        ↓
Manager → POST /api/v1/crm/quotes/{id}/send-to-client/
        ↓
Deal.stage = QUOTE_SENT, email с PDF (Celery queue=default)
        ↓
Client → POST /api/v1/crm/quotes/{id}/approve/
        ↓
Deal.stage = CONTRACT_SIGNED, Quote.approved_at = now()
```

### 5.3. KYC-верификация

```text
Register → POST /api/v1/auth/register/ (CustomUser is_active=False)
        ↓
Email с /setup-password?uid=X&token=Y (в DEBUG — в логах backend)
        ↓
POST /api/v1/auth/setup-password/ (is_active=True)
        ↓
POST /api/v1/accounts/companies/{id}/upload-document/ (MinIO private)
        ↓
KYC-менеджер (React Admin) → POST /api/v1/accounts/companies/{id}/verify-kyc/
        ↓
accounts.services.verify_company_kyc → verification_status = L2_VERIFIED
```

---

## 6. Что где живёт

```text
backend/core/               settings, URLs, ASGI, Celery, middleware, permissions
backend/accounts/           CustomUser, Company, CompanyMember, KYC, Subscriptions, RoleApplication
backend/catalog/            Product, Category, EquipmentGroup, SupplierOffer (PIM)
backend/crm/                Deal FSM, Quote, QuoteItem, Message, Lead, ActivityLog, consumers.py (WS)
backend/sourcing/           Excel import Celery tasks, ImportTask, Attachment, DomainKeyword
backend/master_data/        Country, Currency, UnitOfMeasure, DeliveryBasis
backend/notifications/      Notification, NotificationType
backend/*/services.py       ВСЯ бизнес-логика (см. CLAUDE.md IRON RULE 8 и ADR-0001)

frontend/src/api/           10 axios-клиентов: accountsApi, catalogApi, crmApi, masterDataApi,
                            notificationsApi, sourcingApi, systemApi, dashboardApi, client.ts, types.ts
frontend/src/layouts/       AppShell.tsx (единственный shell)
frontend/src/pages/         20 страниц верхнего уровня
frontend/src/components/ui/ 64 shadcn-компонента
frontend/src/hooks/         useAccounts, useCatalog, useCRM, useMasterData, useSystemSettings, usePageStats, use-mobile
frontend/src/store/         9 Zustand-сторов
frontend/src/i18n/locales/  ru.json, en.json (1679+ ключей, синхронизированы)

Docs/                       Вся проектная документация (этот документ + 13 спутников)
nginx/nginx.conf            Production reverse proxy (SSL-ready)
```

---

## 7. См. также

- [technical-specification.md](technical-specification.md) — детали стека, моделей, API.
- [business-logic.md](business-logic.md) — пользовательские сценарии.
- [role-model.md](role-model.md) — RBAC в деталях.
- [architecture-diagrams.md](architecture-diagrams.md) — Mermaid-диаграммы.
- [interface-architecture.md](interface-architecture.md) — UI-архитектура.
- [ROADMAP.md](ROADMAP.md) — план и статус спринтов.
- [adr/0001-admin-separation.md](adr/0001-admin-separation.md) — разделение Unfold ↔ React.
- [../CLAUDE.md](../CLAUDE.md) — жёсткие правила для AI-агентов и разработчиков.
