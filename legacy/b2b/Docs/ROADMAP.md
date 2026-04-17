# RailTech B2B — Roadmap

**Последняя актуализация:** 2026-04-17

## Контекст

Проект реализован на ~70%. После sprint 0 (security hardening, 2026-03-20), sprint 0.5 (shadcn/ui migration, 2026-03-21) и апрельского cleanup'а проведено упрощение архитектуры фронтенда (единый `AppShell`, удаление дубликатов, унификация padding/header), а также Enterprise Hardening backend (security, cleanup, performance — коммит `114f93f`).

**Этапность деплоя:** Local dev (Neon Cloud DB) → Staging на VPS → Production.

---

## Sprint 0 — Security Hardening (ВЫПОЛНЕН 2026-03-20)

Цель: устранить критические уязвимости перед локальным тестированием. Подробности — [security-audit-2026-03-20.md](security-audit-2026-03-20.md).

- [x] IDOR fix: Excel import + task status (`sourcing/views.py`).
- [x] `ImportTask` модель — persistent task ownership (заменяет volatile cache).
- [x] Deal FSM — explicit transition matrix.
- [x] Стандартизация auth checks (`IsManagerOrAdmin` вместо `is_staff`).
- [x] ActivityLog RBAC — фильтрация по user.
- [x] WebSocket access control — проверка deal-level доступа.
- [x] XLSX magic bytes validation.
- [x] Security headers: CSP, X-Frame-Options DENY, HSTS-ready.
- [x] Nginx rate limiting: `api_general`, `api_auth`, `ws_connect`.
- [x] Split Redis: channels+cache / celery broker (2 инстанса).
- [x] Celery multi-queue: `default`, `pdf`, `imports`.
- [x] `QuoteItemHistory` — immutable audit trail.
- [x] DB indexes: `Deal.stage`, `Deal.manager`, `Deal.company`, `Product.domain_type`.
- [x] Catalog signals: M2M validation + cache invalidation.
- [x] KYC Zod validation на фронтенде.
- [x] WebSocket auth: token через first message (подготовка под security hardening).
- [x] `services.py` fix: aggregate на QuerySet.

---

## Sprint 0.5 — UI Migration to shadcn/ui (ВЫПОЛНЕН 2026-03-21)

- [x] shadcn/ui init: Tailwind v4 CSS variables, path aliases, `components.json`.
- [x] 64 shadcn-компонента установлены.
- [x] Все формы: `LoginPage`, `KYCRegistration`, `PasswordSetup`, `ProfileCompletion` → shadcn Form + Input + Select.
- [x] Все drawers: `CartDrawer`, `NotificationCenter` → shadcn Sheet + ScrollArea.
- [x] Все slide panels, modals, таблицы переведены на shadcn.
- [x] `DealSplitView` → Tabs + ScrollArea + Dialog.
- [x] Все layout shell'ы перешли на `<Sidebar>` с `collapsible="icon"`.
- [x] Dark/light mode через CSS variables (`:root` / `.dark`).
- [x] `@hookform/resolvers/zod` (стандартный) вместо кастомного.

---

## Sprint 0.6 — UI/UX Audit & Fixes (ВЫПОЛНЕН 2026-04-07)

Подробности — [ui-audit-2026-04-07.md](ui-audit-2026-04-07.md).

- [x] 4 CRITICAL бага устранены (logout, dashboard fallback, password setup error state, API error toast).
- [x] 60+ хардкод-цветов → semantic tokens (`text-success`, `bg-warning`, `bg-destructive`).
- [x] 14 raw `<table>` → shadcn `<Table>`.
- [x] 60+ arbitrary-size `text-[9px]` → Tailwind scale.
- [x] 130+ i18n-ключей добавлены, паритет ru/en восстановлен.
- [x] Custom ESLint `railtechPlugin`: `no-hardcoded-colors`, `no-arbitrary-text-size`.
- [x] Husky 9 + lint-staged 15 pre-commit hooks.
- [x] `scripts/check-i18n-sync.py` + CI step.
- [x] `AppShell` → `<Sidebar>` примитивы (убран custom `<aside>`).

---

## Sprint 0.7 — Enterprise Hardening (ВЫПОЛНЕН 2026-04-12, commit 114f93f)

Коммит: `feat: enterprise hardening — security, cleanup, performance`.

- [x] Mermaid-диаграммы (`Docs/architecture-diagrams.md`).
- [x] Swagger/ReDoc (`drf-spectacular`) — `/api/docs/`, `/api/redoc/`, `/api/schema/` (только DEBUG).
- [x] WebSocket dictionary (`Docs/websocket-messages.md`).
- [x] `django-pghistory` на Deal, Quote, QuoteItem (full audit).
- [x] `list_editable` для быстрого inline-редактирования в Unfold.
- [x] ADR-0001 — разделение Unfold ↔ React Admin.
- [x] Celery-таск архивирования чата (`crm.tasks.archive_old_messages`).

---

## Sprint 0.8 — Admin Separation & Frontend Cleanup (ВЫПОЛНЕН 2026-04-16/17)

Последние коммиты: `5dc2f4a`, `1edde99`, `2c11547`.

- [x] Phase 4 ADR-0001: `ReadOnlyInspectionMixin` на всех бизнес-моделях в Unfold.
- [x] Аварийные экшены помечены `[Emergency]`, ограничены `is_superuser`.
- [x] Декоратор `@superuser_only_action` (`core/admin_mixins.py`).
- [x] Phase 6: message history archive → S3 (Celery + Unfold).
- [x] Единый `AppShell` — удалены `AdminShell`, `ClientShell`, `ManagerShell`, `CatalogShell` (hash-based навигация с контекстом).
- [x] Удалён `QuoteBuilderGrid` (заменён унифицированным flow в `RequestDetailPage`).
- [x] Чистка неиспользуемых типов store.
- [x] Синхронизация полей frontend request store с API-схемой.
- [x] Убран дубль currency data source — единый источник `offers`.

---

## Sprint 1 — Ядро сделок (в работе)

- [ ] Quote PDF export через Celery + WeasyPrint (текущая реализация — синхронная через `QuoteViewSet.generate-pdf` @action).
- [ ] Send quote email с attach PDF.
- [ ] Approve/Reject Quote на клиентской стороне → Action Banner (UI-часть реализована, нужно добить backend flow).
- [ ] Sentry Integration (backend + frontend ErrorBoundary).

## Sprint 2 — Real-time Notifications (план)

- [ ] `NotificationConsumer` (WebSocket) — замена polling'а.
- [ ] Signal triggers на Deal/Quote/KYC status changes.
- [ ] Badge count в header, sound alerts, exponential backoff reconnect.
- [ ] Celery tasks для transactional email (quote sent, quote approved, KYC status change).

## Sprint 3 — Financial Settings & Currency (план)

- [ ] Модель `PlatformSetting` (VAT rate, default margin, min margin).
- [ ] Daily exchange rate sync (ЦБ Узбекистана) — Celery Beat.
- [ ] Currency conversion в `QuoteCalculationService`.
- [ ] Margin validation на уровне `QuoteItem.save()`.

## Sprint 4 — Documents & Advanced Catalog (план)

- [ ] Deal document management (`Attachment` model уже есть, нужен UI).
- [ ] Full-text search (PostgreSQL FTS).
- [ ] Фасетная фильтрация по domain/category/equipment group.
- [ ] Product image gallery.

## Sprint 5 — Testing & Quality (план)

- [ ] Backend coverage ≥ 60% (сейчас ≥ 50%).
- [ ] Frontend component tests (vitest + Testing Library) для ключевых страниц.
- [ ] E2E тесты (Playwright): login → create deal → import Excel → send quote → approve.

## Sprint 6 — Production Readiness (план)

- [ ] SSL через Let's Encrypt + Certbot (раскомментировать SSL в `nginx/nginx.conf`).
- [ ] HSTS headers после SSL.
- [ ] Prometheus metrics endpoint + Grafana dashboards.
- [ ] Automated PostgreSQL dump + S3 upload (Celery Beat).
- [ ] GitHub Actions deploy via SSH.

## Sprint 7 — Advanced Features (план)

- [ ] Deal templates (сохранение из существующих сделок).
- [ ] Supplier performance dashboard (delivery time, price stability, quality score).
- [ ] Multi-language: uz локаль.

---

## Deployment Pipeline

```text
Local Dev (текущий этап)
  ↓ .env + remote Neon Cloud DB
  ↓ docker compose up -d --build
  ↓ Тестирование user journeys
  ↓
Staging VPS
  ↓ docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
  ↓ SSL (Let's Encrypt), HSTS
  ↓ E2E Playwright + OWASP ZAP
  ↓
Production
  ↓ DNS switch
  ↓ Monitoring (Sentry + Prometheus)
  ↓ Backup verification
```

---

## Технический долг

- `ProductManagement` и `ProductDetail` — частично используют реальный `catalogApi`, остаточные ссылки на `data/products.ts` (пустой массив) — подчистить.
- `PlatformSetting` ещё не внедрён — VAT и margin хардкодятся в `Quote`.
- Нет HttpOnly cookie для refresh-токена (сейчас localStorage) — см. SEC-04.

---

## См. также

- [master-system-document.md](master-system-document.md) — архитектура.
- [audit-checklist.md](audit-checklist.md) — чеклист апрельского аудита.
- [adr/0001-admin-separation.md](adr/0001-admin-separation.md) — ADR по админкам.
