---
title: Master System Document — RailTech B2B (Карта системы)
aliases: [ТЗ RailTech, Архитектура Платформы, MSD, Карта системы]
project: RailTech B2B Ecosystem
type: system-map
version: 7.0 (Карта системы / living-doc)
status: Active
tags: [architecture, b2b, crm, django, react, postgresql, websockets, celery, ai]
date: 2026-07-20
head: 8b89b17
---

# Master System Document — RailTech B2B · Карта системы (v7.0)

> **Это living-doc, а не энциклопедия.** Задача документа — дать актуальную карту системы «за 10
> минут» и увести к живым источникам истины. При ЛЮБОМ расхождении верь коду и ADR, а не этому
> тексту. Каждый раздел помечает свой **источник истины**; здесь — только выжимка, без дублирования.
>
> Мировая практика (короткий living-doc + ADR вместо текст-монстра) заменила прежнюю
> версию-энциклопедию v6.0 (апрель 2026, устарела и содержала неверные факты — Django 5.2,
> ручной context-switcher, роли ACCOUNT_MANAGER). Полный текст v6.0 заморожен в архиве:
> [`Docs/old/architecture/master-system-document-v6-2026-04.md`](../../old/architecture/master-system-document-v6-2026-04.md).
>
> **Первичные каноны (обновляются раньше этого файла):** `CLAUDE.md` (корень репо — стек,
> топология, правила), ADR [`0001`](../adr/0001-admin-separation.md)…[`0006`](../adr/0006-wedge-loop-and-entitlements.md),
> актуальные спеки в [`Docs/dev/specs/`](../specs/), последние
> [`Docs/dev/ops/session-handoff-*`](../ops/). Схема API: [`schema.json`](schema.json) +
> сгенерированный `frontend/src/api/schema.d.ts`.
>
> HEAD на момент рефреша: `8b89b17` (post PR #351). Миграционные головы: `accounts/0039`, `crm/0062`.

---

## 1. Что это за продукт

B2B-маркетплейс комплексного снабжения железнодорожной отраслью (Узбекистан, Ташкент). Домены
товаров: **железнодорожная техника, general goods, услуги** — снабжение, квотирование (КП), CRM.

**Wedge-продукт (клин, ADR-0006):** цикл **заявка → КП → контракт → инвойс**. AI-ускорение этого
цикла — монетизируемый ров (moat), закрытый за entitlement/подпиской.

> Источник истины: [ADR-0006 «wedge loop + entitlements»](../adr/0006-wedge-loop-and-entitlements.md);
> бизнес-сценарии — [`Docs/business/business-logic.md`](../../business/business-logic.md).

---

## 2. Технический стек (кратко)

| Слой | Технологии |
|---|---|
| **Backend** | Django **6.0**, DRF, Daphne (ASGI), Channels (WebSocket), Celery + Redis |
| **DB** | PostgreSQL **17** (self-hosted; Neon Cloud ретайрнут 2026-06-19) |
| **Frontend** | React 18, TypeScript 5.6, Vite 7, Tailwind CSS 4 (oklch), shadcn/ui, Zustand 5, React Query 5, i18next (RU/EN) |
| **AI** | Anthropic API, модель `claude-opus-4-8` |
| **PDF / Excel** | WeasyPrint (off-thread через Celery) · pandas + openpyxl |
| **Storage** | Django `FileSystemStorage` по умолчанию (== прод); MinIO — **opt-in** через compose-профиль `with-minio` |
| **Auth** | JWT (simplejwt): access 30 мин, refresh 7 д в HttpOnly-cookie, ротация; login-lockout; опциональный 2FA (TOTP) |
| **Инфра** | Docker Compose (dev) · **Caddy** — прод-edge (TLS/CSP/XFF) · nginx только *внутри* frontend-контейнера отдаёт SPA · GitHub Actions CI + self-hosted deploy-runner · Sentry |

> Источник истины: `CLAUDE.md` §«Tech Stack»; версии backend-зависимостей — `backend/requirements.txt`
> (генерируемый hashed-lock, INF-05). Устаревшие факты v6.0, которые НЕ повторять: Django 5.2, Neon
> Cloud, MinIO по умолчанию, nginx как прод reverse-proxy.

---

## 3. Топология (прод)

- **app-VPS** — Docker-стек (backend/Daphne, celery-workers, redis×2) + host-**Caddy** как edge
  (владеет TLS, CSP-заголовками, перезаписью X-Forwarded-For). Домен: `b2b.railtech.uz`; SPA
  раздаётся из `/var/www/railtech-b2b`. Caddy-конфиг применяется **вручную** из фрагмента
  `deploy/caddy/b2b.railtech.uz.caddy`.
- **DB-VPS** — выделенный сервер PostgreSQL 17 (private `10.0.0.2`, из app-VPS `10.0.0.3` по
  приватной LAN хостера, интерфейс **`ens8`** — НЕ WireGuard; `sslmode=require`). Нативная apt/PGDG
  установка, не Docker. Ежедневный `pg_dump` cron → `/var/backups/railtech-db/` (14 дней).
- **Dev** — `docker compose up -d --build`; локальный Postgres 17 добавляется через
  gitignored `docker-compose.override.yml`. Два Redis: `redis:6379` (Channels) и
  `redis-celery:6380` (Celery broker+results).
- **Staging** — пока не существует (нужны DNS + GitHub-environment + Caddy-блок); nightly
  Playwright e2e бьёт по проду prod-safe спеками.

> Источник истины: `CLAUDE.md` §«Production Deployment» / §«Database» / §«Docker Services»;
> оперативка — [`Docs/dev/ops/RUNBOOK-b2b-vps.md`](../ops/RUNBOOK-b2b-vps.md); prod-факты —
> memory `reference-vps-b2b`.

---

## 4. Домены (Django-приложения)

| App | Владеет | Ключевые модели |
|---|---|---|
| `accounts` | Пользователи, компании, членство, роли, KYC, подписки, entitlements | `CustomUser`, `Company`, `CompanyMember`, `CompanyRole`, `OperatorRole`, `SupplierSubscription`, `CompanyEntitlement`, `Contact` |
| `catalog` | PIM: товары и предложения | `Product`, `Category`, `EquipmentGroup`, `SupplierOffer` |
| `crm` | Wedge-цикл: сделки, КП, договоры, биллинг, чат | `Deal`, `DealSellerRouting`, `Quote`, `QuoteItem`, `Contract`, `Fulfillment`, `Invoice`/`Act`/`Payment`, `Message`, `Lead`, `ActivityLog` |
| `sourcing` | Импорт (Excel/AI), вложения | `Attachment`, `ImportTask`, `AIJob`, `DomainKeyword` |
| `master_data` | Справочники (`AbstractLookup`) | `Country`, `Currency`, `UOM`, `DeliveryBasis` |
| `notifications` | Уведомления, email-аудит | `Notification`, `EmailLog`, `EmailTemplate` |

Модели больших приложений разложены по пакетам (`{crm,accounts,catalog}/models/`), FK внутри
приложения — строковыми ссылками (`"app.Model"`). Вся бизнес-логика — в `<app>/services/`
(IRON RULE 8: `views`/`admin` — тонкие обёртки).

> Источник истины: `CLAUDE.md` §«Project Structure»; раскладка сервисов — тот же файл;
> детальные поля моделей — [`schema.json`](schema.json) и код `backend/<app>/models/`.

---

## 5. Ключевые потоки

### 5.1. Wedge-цикл: заявка → КП → контракт → инвойс

**Deal FSM:** `DRAFT → KYC_PENDING → RFQ_OPEN → SOURCING → CALCULATING → QUOTE_SENT →
CONTRACT_SIGNED → CLOSED_WON / CLOSED_LOST` (переходы в `ALLOWED_STAGE_TRANSITIONS`,
`crm/services/deals.py`; терминальные состояния переоткрываемы менеджером).

Автопереходы (ADR-0006 Move 0): отправка КП → `QUOTE_SENT`; клиент принимает КП →
`CONTRACT_SIGNED` (+ материализуется `Contract`); двусторонняя подпись договора → `CLOSED_WON`
(диспатчит `auto_invoice_on_closed_won`).

### 5.2. Multi-seller routing (keystone)

Заявка веерно рассылается продавцам через `DealSellerRouting` (владение per-seller-company,
«скрытая конкуренция»); querysets продавца скоупятся по `seller_visible_deal_ids`;
claim/assignment — в `crm/services/assignment.py`.

> Источник истины: [ADR-0003 «multi-tenant admin planes» §5](../adr/0003-multi-tenant-admin-planes.md).

### 5.3. Гейты: KYC-этаж + entitlements

- **KYC-этаж (ADR-0006 Phase E):** ниже L2 — только регистрация, просмотр и DRAFT-заявка. Buyer
  submit → `KYC_REQUIRED_TO_SUBMIT`; seller send/export требует L2+ (`SELLER_KYC_REQUIRED`,
  проверяется ДО `SUBSCRIPTION_REQUIRED`). Verified-коды = `{L2_VERIFIED, L3_CONTRACTED}` (нет
  `L3_VERIFIED`). Источник: `accounts/services/kyc.py`.
- **Entitlement-слой (ADR-0006 Move 4):** коды `FeatureKey` в `accounts/constants.py`
  (`quote.send`, `quote.export`, `ai.match`, `ai.draft`, `ai.preflight`, `roles.custom`).
  `FREE_FLOOR_FEATURES = {ai.match, ai.preflight}`; `SUBSCRIPTION_BASELINE_FEATURES` даётся
  операционной `SupplierSubscription`; явные `CompanyEntitlement`-строки ПЕРЕОПРЕДЕЛЯЮТ (promo-grant
  или DEMO-downgrade → watermarked PDF). Сервис: `accounts/services/entitlements.py`.

### 5.4. AI-слой (ARCH-01) — 202 + Celery, никогда в request-path

**Ни один LLM-вызов не выполняется в HTTP-обработчике.** 8 интерактивных AI-эндпоинтов
валидируют синхронно (клампы, видимость, 503 `AI_DISABLED`), затем ставят `sourcing.run_ai_job`
на выделенную Celery-очередь `ai` (свой сервис `celery-worker-ai`; основной воркер `ai` НЕ
слушает) и отвечают **202 {task_id}**; SPA поллит `GET /api/v1/sourcing/ai-status/<task_id>/`
(IDOR-guard по строке `AIJob`) через `frontend/src/lib/aiJob.ts`. `run_ai_job` — **single-attempt**
(`max_retries=0`: хендлеры платные, `draft_quote` пишет и списывает кредит).

Фичи: `match`/`preflight`/`extract`/`compose` (sourcing), `chat_reply`/`quote_diff`/`draft_quote`
(crm), `enrich` (catalog). Единая фабрика клиента `_client()` в `sourcing/services_ai.py`
(`AI_REQUEST_TIMEOUT`=60s). AI-сбои в сервисах — логируемые no-op, никогда не 500 в лицо.

> Источник истины: `CLAUDE.md` §«AI layer (ARCH-01)» и §«AI calls» (конвенция).

### 5.5. КП-конструктор (grid)

Основное рабочее место продавца — inline-грид в `DealQuotePage` (`frontend/src/components/Admin/
QuoteBuilderGrid.tsx`, контекст `frontend/src/components/QuoteBuilder/`). Свойства:

- **Секции / заметки / опциональные позиции** (одна модель, Odoo-стиль `display_type`, миграция
  `crm/0062`): `QuoteItem.display_type` (`ITEM` default / `SECTION` / `NOTE`) + `is_optional` +
  `position`. `SECTION`/`NOTE` — презентационные (без цен); optional-`ITEM` НЕ входит в итоги
  (пропуск в `recalculate_quote`). Перемещение строк — кнопки ↑/↓ (меняют `position`; drag-n-drop
  сознательно не делаем — конфликт с виртуализацией).
- **Виртуализация** списка позиций (`@tanstack/react-virtual`, `useVirtualizer`) — КП на 30–300
  строк; `QuoteItemViewSet` имеет `pagination_class = None` (пагинация не режет большие КП).
- **Юнит-экономика:** SAP-style каскадные charges (`crm/services/charges.py`), `DecimalField` на
  бэке + `decimal.js` на фронте, аудит `QuoteItemHistory`, optimistic locking
  (`core/optimistic_locking.py`). Валюта КП зафиксирована на **UZS** (UZS-canonical — не откатывать
  к USD).

> Источник истины: спеки [`spec-quote-builder-ux-refactor-2026-07-14.md`](../specs/spec-quote-builder-ux-refactor-2026-07-14.md),
> [`spec-quote-builder-workspace-implementation-2026-07-14.md`](../specs/spec-quote-builder-workspace-implementation-2026-07-14.md),
> [`spec-quote-sections-hygiene-2026-07-17.md`](../specs/spec-quote-sections-hygiene-2026-07-17.md).

### 5.6. Публичный КП

Неаутентифицированный `GET /api/v1/public/quotes/<token>/` (throttle 30/мин; только замороженные
SENT-КП). Промах PDF-кэша → `crm.tasks.render_document_pdf` + **202 + Retry-After**; браузер видит
самообновляющийся interstitial. SPA-страницы перед этим нет by design.

### 5.7. Real-time чат (WebSocket)

`crm.consumers.ChatConsumer` на Channels + Redis (`6379`), изоляция по deal-room, JWT в
middleware/first-message. Архив старых сообщений — `crm.tasks.archive_old_messages`.

> Источник истины: [`websocket-messages.md`](websocket-messages.md).

---

## 6. Роли и права (4 слоя, не взаимозаменяемы)

| Слой | Где | Что | Коды |
|---|---|---|---|
| **SystemRole** | `CustomUser.role` | Платформенная роль | только `ADMIN` (Platform Operator, без членств) и `USER` — **никаких `ACCOUNT_MANAGER`/`SALES_MANAGER` как SystemRole** |
| **OperatorRole** | `CustomUser.operator_role` | Гранулярные суб-роли оператора (ADR-0004 G1) | `SUPPORT`, `KYC_OFFICER`, `BILLING_OPERATOR`, `MODERATOR`, `SUPER_OPERATOR` + audited break-glass |
| **CompanyRole** | per-tenant | Права доступа к КП | `quote.build/send/view_cost_margin/edit_pricing/review/approve_final` (внутр. цепочка) vs `quote.approve` (buyer accept) |
| **WorkspaceRole** | `CompanyMember.role` | **Только label/derivation** (депрекация ADR-0005 Phase E U3 завершена, PR #255 — бизнес-authz не ветвится на WorkspaceRole) | `OWNER` («Администратор компании»), SALES_MANAGER, LOGIST… + инвариант never-orphan (≥1 активный OWNER) |

Плюс per-member capabilities `CompanyMember.can_sell` / `can_buy`. Платформенный оператор не
может стать `CompanyMember` и не совершает buy/sell/sign/pay (`ADMIN_VIEWER_CANNOT_ACT`).

> Источник истины: [ADR-0002](../adr/0002-role-responsibilities.md),
> [ADR-0003](../adr/0003-multi-tenant-admin-planes.md), [ADR-0004](../adr/0004-three-admin-planes-core.md);
> каталог кодов — `accounts/constants.py`; дизайн — [`spec-rbac`](../specs/rbac-roles-design-2026-06-25.md).

---

## 7. Frontend (навигация и оболочки)

- **2 оболочки, и только:** `AppShell` (все пользователи компаний; контекст Buyer/Seller —
  **page-derived**, ручной context-switcher РЕТАЙРНУТ в ADR-0005 Phase C) и `PlatformAdminShell`
  (платформенные операторы). Обе — на shadcn `<Sidebar collapsible="icon">`.
- **Единая capability-driven навигация (ADR-0005):** `buildNavigation(capabilities)` в
  `frontend/src/config/navigation.tsx`; `/me` отдаёт объект `capabilities` (kyc_level, can_buy/
  can_sell, subscription, права CompanyRole, operator_permissions). Тиры T0 (pre-KYC:
  Dashboard+Catalog) / T1 (KYC L2) / T2 (подписка). Пункты СКРЫВАЮТСЯ, не дизейблятся.
- **Routing — гибрид, БЕЗ React Router:** auth-маршруты (`/`, `/register`, `/setup-password`)
  через `useAuthRoute()`; остальное — hash-навигация (`#dashboard`, `#deal-quote/{id}`, `#admin-*`,
  `#settings`). `react-router-dom` удалён из package.json (2026-07-16).
- **Settings Hub** — единая `SettingsPage` (профиль, безопасность/2FA, компания, документы,
  дефолты, нумерация, шаблоны, команда), секции гейтятся `buildSettingsSections(gate)`.

> Источник истины: [ADR-0005 «unified navigation»](../adr/0005-unified-navigation.md); `CLAUDE.md`
> §«Key Architecture Decisions» и §«Project Structure» (frontend).

---

## 8. Где что искать

```text
backend/core/               settings, urls, asgi, celery + cross-cutting (csp, idempotency,
                            optimistic_locking, versioning, audit, validators)
backend/accounts/           пользователи, компании, членство, роли, KYC, подписки, entitlements
backend/catalog/            PIM: Product, Category, EquipmentGroup, SupplierOffer
backend/crm/                Deal FSM, Quote/QuoteItem, Contract, Fulfillment, биллинг, чат
backend/sourcing/           импорт (Excel + AI: services_ai*.py, tasks_ai.py), ImportTask, AIJob
backend/master_data/        справочники (AbstractLookup)
backend/notifications/      уведомления, EmailLog, EmailTemplate
backend/*/services/         ВСЯ бизнес-логика (IRON RULE 8, ADR-0001)

frontend/src/api/           axios-клиент (JWT-интерцептор + refresh-mutex), schema.d.ts (генерир.)
frontend/src/store/         8 Zustand-сторов (auth, user, cart, task, theme, currency, domain, loading)
frontend/src/layouts/       AppShell.tsx + PlatformAdminShell.tsx — ЕДИНСТВЕННЫЕ 2 оболочки
frontend/src/config/        navigation.tsx (buildNavigation), settingsSections.tsx
frontend/src/pages/         ~40 страниц (вкл. Admin*, Dashboard, DealQuotePage, Settings…)
frontend/src/components/    ui (shadcn), Admin (QuoteBuilderGrid), CRM, Settings, Sourcing…
frontend/src/i18n/locales/  ru.json, en.json (паритет проверяет CI i18n-symmetry)

deploy/caddy/               фрагмент прод-edge Caddy (применяется вручную)
Docs/                       документация по аудиториям (карта: Docs/README.md)
```

> Полная и всегда более свежая раскладка — `CLAUDE.md` §«Project Structure».

---

## 9. Celery, окружение, тесты (указатели)

- **Celery:** два воркера — `celery-worker` (`default,pdf,imports`) + `celery-worker-ai` (`ai`).
  Все document-PDF рендерятся off-thread (ARCH-03, request-path отвечает 202). Beat —
  `DatabaseScheduler`. **Не авто-релоадится** — после model/migration change перезапускать воркеры.
- **Окружение:** конфиг из `.env`; прод-`.env` рендерится из GitHub-секретов heredoc'ом в
  `deploy-b2b.yml` (ручные правки на VPS перетираются). Ключевые флаги: `DRF_NUM_PROXIES`,
  `CSP_REPORT_ONLY`, `PRODUCTION`, `ANTHROPIC_API_KEY` (пусто = AI off).
- **Тесты/CI:** pytest (`--create-db --nomigrations`, coverage-гейт 30%) + vitest; CI-джобы:
  i18n-symmetry, backend-lint/test, migration-check, api-contract (spectacular + typegen drift),
  frontend-lint/test/build, security (pip-audit + npm audit, HARD), docker-build.

> Источник истины: `CLAUDE.md` §«Celery Tasks» / §«Environment» / §«Testing».

---

## 10. См. также (живые каноны)

- [`../../../CLAUDE.md`](../../../CLAUDE.md) — **главный канон** для агентов и разработчиков (стек, топология, IRON RULES).
- [ADR 0001–0006](../adr/) — действующие архитектурные решения (разделение админок → wedge-loop).
- [`technical-specification.md`](technical-specification.md) — детали стека/моделей/API.
- [`schema.json`](schema.json) — OpenAPI-схема (+ генерируемый `frontend/src/api/schema.d.ts`).
- [`architecture-diagrams.md`](architecture-diagrams.md) — Mermaid/drawio-диаграммы.
- [`websocket-messages.md`](websocket-messages.md) — словарь WebSocket-сообщений.
- [`../specs/`](../specs/) — актуальные ТЗ (quote-builder, policy-pack, sections-hygiene, remaining).
- [`../ops/`](../ops/) — RUNBOOK, деплой, последние session-handoff'ы.
- [`../../business/business-logic.md`](../../business/business-logic.md) — пользовательские сценарии.
- [`../../business/ROADMAP.md`](../../business/ROADMAP.md) — план и статус.
- [`../../old/architecture/master-system-document-v6-2026-04.md`](../../old/architecture/master-system-document-v6-2026-04.md) — **архив** прежней версии-энциклопедии (v6.0, устарела).
