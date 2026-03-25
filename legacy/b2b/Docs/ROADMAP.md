# RailTech B2B Ecosystem — Roadmap v2 (Post-Audit)

## Контекст

Проект реализован на ~60%. После полного аудита безопасности и архитектуры (2026-03-20) были выявлены и исправлены критические уязвимости. Данный Roadmap учитывает необходимость Security-First подхода: мониторинг и безопасность — до первого деплоя, а не после.

**Этапность:** Локальное тестирование с удалённой БД (Neon Cloud) → Staging на VPS → Production.

---

## Sprint 0: Security Hardening (ВЫПОЛНЕН 2026-03-20)

**Цель:** Устранить критические уязвимости, подготовить к безопасному локальному тестированию.

### Выполнено:
- [x] IDOR fix: Excel import + task status (sourcing/views.py)
- [x] ImportTask model — persistent task ownership (заменяет volatile cache)
- [x] Deal stage FSM — explicit transition matrix
- [x] Стандартизация auth checks (`is_manager_or_admin` вместо `is_staff`)
- [x] ActivityLog RBAC — фильтрация по user
- [x] WebSocket access control — проверка deal-level доступа
- [x] XLSX magic bytes validation — защита от malicious uploads
- [x] Security headers: CSP, X-Frame-Options DENY, HSTS-ready
- [x] Nginx rate limiting: api_general, api_auth, ws_connect zones
- [x] Split Redis: channels+cache / celery broker (2 инстанса)
- [x] Celery multi-queue: default+pdf / imports (2 worker'а)
- [x] QuoteItemHistory — immutable audit trail для финансов
- [x] DB indexes: Deal.stage, Deal.manager, Deal.company, Product.domain_type
- [x] Catalog signals: M2M validation + cache invalidation
- [x] KYC form Zod validation (frontend)
- [x] WebSocket auth: token через first message (не query string)
- [x] services.py fix: aggregate на QuerySet, не list

## Sprint 0.5: UI Migration to shadcn/ui (ВЫПОЛНЕН 2026-03-21)

**Цель:** Полная миграция frontend на shadcn/ui — единый дизайн-система.

### Выполнено:
- [x] shadcn/ui init: Tailwind v4 CSS variables, path aliases, components.json
- [x] 27 shadcn компонентов установлены (Button, Badge, Card, Form, Sheet, Dialog, Sidebar, etc.)
- [x] Все формы: LoginPage, KYCRegistration, PasswordSetup, ProfileCompletion → shadcn Form + Input + Select
- [x] Все drawers: CartDrawer, NotificationCenter → shadcn Sheet + ScrollArea
- [x] Все slide panels: UserSlidePanel, NomenclatureSlidePanel → shadcn Sheet + Form
- [x] Все modals: ProductDetailModal, ExcelUploadModal → shadcn Dialog
- [x] Все таблицы: QuoteBuilderGrid, AdminUsers, SourcingGrid → shadcn Table + DropdownMenu + Dialog
- [x] DealSplitView → shadcn Tabs + ScrollArea + Dialog
- [x] Все layout shells → shadcn Sidebar (ClientShell, ManagerShell, AdminShell)
- [x] CatalogShell → shadcn Button + DropdownMenu + Avatar (top navbar)
- [x] Dark/light mode через CSS variables (:root / .dark)
- [x] `@hookform/resolvers/zod` (стандартный) вместо кастомного resolver

---

## Sprint 1: Ядро сделок (Недели 1-2)

**Цель:** Клиент получает КП, одобряет → менеджер отправляет.

### 1.1 Quote PDF Export
- Celery-таск `generate_quote_pdf` через WeasyPrint
- `GET /api/v1/crm/deals/{id}/export-pdf/` → PDF blob
- HTML-шаблон КП: `crm/templates/quote_pdf.html`

### 1.2 Send Quote to Client
- `POST /api/v1/crm/deals/{id}/send-quote/`
- Quote status → SENT, Deal stage → QUOTE_SENT (FSM validated)
- Notification + email с PDF (Celery task)
- Frontend: кнопка «Отправить КП» (manager/admin only)

### 1.3 Approve/Reject Quote
- `POST /api/v1/crm/deals/{id}/approve-quote/`
- `POST /api/v1/crm/deals/{id}/reject-quote/`
- Клиент видит Action Banner с кнопками
- Approve → Deal.stage = CONTRACT_SIGNED, Quote.approved_at = now()

### 1.4 Sentry Integration (Sprint 0.5)
- Backend: `sentry-sdk[django]` + DSN config
- Frontend: `@sentry/react` + ErrorBoundary integration
- **Не ждём Sprint 6 — мониторинг нужен с первого деплоя**

---

## Sprint 2: Real-time Notifications (Недели 3-4)

**Цель:** Push-уведомления через WebSocket, отказ от polling.

### 2.1 NotificationConsumer
- WebSocket consumer: `ws/notifications/`
- JWT auth через first message (как в ChatConsumer)
- Signal triggers: Deal/Quote/KYC status changes

### 2.2 Frontend WebSocket Integration
- `notificationStore` (Zustand) с WebSocket state
- Badge count в header, sound alerts
- Exponential backoff reconnect

### 2.3 Email Notifications
- Celery tasks для transactional emails
- Templates: quote sent, quote approved, KYC status change

---

## Sprint 3: Financial Settings & Currency (Недели 5-6)

**Цель:** Настраиваемые финансовые параметры, мульти-валюта.

### 3.1 PlatformSetting Model
- VAT rate, default margin, min margin constraint
- Admin UI через Django Unfold

### 3.2 Exchange Rate Sync
- Celery Beat: daily sync с ЦБ Узбекистана
- Currency conversion в QuoteCalculationService

### 3.3 Margin Validation
- Min/max margin constraints на уровне QuoteItem.save()
- Warning UI при выходе за пределы

---

## Sprint 4: Documents & Advanced Catalog (Недели 7-8)

**Цель:** Управление документами, продвинутый каталог.

### 4.1 Deal Document Management
- Upload/download через Attachment model
- Grouping by type: КП, Договор, Акт, Счёт

### 4.2 Advanced Catalog Search
- Full-text search (PostgreSQL FTS)
- Фасетная фильтрация по domain, category, equipment group
- Product image gallery

---

## Sprint 5: Testing & Quality (Недели 9-10)

**Цель:** 60% coverage, CI green.

### 5.1 Backend Unit Tests
- Auth: login, refresh, permissions
- Financial: QuoteCalculationService, Landed Cost formula
- RBAC: get_queryset filtering, object-level permissions
- FSM: stage transitions (allowed + denied)

### 5.2 Frontend Component Tests
- Vitest + React Testing Library
- LoginPage, ProtectedRoute, QuoteBuilderGrid

### 5.3 E2E Tests
- Playwright: full deal lifecycle
- Login → Create Deal → Import Excel → Send Quote → Approve

---

## Sprint 6: Production Readiness (Недели 11-12)

**Цель:** SSL, мониторинг, деплой на VPS.

### 6.1 SSL/HTTPS
- Let's Encrypt + Certbot в docker-compose
- Nginx HTTP→HTTPS redirect (раскомментировать в nginx.conf)
- HSTS headers (раскомментировать в settings.py)

### 6.2 Monitoring
- Prometheus metrics endpoint
- Grafana dashboards: API latency, Celery queue depth, error rate

### 6.3 API Documentation
- drf-spectacular (OpenAPI 3.0)
- Swagger UI на `/api/v1/docs/`

### 6.4 VPS Deployment
- Docker Compose production profile
- Automated backup: daily PostgreSQL dump + S3 upload
- GitHub Actions: build → test → deploy via SSH

---

## Sprint 7: Advanced Features (Недели 13-14)

**Цель:** Бизнес-фичи для масштабирования.

### 7.1 Deal Templates
- Сохранение шаблонов КП из существующих сделок
- Быстрое создание deal из template

### 7.2 Supplier Performance Dashboard
- Метрики: delivery time, price stability, quality score
- Рейтинг поставщиков для менеджеров

### 7.3 Multi-language (i18n)
- i18next: ru, uz, en
- Backend: Accept-Language middleware
- Каталог: мультиязычные product names

---

## Deployment Pipeline

```
Local Dev (текущий этап)
  ↓ .env + remote Neon DB
  ↓ docker-compose up (без local-db profile)
  ↓ Тестирование всех user journeys
  ↓
Staging VPS
  ↓ docker-compose up + SSL
  ↓ E2E тесты (Playwright)
  ↓ Security scan (OWASP ZAP)
  ↓
Production
  ↓ DNS switch
  ↓ Monitoring (Sentry + Prometheus)
  ↓ Backup verification
```
