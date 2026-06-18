# RailTech B2B SaaS — Консолидированный технический и продуктовый аудит

> **Дата:** 2026-06-18 · **Ветка:** `claude/b2b-platform-audit-jvnvjw`
> **Метод:** статический анализ + трассировка кода 5 параллельными агентами-аудиторами + независимая верификация спорных находок по коду.
> **Состав совета:** Chief Software Architect · Lead Python/Django · Lead React · Database Architect · CX/UX Engineer.

---

## 0. Вердикт (Executive Summary)

Платформа **архитектурно здорова**, а не «сгнила». Сервисный слой реальный, FSM сделки имеет единственную точку записи, финансы на `Decimal` с аудит-трейлом, GIN-триграммы под Smart Match существуют и используются, `transaction.atomic()` и `select_for_update()` применяются широко, авто-инвойс идемпотентен. Это опровергает первое впечатление о «костыльном» продукте.

**Источник нестабильности, на которую жалуются пользователи, — НЕ архитектура, а конкретные классы дефектов:**

| # | Корневая причина «непредсказуемости» | Где | Severity |
|---|---|---|---|
| 1 | **Side-effects диспатчатся внутри транзакции, а не через `on_commit`** (0 вхождений `on_commit` во всём backend) | `crm/services/deals.py:135`, quotes/contracts/kyc | 🔴 CRIT |
| 2 | **MinIO выключен в проде → KYC-документы и PDF на одном неарбекапленном локальном volume** | `docker-compose.prod.yml:62`, `core/storage.py` | 🔴 CRIT |
| 3 | **Тихие сбои в UI** — десяток list-страниц не обрабатывают `isError` | `DealsPage`, `QuotesPage`, `ProductManagement`, `ActsPage`, `DealQuotePage` | 🔴 HIGH |
| 4 | **Документированный гейт подписки НЕ включён** — `company_has_operational_subscription()` имеет 0 call-sites | `accounts/services/permissions.py:111` | 🔴 HIGH |
| 5 | **Нет структурного логирования и request-id** — продакшн нечем дебажить | `core/settings.py:596` | 🔴 HIGH |
| 6 | **Магические строки статусов** (101 вхождение) post-sale слоя | `crm/models/{contracts,billing,fulfillment}.py` | 🟠 MED |

### Верифицированные опровержения (auditor's correction)

Чтобы отделить факты от догадок, ниже — «находки», оказавшиеся ложными после проверки кода:

| Заявлено | Реальность (проверено) |
|---|---|
| «FSM течёт: ~6 прямых `deal.stage =`» | **Ложь.** Единственная запись — `deals.py:117` внутри `transition_deal_stage`. FSM — единственный чокпоинт. ✅ |
| «Транзакции отсутствуют» | **Ложь.** `atomic()`: quotes.py — 11, contracts.py — 5, billing.py — 4. `select_for_update` используется. ✅ |
| «Авто-инвойс не идемпотентен» | **Ложь.** `crm/tasks.py:220` переиспользует Invoice (`idempotent_reuse`). ✅ |
| «Sentry для Celery не подключён» | **Ложь.** `settings.py:711` — `[DjangoIntegration(), CeleryIntegration()]`. ✅ |
| «Фронтенд: хардкод цветов, `as any`, `text-[10px]`» | **Ложь.** 0 hex/палитры, 0 `text-white/black`, 0 `as any` в `.tsx`, i18n-симметрия 99.9%, статусы по `_code`. Фронтенд дисциплинирован. ✅ |

Реальный долг фронтенда — **структурный** (god-компоненты, дублирование состояния, не-персистируемая корзина), а не стилевой.

---

## 1. АУДИТ КОДОВОЙ БАЗЫ (Red Flags & Code Smells)

### 1.1 Хлипкий код и тихое проглатывание ошибок

| Severity | Файл:строка | Проблема | Стандарт |
|---|---|---|---|
| 🔴 HIGH | `sourcing/views.py:162`, `:265` | `except Exception` оборачивает файл+base64+`.delay()`+3 ORM-create; баг маскируется как «Failed to process import» | `(OSError, ValueError)` / `kombu.exceptions.OperationalError` |
| 🟠 MED | `core/middleware.py:26` | `except Exception: return AnonymousUser()` — ошибки JWT неотличимы от «нет токена», без лога | `(InvalidToken, TokenError, CustomUser.DoesNotExist)`, логировать неожиданное |
| 🟠 MED | `core/admin_api/triage.py:266` | `except Exception: continue` (+`# pragma: no cover`) — сломанный сборщик невидим | `logger.exception()` перед `continue` |
| 🟡 LOW | applications/kyc/messaging/emails (~12) | bare-except вокруг side-effects, но с `logger.exception` — защитимо | Сузить до конкретных исключений |

### 1.2 Хардкод магических строк (DRY + IRON RULE 2)

`Deal`/`Quote` имеют `crm/constants.py` (`DealStageCode`, `QuoteStatusCode`). Но **post-sale слой использует сырые литералы — 101 вхождение в 19 файлах**: `"SIGNED"`, `"ISSUED"`, `"PAID"`, `"PARTIAL"`, `"PENDING_CLIENT"`, `"IN_TRANSIT"`, `"SHIPPED"`.

```
Было:    invoice.status = "PAID"          # billing.py:197 — опечатка = тихий промах
Стандарт: class InvoiceStatusCode(TextChoices): PAID = "PAID", _("Оплачен")
         invoice.status = InvoiceStatusCode.PAID
```
**Действие:** `ContractStatusCode / InvoiceStatusCode / ActStatusCode / FulfillmentStatusCode` в `crm/constants.py`.

### 1.3 Высокая цикломатическая сложность (лимит — 50 строк/функция)

| Функция | Строк | Файл |
|---|---|---|
| `AdminSearchView.get()` | 125 | `core/admin_api/search.py:49` |
| `_compute_dashboard_payload()` | 121 | `core/dashboard.py:84` |
| `process_excel_import` | 117 | `sourcing/tasks.py:167` |
| `RegistrationWizard.done()` | 92 | `accounts/wizard.py:192` |
| `record_payment()` | 88 | `crm/services/billing.py:121` |
| `send_templated_email()` | 87 | `notifications/emails.py:80` |

Смелл: `record_payment(payment_data_or_invoice_id, ...)` — первый параметр принимает dataclass **либо** int (перегрузка типа).

### 1.4 Фронтенд: god-компоненты (структурный долг)

| Компонент | Строк | Что намешано |
|---|---|---|
| `AdminUsersPage.tsx` | 696 | 9 mutation-хуков + `MembershipsPanel` + диалоги + CSV + аплоад в одном файле |
| `AdminDataTable.tsx` | 685 | sort+pagination+filter+resize+selection+CSV; 20+ пропсов |
| `AdminKYCPage.tsx` | 679 | KYC 3 уровня + preview + сырой `fetch` рядом с React Query |
| `PlatformAdminDashboard.tsx` | 673 | 8+ источников, конфиги графиков инлайн |
| `AppShell.tsx` | 622 | hand-rolled hash-роутер + переключатель контекста + nav + рендер |

Все превышают лимит 500 строк/модуль. **Стандарт:** container/presenter split, TanStack Table v8.

### 1.5 Мелкие нарушения соглашений

- `DEBUG = os.environ.get("DJANGO_DEBUG","False") != "False"` (`settings.py:34`) — `"false"`/`""` → `DEBUG=True`. → `.lower()=="true"`.
- Однобуквенные переменные: `kyc.py:124 (u)`, `tasks.py:174 (ff)`, `billing.py:143 (pd)`, `Decimal as D`.
- `AppShell.tsx:243` — `statusColor()` всегда возвращает `'text-primary'` (мёртвый no-op).

---

## 2. АУДИТ АРХИТЕКТУРЫ И ЛОГИКИ БД

### 2.1 Сделано правильно (baseline)

- ✅ GIN-триграммы Smart Match (`catalog/migrations/0006`) + `TrigramSimilarity` по тем же колонкам (`sourcing/services.py:72`).
- ✅ Все деньги — `DecimalField(14,2)`, ни одного `FloatField`; `QuoteItemHistory` зеркалит финансовые поля.
- ✅ Композитные индексы: `deal_company_stage_idx`, `notif_user_read_aud_idx`, `(deal, timestamp)`.
- ✅ Полиморфный `Attachment` через явные FK + `CheckConstraint exactly_one_fk_populated`.
- ✅ Seed = data-migrations (`RunPython get_or_create`); в hot-path лукапов `get_or_create` нет.
- ✅ N+1: list-эндпоинты используют `select_related`/`prefetch_related`/`aggregate()`; `.count()` в циклах не найдено.

### 2.2 Проблемы данных

| Severity | Сущность:строка | Проблема | Было / Как должно быть |
|---|---|---|---|
| 🟠 MED | contracts/billing/fulfillment/subscriptions/applications | Статусы post-sale — `CharField(choices)` vs `AbstractLookup`-FK у Deal/Quote/Product. Полу-и-полу | `status="PAID"` → `AbstractLookup`-подкласс или явный code-freeze |
| 🟠 MED | `catalog/models/products.py:91` vs `:100` | Двойной живой источник производителя: `manufacturer` (DEPRECATED) и `brand` оба пишутся/индексируются | Выбрать `brand` каноном, backfill, удалить `manufacturer` |
| 🟠 MED | `offers.py:105`, `company.py:61` | `SupplierOffer.is_active` фильтруется на каждом публичном чтении без `db_index`; то же `Company.is_verified` | `BooleanField(db_index=True)` / partial index |
| 🟡 LOW | `crm/serializers.py:163` | `DealListSerializer` встраивает `active_quote` со всеми items в список | Лёгкий list-сериализатор без `items` |
| 🟡 LOW | `crm/serializers.py:22` | `QuoteItemSerializer` читает `offer.supplier.name` — bulk-пути проверить на N+1 | Гарантировать prefetch у всех вызывающих |

### 2.3 Интегрити финансовых записей (углублённый проход)

| Severity | Находка | Доказательство |
|---|---|---|
| 🔴 HIGH | **Гонка двойного платежа**: `Payment.reference` есть, но нет `UniqueConstraint(invoice, reference)` | `crm/models/billing.py:142` |
| 🔴 HIGH | **pghistory на Deal/Quote/QuoteItem, но НЕ на Contract/Invoice/Payment/Act** — самые аудит-критичные записи без immutable-истории | скан `@pghistory.track` |
| 🟠 MED | Нумерация документов `count()+1` (invoice/act/contract) — гонка → дубль-номер 500 | billing/contracts services |
| 🟠 MED | Финансовые FK на `CASCADE` (`Invoice.deal`, `Payment.invoice`) — удаление Deal сносит платежи без следа | `crm/models/billing.py` |
| 🔴 HIGH | Нет оптимистичной блокировки: `Quote.version` — ревизия, не concurrency-токен; buyer request-edit путь (`quotes.py:637`) небло­кируем и неатомарен | — |

---

## 3. АНАЛИЗ ПОЛЬЗОВАТЕЛЬСКОГО ПУТИ (CJM)

**Роутинг (факт):** всё — hash-based SPA через `App.tsx MainApp() switch(page.type)` в двух shells: `AppShell` (BUYER/SELLER/MFG) и `PlatformAdminShell` (ADMIN). Упомянутые в CLAUDE.md `AdminShell/ClientShell/ManagerShell/CatalogShell` **в рантайме не существуют** — устаревшая документация. React Router в боевом пути нет.

### 3.1 Тупиковые маршруты и тихие сбои

| Severity | Роль | Файл:строка | Тупик / трение |
|---|---|---|---|
| 🔴 CRIT | ADMIN | `PlatformAdminShell.tsx:117`, `PlatformAdminDashboard.tsx:277` | **`admin-bids` — мёртвый маршрут**: nav-пункт и маппинг очереди есть, но `'admin-bids'` нет в `Page`/`switch`/`validTypes`/`ADMIN_PAGES`. Клик → тихий отскок на dashboard |
| 🔴 HIGH | BUYER/SELLER | `DealsPage:208`, `QuotesPage:39`, `ProductManagement:61`, `ActsPage:32`, `SourcingRequestsPage:18`, `DealQuotePage:29` | **Нет обработки `isError`** — провал запроса (вкл. сон Neon) рисует пустую таблицу. Эталон: `RequestDetailPage.tsx:54-69` |
| 🔴 HIGH | BUYER/SELLER | `ExcelUpload.tsx:57` | **Тихий провал Excel-импорта**: при Celery `FAILURE` — `toast.error`+сброс, без persistent error-карточки и retry. Порт из `CatalogImportPage.tsx:286` |
| 🟡 LOW | ALL | `App.tsx:316-380` | Context-guard построен правильно: отбивает кросс-ролевые deep-links с тостом ✅ |

### 3.2 Трение в бизнес-потоках

| Severity | Роль | Где | Проблема |
|---|---|---|---|
| 🔴 HIGH | SELLER/MFG | `accounts/services/permissions.py:111` | **Гейт подписки задокументирован (ADR-0002), но НЕ включён** — 0 call-sites. Продавец с `past_due` может слать КП и подписывать. Нет кода ошибки `SUBSCRIPTION_REQUIRED` |
| 🔴 HIGH | ADMIN | `useViewerMode.ts`, `lib/apiError.ts:21` | **`ADMIN_VIEWER_CANNOT_ACT` не проброшен в admin-UI**: ни одна из 8 admin-страниц не импортирует `useIsViewerMode()`; в catch часто `toast.error(t('common.error'))` вместо `translateApiError(e)` |
| 🟠 MED | SELLER | `RequestDetailPage.tsx`, `DealQuotePage.tsx:60` | Разрыв в середине потока: нет кнопки-моста к `QuoteBuilderGrid`; после отправки КП нет CTA «сгенерировать контракт» |
| 🟠 MED | SELLER/BUYER | `QuotesPage:201`, `DealQuotePage:99`, `RequestDetailPage:226`, `LeadsPage:76` | Необратимые клиент-видимые действия (Send to Client / Approve / Convert lead) без `ConfirmActionDialog` |

### 3.3 Обратная связь

- 🟠 `AdminKYCPage:97`, `AdminRoleApplicationsPage:262`, `AdminSupportPage:84`, `AdminCompaniesPage:203` — catch-блоки используют `toast.error(t('common.error'))`, выбрасывая backend-причину. Стандарт: `RequestDetailPage.tsx:89` обёртка `run()` с `translateApiError`.
- ✅ Force-actions админа (`AdminDealsPage:160`) — образцовый `ConfirmActionDialog` с reason.

---

## 4. ROADMAP ТРАНСФОРМАЦИИ К МЕЖДУНАРОДНЫМ СТАНДАРТАМ

### Фаза 0 — Стабилизация продакшна

| Задача | Файлы | Паттерн |
|---|---|---|
| Side-effects в `transaction.on_commit` | `crm/services/deals.py:135`, quotes/contracts/kyc | on_commit hook |
| Восстановить внешний S3-storage для KYC/PDF | `docker-compose.prod.yml`, `core/storage.py` | fail-loud, без FS-fallback в prod |
| Гейтить deploy на CI | `.github/workflows/deploy-b2b.yml` | `workflow_run`/`needs` |
| `UniqueConstraint(invoice, reference)` на Payment + БД-секвенс нумерации | `crm/models/billing.py` | idempotency constraint |
| Триада loading/error(retry)/empty на всех list-страницах | DealsPage, QuotesPage, ProductManagement, ActsPage, DealQuotePage | `PageShell` HOC из RequestDetailPage |
| Persistent error+retry на async-импортах | `ExcelUpload.tsx` | порт из CatalogImportPage |
| Включить/исправить гейт подписки | `accounts/services/permissions.py` → seller-write | `company_has_operational_subscription()` + код `SUBSCRIPTION_REQUIRED` |
| Структурный JSON-лог + request-id → Celery/WS | `core/settings.py:596` | `python-json-logger` + correlation-id middleware |
| `translateApiError(e)` во всех admin catch | 4 admin-страницы | единый error-envelope |

### Фаза 1 — Финансовая надёжность

| Задача | Файлы |
|---|---|
| `acks_late=True, task_reject_on_worker_lost=True` для финансовых задач | `crm/tasks.py` |
| `@pghistory.track` на Contract/Invoice/Payment/Act | `crm/models/*` |
| Idempotency-Key на мутирующих POST | DRF middleware |
| Оптимистичная блокировка (`row_version`/ETag) | Quote/Contract/Invoice |
| Константы статусов post-sale | `crm/constants.py` |
| Индексы `is_active`/`is_verified` | `offers.py`, `company.py` |
| Healthcheck celery worker/beat + лимит памяти redis-celery | `docker-compose.prod.yml` |

### Фаза 2 — Безопасность и контракт API

| Задача | Было | Стандарт |
|---|---|---|
| JWT хранение | localStorage (XSS) | refresh в HttpOnly cookie, access в памяти |
| WS-auth | токен в query-string | `Sec-WebSocket-Protocol` / ticket |
| logout/revocation | нет endpoint | endpoint отзыва токена |
| Фронтенд-типы API | hand-written, codegen сломан (`schema.openapi.json` ≠ `schema.json`, пакет не установлен) | генерация из `schema.json` + CI drift-gate |
| Versioning | `v1` хардкод, нет `DEFAULT_VERSIONING_CLASS` | `URLPathVersioning` + `Sunset`-политика |

### Фаза 3 — Структурный долг фронтенда

| Задача | Файлы |
|---|---|
| Единый источник auth/role; `userStore`→селекторы над `authStore` | `userStore.ts`, `authStore.ts`, `api/client.ts` |
| `activeStatus` вычислять, не хранить | `userStore.ts:136` |
| Персист `cartStore` | `cartStore.ts:25` |
| Рефактор 6 god-компонентов | §1.4 |
| Убрать `onNavigate` prop-drilling (107 вхождений/17 файлов) | `AppShell.tsx` → NavigationContext / React Router |
| `isViewerMode`→`isPlatformAdmin` | `userStore.ts:87` |

### Целевая архитектура

```
FRONTEND (React)
  • access-token в памяти, refresh в HttpOnly-cookie
  • типы API ГЕНЕРИРУЮТСЯ из OpenAPI (нет дрейфа)
  • React Query = server-state; Zustand = ТОЛЬКО ui-state (один auth-источник)
        │ HTTPS + Idempotency-Key на записях
NGINX/Caddy (gateway) • per-tenant rate-limit • CSP • no-cache на authed
        │
DJANGO/DRF (Daphne ASGI, N реплик, sticky WS)
  • тонкие views → СЕРВИСНЫЙ СЛОЙ (вся бизнес-логика)        ← уже так
  • каждая мульти-моделная запись в transaction.atomic()      ← уже так
  • side-effects через transaction.on_commit                  ← ВКЛЮЧИТЬ
  • единственный чокпоинт FSM: transition_deal_stage()        ← уже так
  • гейт: is_member_of(capability) + company_has_operational_subscription() ← ВКЛЮЧИТЬ
  • структурный JSON-лог + request-id → Celery/WS
        │                    │                  │
   PostgreSQL          Redis(Channels)     Redis(Celery)
   • optimistic lock    • AOF persist       • AOF + acks_late + idempotent
   • FK/partial idx
        └────────► Sentry (Django+Celery ✅) + лог-агрегатор ◄────┘
   Object storage (S3/MinIO) для KYC/PDF — НЕ локальный FS
```

**Парадигма:** фронтенд не держит бизнес-правил — рендерит состояние и шлёт интенты. Сервисы — единственный авторитет переходов, обёрнуты в транзакции, side-effects через `on_commit`, эмитят domain-события в `ActivityLog` + notifications. Celery-задачи идемпотентны и durable. Каждая кросс-сущностная мутация атомарна и проаудитирована.

---

## 5. Приоритезированный план (P0 → P3)

**P0 (стабильность + интегрити):**
1. Side-effects в `transaction.on_commit` (`deals.py:135` → quotes/contracts/kyc).
2. Внешний S3-storage для KYC/PDF (снять `profiles: with-minio`).
3. Гейт deploy на CI.
4. `UniqueConstraint(invoice, reference)` на Payment + БД-секвенс нумерации.
5. Триада error-state на всех list-страницах.
6. Включить гейт подписки + код `SUBSCRIPTION_REQUIRED`.
7. Структурный JSON-лог + request-id.

**P1:** pghistory на финансовых моделях; healthcheck celery; codegen API + drift-gate; персист cartStore; константы статусов; индексы.

**P2:** logout/revocation; soft-delete/`PROTECT` финансовых FK; вынести Rule-8-утечки в сервисы; JWT в HttpOnly; оптимистичная блокировка.

**P3:** рефактор god-компонентов; убрать prop-drilling; разбить >500-строчные модули; переименования.
