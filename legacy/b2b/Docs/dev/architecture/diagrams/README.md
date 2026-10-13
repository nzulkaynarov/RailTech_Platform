# RailTech SaaS B2B — User Journey Maps & Business Process Diagrams

Диаграммы путей пользователя (SJM) и бизнес-процессов для всех ролей системы **RailTech**, построенные **end-to-end** на основе исходного кода (`backend/*/services.py`, `backend/*/views.py`, `backend/*/admin.py`, `frontend/src/layouts/AppShell.tsx`, `frontend/src/store/userStore.ts`).

Все файлы — исходники **draw.io** (`.drawio`), открываются в:

- [app.diagrams.net](https://app.diagrams.net/) (онлайн)
- Draw.io Desktop
- VS Code extension **Draw.io Integration** (`hediet.vscode-drawio`)

---

## Содержание

| Файл | Роль | Назначение |
|---|---|---|
| [`buyer.drawio`](./buyer.drawio) | **BUYER** (Клиент-покупатель, `CompanyType=CLIENT`) | От регистрации до закрытия сделки глазами заказчика |
| [`seller.drawio`](./seller.drawio) | **SELLER** (Поставщик, `CompanyType=SUPPLIER`) | От заявки на роль до публикации офферов и участия в сделке |
| [`manufacturer.drawio`](./manufacturer.drawio) | **MANUFACTURER** (Производитель, `CompanyType=MANUFACTURER`) | Расширение пути Seller с учётом PIM и equipment-groups |
| [`manager.drawio`](./manager.drawio) | **MANAGER** (Account / Sales Manager, `SystemRole ∈ {ACCOUNT_MANAGER, SALES_MANAGER}`) | Полный FSM сделки: DRAFT → … → CLOSED_WON |
| [`admin_spa.drawio`](./admin_spa.drawio) | **ADMIN SPA** (React Admin, `role=ADMIN`, хэш-роуты `#admin-*`) | Ежедневные операции админа из React UI |
| [`admin_unfold.drawio`](./admin_unfold.drawio) | **ADMIN UNFOLD** (Django Admin `/admin/`, `is_superuser=True`) | Инженерный/аварийный периметр |

---

## Легенда цветов

Единая схема во всех шести диаграммах:

| Цвет | Значение |
|---|---|
| 🟢 зелёный (`#d5e8d4`) | Happy-path шаг: нормальный, отлаженный переход |
| 🟡 жёлтый ромб (`#fff2cc`) | Точка решения / ручная проверка |
| 🟠 оранжевый (`#ffe6cc`) | **Узкое место** — ожидание, лимит, асинхронный тайм-аут, ручная задержка |
| 🔴 красный (`#f8cecc`) | **Тупик** — отсутствующий функционал, терминальное состояние без возврата, скрытая потеря данных |
| 🔵 синий (`#dae8fc`) | Admin-действие (Unfold action или React Admin операция) |
| 🟣 фиолетовый курсив (`#e1d5e7`) | Внешняя система: Celery, Email SMTP, WeasyPrint PDF, MinIO, WebSocket, Neon PostgreSQL |
| ⚪ серый (`#e8e8e8`) | Старт / терминальное состояние |

Пунктирный красный маршрут на стрелке — «аномальный» путь (отказ, silent-failure, фолбэк на Unfold).

---

## 1. BUYER — клиент-покупатель

Путь начинается на публичной `LoginPage` и заканчивается состоянием `CLOSED_WON / CLOSED_LOST`. Полный сценарий:

1. **Регистрация** (`POST /api/v1/auth/register/` → `accounts/services.py:24` `create_pending_user`) — создаётся `CustomUser(is_active=False, role=GUEST)`, отправляется письмо с `/setup-password`.
2. **Setup password** (`accounts/services.py:69` `verify_and_setup_password`) — `is_active=True`.
3. **Submit profile** (`accounts/services.py:86` `submit_company_profile`) — создаётся `Company(type=CLIENT по умолчанию)`, `verification_status=PROFILE_SUBMITTED`, `CompanyMember(is_primary=True)`.
4. **Upload KYC docs** (`POST /accounts/companies/{id}/upload-document/`, `accounts/services.py:357`).
5. **Ожидание администратора** → `L2_VERIFIED` (`accounts/services.py:198` `verify_company_kyc`).
6. **Login → Dashboard** (контекст BUYER).
7. **Создание сделки** (`POST /api/v1/crm/deals/` → `Deal(stage=DRAFT)`).
8. **Спецификация** — загрузка Excel (`POST /sourcing/import-deal/{id}` → Celery `process_excel_import`) либо выбор из каталога.
9. **Ожидание менеджера** — менеджер ведёт FSM `DRAFT → SOURCING → CALCULATING`, формирует `Quote`, нажимает `send_to_client` → `Deal → QUOTE_SENT`.
10. **Просмотр КП** в `QuotesPage` (PDF + items).
11. **Approve / Reject** (`crm/services.py:226` `approve_quote` / `:271` `reject_quote`).
12. **Закрытие сделки** менеджером → `CLOSED_WON`.

### Тупики и узкие места (Buyer)

| Где | Файл | Что |
|---|---|---|
| 🔴 Email fail → каскадное удаление пользователя | `backend/accounts/services.py:63` | Если SMTP упал при регистрации, `CustomUser` удаляется. Новая попытка — новая регистрация. |
| 🔴 Хардкод `CompanyType='CLIENT'` | `backend/accounts/services.py:86` | При онбординге `company_type_code` захардкожен `CLIENT`. Стать Supplier/Manufacturer можно только через отдельную `CompanyRoleApplication`. |
| 🟠 Ручная KYC-верификация | `backend/accounts/admin.py:156`, `services.py:198` | Единственный путь подтверждения — Unfold `verify_kyc` action. SLA/таймера нет. |
| 🔴 Нет нотификации клиенту об `L2_VERIFIED` | `backend/accounts/services.py:220` (`# TODO`) | Клиент узнаёт о верификации только при следующем логине. |
| 🟠 BUYER не видит меню «Сделки/Клиенты/Аналитика» | `frontend/src/layouts/AppShell.tsx:105` | Показывается только ролям `ADMIN`/`MANAGER`. Обычный покупатель работает через `My Requests`. |
| 🟠 Лимит Celery-импорта | `backend/sourcing/tasks.py:16` | `MAX_ROWS=5000`, soft timeout 540 s, hard timeout 600 s. Большие спецификации падают. |
| 🔴 Smart Match threshold 0.3 | `backend/sourcing/services.py:54-66` | Низкий порог → ложные срабатывания. Ручного re-match UI нет. |
| 🔴 `CONTRACT_SIGNED` — «пустой» статус | `backend/crm/services.py:250` | Переход `QUOTE_SENT → CONTRACT_SIGNED` не порождает файл контракта, не отправляет на e-sign. Статус номинален. |
| 🔴 Quote `valid_until` не enforced | `backend/crm/models.py` | Поле есть, но ни одна Celery-task его не проверяет. |
| 🔴 Терминальные `CLOSED_WON/LOST` | `backend/crm/services.py:330` | `ALLOWED_STAGE_TRANSITIONS[...]=[]` — сделку нельзя «открыть обратно». |
| 🔴 Нет платёжного контура | `CLAUDE.md:294` | `SupplierSubscription` существует, но биллинг, инвойсы, счета-фактуры, акты — не реализованы. |

---

## 2. SELLER — поставщик

Роль получается **надстройкой** на базовый путь `BUYER`: сначала регистрация как `CLIENT`, потом заявка на роль `SUPPLIER`.

1. Прохождение базового KYC (как Buyer) до `L2_VERIFIED`.
2. **Подача `CompanyRoleApplication`** с `requested_type=SUPPLIER`, обязательными `contract_file` + `nda_file` (`backend/accounts/services.py:260`).
3. **Admin approve в Unfold** (`@superuser_only_action`, `backend/accounts/admin.py:294`) → `approve_role_application` → `company.types.add(SUPPLIER)`.
4. Login → sidebar в контексте SELLER (`getSellerNavigation`, `AppShell.tsx:133`).
5. Catalog: `Category → EquipmentGroup → Product → SupplierOffer`.
6. CRM: просмотр сделок, где supplier=self (через `SupplierOffer`).

### Тупики и узкие места (Seller)

| Где | Файл | Что |
|---|---|---|
| 🔴 approve `CompanyRoleApplication` в React недоступен | `backend/accounts/admin.py:294` | Единственный путь — Django Unfold. `AdminRoleApplicationsPage.tsx` существует, но REST-endpoint approve/reject в `backend/accounts/views.py` не найден. |
| 🔴 `SupplierSubscription` не гейтит фичи | `backend/accounts/models.py:436-533`, `CLAUDE.md:294` | Поставщик работает без оплаты. `subscription.is_active` не проверяется ни в одной view. |
| 🔴 Поставщик пассивен | `backend/crm/services.py:169` | `Quote` создаёт только `Manager` (`IsManagerOrAdmin`). Нет bid-flow, supplier не может сам котировать RFQ. |
| 🔴 Нет модерации офферов | `backend/catalog/admin.py:140` | `publish_products` — только `@admin.action`. `SupplierOffer` публикуется сразу, без review-queue. |
| 🟠 Валидация RAILWAY_MACHINERY | `backend/catalog/models.py:309-332` | Продукт railway-домена требует ≥1 `equipment_group` — блокирующий валидатор. |
| 🔴 Global catalog import без namespace | `backend/sourcing/tasks.py:130` | `process_catalog_import` пишет в общий PIM — SKU-конфликты между поставщиками. |

---

## 3. MANUFACTURER — производитель

Почти копия Seller, но:

- Заявка на роль требует **`partnership_agreement`** вместо contract+NDA (`accounts/services.py:263`).
- `Company.types += MANUFACTURER`.
- Фронт маппит `MANUFACTURER` и `PLANT` в одну UI-ветку `status=MANUFACTURER` (`userStore.ts:148-161`).
- Sidebar (`getManufacturerNavigation`, `AppShell.tsx:113`) **не включает Sourcing-меню** — в отличие от Seller.

### Тупики и узкие места (Manufacturer)

| Где | Файл | Что |
|---|---|---|
| 🔴 Нет Sourcing-меню | `frontend/src/layouts/AppShell.tsx:113-131` | MFG не видит RFQ напрямую; полагается на менеджера. |
| 🔴 Frontend смешивает Seller/MFG, backend различает | `userStore.ts:148`, `AppShell.tsx` | Возможны перекосы прав/меню. |
| 🟠 Approve MANUFACTURER — только Unfold | `backend/accounts/admin.py:294` | То же ограничение, что и у Seller. |
| 🔴 Production Analytics только для `role=ADMIN/MANAGER` | `AppShell.tsx:127` | Владелец MFG-компании с ролью `CLIENT` её не видит. |

---

## 4. MANAGER — менеджер продаж / аккаунт-менеджер

Единственная роль, которая **ведёт сделку через FSM**. Создаётся вручную (Unfold или `init_superadmin`).

Полный FSM (`backend/crm/services.py:323-332`):

```
DRAFT ──► KYC_PENDING ──► SOURCING ──► CALCULATING ──► QUOTE_SENT ──► CONTRACT_SIGNED ──► CLOSED_WON
  │           │             │              │                │                                    │
  └───────────┴─────────────┴──────────────┴────────────────┴──────────────► CLOSED_LOST ◄───────┘
                                                            │
                                                            └───► CALCULATING (при reject_quote)
```

Ключевые сервисы:

- `crm/services.py:340` `transition_deal_stage` — проверяет `ALLOWED_STAGE_TRANSITIONS`, пишет `ActivityLog`.
- `crm/services.py:12-105` `QuoteCalculationService.recalculate_quote` — пересчёт totals, `QuoteItemHistory` (audit).
- `crm/services.py:142` `generate_pdf` — WeasyPrint → приватный MinIO.
- `crm/services.py:169` `send_to_client` — замораживает цены (`frozen_at`), `Deal → QUOTE_SENT`, шлёт Notification.
- `crm/services.py:226` `approve_quote`, `:271` `reject_quote`.

### Тупики и узкие места (Manager)

| Где | Файл | Что |
|---|---|---|
| 🟠 Менеджер не может зарегистрироваться сам | `backend/accounts/services.py`, `accounts/admin.py:85` | Роль назначается только через `make_staff` в Unfold или скрипт. |
| 🔴 Lead → Deal не автоматизировано | `backend/crm/admin.py:198` | `mark_processed` только ставит флаг. Функции `convert_lead_to_deal` нет. |
| 🔴 Ручной re-match Smart Match | `backend/sourcing/services.py` | UI переназначения `QuoteItem.product` не реализован. |
| 🔴 Нет шаблонизатора контракта/инвойса | `backend/crm/services.py:142` | WeasyPrint генерит только quote PDF. |
| 🟠 Нет SLA / auto-reminder для `QUOTE_SENT` | `backend/crm/services.py:169` | Quote висит бессрочно. |
| 🔴 Post-sale workflow отсутствует | — | После `CLOSED_WON` — нет инвойса, акта, fulfillment, reconcile. |
| 🟠 `mark_closed_lost` — только Unfold | `backend/crm/admin.py:108` | Bulk-закрытие из React недоступно. |

---

## 5. ADMIN SPA — React Admin (`role=ADMIN`)

Фронт-админка внутри `AppShell` (хэш-роуты `#admin-users`, `#admin-kyc`, `#admin-subscriptions`, `#admin-role-apps`, `#admin-catalog`, `#admin-categories`, `#admin-equipment-groups`, `#admin-offers`). Страницы лежат в `frontend/src/pages/Admin*Page.tsx`.

Маппинг роли (`frontend/src/store/userStore.ts:176`):

```ts
role: (role_code === 'ADMIN' || role_code === 'SALES_MANAGER') ? 'ADMIN'
    : role_code === 'ACCOUNT_MANAGER' ? 'MANAGER'
    : 'EMPLOYEE'
```

### Тупики и узкие места (Admin SPA)

| Где | Файл | Что |
|---|---|---|
| 🔴 Нет REST-endpoint «assign SystemRole» | `backend/accounts/views.py` | Ролевые назначения (ADMIN, ACCOUNT_MANAGER, SALES_MANAGER) возможны только из Unfold. |
| 🔴 KYC email-нотификации нет | `backend/accounts/services.py:220` | После approve клиент не получает email (TODO). |
| 🔴 `CompanyRoleApplication` approve/reject REST отсутствует | `backend/accounts/views.py`, `admin.py:294` | `AdminRoleApplicationsPage.tsx` фактически read-only. |
| 🔴 `publish_products` — только Unfold | `backend/catalog/admin.py:193` | В React Admin — не действие, а изменение `status`. |
| 🔴 Subscriptions без биллинга | `backend/accounts/models.py:436-533` | Статус меняется вручную. |
| 🔴 Subscription не enforced | — | `is_active` не используется как gate. |
| 🔴 Конфликт двух админок | ADR `Docs/dev/adr/0001-admin-separation.md` | Декларация «features → React Admin», практика — «stable features → Unfold». Админу приходится работать в двух местах. |

---

## 6. ADMIN UNFOLD — Django Admin (`/admin/`)

Периметр инженерный/аварийный. По ADR 0001 — **не для ежедневной работы**, а для:

- CRUD lookup-таблиц (`master_data`, `accounts.*Status`, `catalog.*Status`).
- Read-only audit (`ActivityLog`, `QuoteItemHistory`, `pghistory`).
- Emergency data fixes DBA.
- Celery Beat расписания.
- Django Auth Groups/Permissions.

### Реальные actions

| Модель | Action | Файл |
|---|---|---|
| `CustomUser` | `make_staff` → `assign_sales_manager_role` | `accounts/admin.py:85`, `services.py:185` |
| `Company` | `verify_kyc` (`@superuser_only_action`) | `accounts/admin.py:156` |
| `CompanyRoleApplication` | `approve_application`, `reject_application` | `accounts/admin.py:253,294` |
| `SupplierSubscription` | `activate_subscription`, `suspend_subscription` | `accounts/admin.py:321` |
| `Deal` | `mark_closed_lost` | `crm/admin.py:65,108` |
| `Lead` | `mark_processed` | `crm/admin.py:198` |
| `Message` | `archive_selected` | `crm/admin.py:238` |
| `Product` | `publish_products` | `catalog/admin.py:140,193` |
| `Notification` | `mark_as_read` | `notifications/admin.py:27` |

### Тупики и узкие места (Admin Unfold)

| Где | Файл | Что |
|---|---|---|
| 🟠 Superadmin не auto-created | `CLAUDE.md:293` | Нужен ручной `python manage.py init_superadmin`, читает `SUPERADMIN_EMAIL/PASSWORD` из `.env`. |
| 🔴 `make_staff` не назначает `SystemRole` | `accounts/services.py:185`, `admin.py:85` | Ставит `is_staff=True`, но `role` остаётся пустым/GUEST — менеджера не получится. |
| 🔴 Нет UI для полного FSM сделки | `crm/admin.py:65` | Только `mark_closed_lost` (bulk). Прочие переходы доступны лишь через React. |
| 🟠 `DomainKeyword` кэшируется 5 мин | `sourcing/tasks.py:30` | После правки ключевых слов роутинг отстаёт. |
| 🔴 `verify_kyc` без пост-хука | `accounts/services.py:220` | Нет email / pghistory trigger. |
| 🔴 Дубль с React Admin | ADR 0001 | По заявке «всё новое → React», на практике критические actions живут только в Unfold. |

---

## Сводная матрица тупиков (top-priority)

| # | Тупик / узкое место | Путь в коде | Затрагивает роли |
|---|---|---|---|
| 1 | Хардкод `CompanyType='CLIENT'` при онбординге | `accounts/services.py:86` | Buyer → Seller/MFG |
| 2 | Нет REST approve/reject `CompanyRoleApplication` | `accounts/views.py`, `admin.py:294` | Admin SPA, Seller, MFG |
| 3 | Нет email-нотификации после approve KYC | `accounts/services.py:220` | Buyer, Seller, MFG |
| 4 | `CONTRACT_SIGNED` — фиктивный статус (нет файла контракта, e-sign) | `crm/services.py:250` | Buyer, Manager |
| 5 | `Quote.valid_until` не enforced Celery | `crm/models.py`, `crm/tasks.py` | Manager, Buyer |
| 6 | Нет payment-контура (инвойс, счёт-фактура, оплата) | `accounts/models.py:436`, `CLAUDE.md:294` | Все |
| 7 | `SupplierSubscription` не гейтит фичи | `accounts/models.py:525-532` | Seller, MFG, Admin SPA |
| 8 | Lead → Deal не автоматизирован | `crm/admin.py:198` | Manager |
| 9 | `make_staff` не назначает `SystemRole` | `accounts/admin.py:85` | Admin Unfold |
| 10 | Поставщик не может сам котировать RFQ | `crm/services.py:169` | Seller |
| 11 | Smart Match threshold 0.3 + отсутствие re-match UI | `sourcing/services.py:54-66` | Manager, Buyer |
| 12 | Лимит Celery `process_excel_import` (5000 строк, 600 s) | `sourcing/tasks.py:16` | Buyer, Manager |
| 13 | FSM-терминалы `CLOSED_WON/LOST` без reopen | `crm/services.py:330` | Manager |
| 14 | Отсутствие post-sale workflow | — | Manager |
| 15 | BUYER не видит меню «Сделки» | `AppShell.tsx:105` | Buyer |
| 16 | Дубль action'ов Unfold ↔ React | `backend/*/admin.py`, `frontend/src/pages/Admin*` | Admin SPA, Admin Unfold |

Оранжевым выделены процессные узкие места (ожидание, лимиты). Красным — **архитектурные тупики**, то есть отсутствующая функциональность, которая нужна по логике SaaS.

---

## Как открывать

1. Скачать / клонировать репозиторий.
2. Открыть `docs/diagrams/<role>.drawio` в [app.diagrams.net](https://app.diagrams.net/) или Draw.io Desktop. В VS Code — через расширение **Draw.io Integration**.
3. В верхнем правом углу каждой диаграммы — блок `LEGEND` с напоминанием цветов.
4. Для аудита процессов — **красные** и **оранжевые** узлы отмечают места, куда стоит смотреть в первую очередь.

---

## Ссылки на ключевые файлы кода

- FSM сделки: `backend/crm/services.py` (323-398)
- Quote lifecycle: `backend/crm/services.py` (137-313)
- Smart Match: `backend/sourcing/services.py` (16-68)
- Excel import: `backend/sourcing/tasks.py` (45-200)
- KYC / Role Apps / Subscriptions: `backend/accounts/services.py` (24-360), `accounts/admin.py`
- Роль-маппинг фронта: `frontend/src/store/userStore.ts` (148-204)
- Навигация по ролям: `frontend/src/layouts/AppShell.tsx` (98-198)
- ADR об админке: `Docs/dev/adr/0001-admin-separation.md`
