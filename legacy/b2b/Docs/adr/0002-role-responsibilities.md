# ADR-0002: Роли и зоны ответственности

**Status:** Accepted (revised 2026-04-19 after Platform Admin model)
**Date:** 2026-04-19
**Deciders:** Product owner + Engineering
**Related:** ADR-0001 (admin separation), `accounts/migrations/0010_platform_admin_model.py`, `memory/platform_owner_semantics_2026_04_19.md`, `memory/capabilities_and_seller_implies_buyer_2026_04_19.md`

## Контекст

После миграции `accounts/0010_platform_admin_model` в платформе остались только **два** SystemRole: `ADMIN` и `USER`. Старые роли SALES_MANAGER, ACCOUNT_MANAGER, EMPLOYEE, GUEST, CLIENT упразднены. Вся коммерческая семантика «кто что делает в компании» переехала в `CompanyMember.role` (= `WorkspaceRole`) и `CompanyMember.can_sell / can_buy`.

Это устраняет долго копившуюся путаницу:
- «системный админ компании» vs. «администратор платформы»;
- «sales manager — это сотрудник конкретного supplier'а или сотрудник RailTech?»;
- одно поле `role` хранило одновременно платформенную и компанейскую семантику.

## Решение

Фиксируем три уровня:

1. **Платформа (SystemRole, FK на `CustomUser.role`):**
   - `ADMIN` — Platform Admin. Владелец платформы. Не может быть `CompanyMember` (инвариант enforced миграцией 0010 + сервисом `add_company_member`).
   - `USER` — все остальные. По умолчанию.

2. **Компания (WorkspaceRole, FK на `CompanyMember.role`):**
   - `OWNER` — универсальная для любого CompanyType.
   - `PROCUREMENT_MANAGER`, `BUYER_MANAGER` — только для `CLIENT` компаний.
   - `SALES_MANAGER`, `LOGIST` — только для `SUPPLIER` компаний.
   - `CONTRACT_MANAGER`, `FOREIGN_TRADE_SPECIALIST` — только для `MANUFACTURER` компаний.
   - Применимость хранится в `WorkspaceRole.applicable_to_types` (M2M на `CompanyType`).

3. **Per-member capabilities** (на `CompanyMember`):
   - `can_sell: bool`, `can_buy: bool`. Распределяются OWNER'ом внутри команды.

### Два админ-периметра (из ADR-0001)

| Периметр | Для кого | Когда |
|---|---|---|
| Django Unfold (`/admin/`) | Инженеры / DBA (`is_superuser`) | Редкие ситуации: справочники, аварийные фиксы, аудит-просмотр |
| React `PlatformAdminShell` (SystemRole=ADMIN в SPA) | Платформенный админ | Ежедневные операции — KYC, подписки, заявки на роли |

### Роль 1 — Platform Engineer (`is_superuser=True`)

Инструмент: Unfold + терминал (compose / manage.py / миграции).

| Отвечает | Где именно |
|---|---|
| Развёртывание, миграции БД, расписание Celery Beat | `make up`, `make migrate`, Unfold → Periodic tasks |
| Master data: Currency / Country / Unit / DeliveryBasis | Unfold (ModelAdmin редактируемые) |
| Назначение SystemRole=ADMIN/USER через Django shell или React Admin | Unfold или React Admin → Users → Change role |
| Аварийные фиксы данных через Unfold (временно сняв ReadOnlyInspectionMixin) | Unfold |
| Seed суперадмина: `init_superadmin`, `core_seed` | manage commands |
| Просмотр ActivityLog, QuoteItemHistory, pghistory | Unfold (read-only) |

**НЕ делает:** работу с клиентами / сделками / контрактами — это зона business-ролей.

### Роль 2 — Platform Admin (`SystemRole.code = 'ADMIN'`, `is_superuser=False`)

Инструмент: React `PlatformAdminShell`. Не имеет CompanyMember, не имеет коммерческого интереса в сделках. Бизнес-операции от лица компаний backend отвергает с `ADMIN_VIEWER_CANNOT_ACT`.

| Отвечает | Где в UI |
|---|---|
| Пользователи: создание, редактирование, смена SystemRole, toggle-active, удаление | Admin → Пользователи |
| Компании: реестр, правка реквизитов | Admin → Компании |
| KYC-верификация: L1→L2→L3, revoke, загрузка документов | Admin → KYC |
| Подписки поставщиков: создание, активация, приостановка, продление, фиксация оплаты | Admin → Подписки |
| Заявки на роли SUPPLIER / MANUFACTURER: approve / reject | Admin → Заявки на роли |
| Force-change Deal stage / Force-approve Quote / Force-cancel Contract | Admin → Сделки + контекстные кнопки на Quotes / Contracts |
| Админ-каталог: товары / категории / группы оборудования / офферы | Admin → Каталог |
| SystemSettings: VAT / margin / exchange rate / maintenance / 2FA | Settings → Платформа |

**НЕ делает:** не входит в команду компаний, не покупает / не продаёт / не подписывает / не платит от чьего-либо лица.

### Роль 3 — WorkspaceRole внутри SUPPLIER / MANUFACTURER (продающая сторона)

Это **не** SystemRole платформы. Это роль конкретного сотрудника **внутри своей компании-продавца**. Системно — все они `SystemRole.USER`.

| WorkspaceRole | Применимо к | Что делает |
|---|---|---|
| `OWNER` | любые CompanyType | Управляет командой, распределяет `can_sell`/`can_buy`, оплачивает подписку |
| `SALES_MANAGER` | `SUPPLIER` | Ведёт сделки своей компании: подача SupplierBid, формирование Quote, подпись Contract, генерация Invoice / Act, чат с клиентом, sales-аналитика |
| `LOGIST` | `SUPPLIER` | Управляет Fulfillment'ами после CLOSED_WON, отгрузка / трекинг |
| `CONTRACT_MANAGER` | `MANUFACTURER` | Подписывает контракты от лица производителя, ведёт договорной флоу |
| `FOREIGN_TRADE_SPECIALIST` | `MANUFACTURER` | ВЭД / экспортные документы для MFG |

**Гейтинг:** все write-сервисы (`submit_supplier_bid`, `generate_contract_from_quote`, `record_payment` и т.д.) проверяют `is_member_of(user, company_id, capability='sell')`. Per-member `can_sell` распределяет OWNER. Платформенный admin отсекается на shared actor-guard.

### Роль 4 — WorkspaceRole внутри CLIENT (покупающая сторона)

| WorkspaceRole | Применимо к | Что делает |
|---|---|---|
| `OWNER` | любые CompanyType | Профиль компании, KYC, инвайты, capabilities |
| `PROCUREMENT_MANAGER` | `CLIENT` | Создаёт RFQ, импортирует Excel-заявки, оценивает SupplierBid, принимает решение |
| `BUYER_MANAGER` | `CLIENT` | Сопровождает существующие сделки, чат с продавцом, фиксация платежей, приёмка по Fulfillment |

**Гейтинг:** `is_member_of(user, company_id, capability='buy')` для buyer-side операций. CLIENT-компании не нуждаются в SupplierSubscription (подписка только для SELLER/MANUFACTURER).

### Матрица зон

| Функция | Plat Engineer | Plat Admin | SUPPLIER OWNER | SUPPLIER SALES_MGR | SUPPLIER LOGIST | CLIENT OWNER | CLIENT PROC_MGR / BUYER_MGR |
|---|---|---|---|---|---|---|---|
| Миграции БД / deploy | ✅ | — | — | — | — | — | — |
| Master data CRUD | ✅ | — (read) | — | — | — | — | — |
| SystemSettings (VAT / margin) | ✅ | ✅ | — | — | — | — | — |
| Создание users / company | — | ✅ | — | — | — | — | — |
| KYC verify (L1→L2→L3) | — | ✅ | — | — | — | — | — |
| Subscription activate / suspend | — | ✅ | — | — | — | — | — |
| Pay subscription (от лица компании) | — | — | ✅ | — | — | — | — |
| Role application approve / reject | — | ✅ | — | — | — | — | — |
| Force Deal stage / Force-approve Quote / Force-cancel Contract | — | ✅ | — | — | — | — | — |
| Submit SupplierBid | — | — | ✅ | ✅ (если can_sell) | — | — | — |
| Build / send Quote, sign contract от лица seller | — | — | ✅ | ✅ | — | — | — |
| Open RFQ от лица buyer | — | — | — | — | — | ✅ | ✅ |
| Accept / Reject SupplierBid | — | — | — | — | — | ✅ | ✅ (если can_buy) |
| Sign contract от лица buyer | — | — | — | — | — | ✅ | ✅ |
| Record payment от лица buyer | — | — | — | — | — | ✅ | ✅ |
| Update fulfillment status (отгрузка) | — | — | ✅ | — | ✅ | — | — |
| Acceptance fulfillment (приёмка клиентом) | — | — | — | — | — | ✅ | ✅ |
| Распределение `can_sell` / `can_buy` среди членов | — | — | ✅ | — | — | ✅ | — |
| Invite team member | — | ✅ (для любой компании) | ✅ (своей) | — | — | ✅ (своей) | — |
| Upload KYC docs | — | ✅ (для любой) | ✅ (своей) | — | — | ✅ (своей) | — |

### Эскалация

```
Сотрудник компании (любой WorkspaceRole)
        ↓
   OWNER своей компании  ← решает большинство внутренних вопросов
        ↓
   Platform Admin        ← KYC, subscriptions, force-actions, спорные эскалации
        ↓
   Platform Engineer     ← технический сбой, миграции, master data
```

**Правило:** не эскалировать на Platform Engineer, пока не проверены React Admin контуры (KYC, подписки, role applications). 90% «сломалось» решается на уровне Platform Admin без Unfold.

## Последствия

### Положительные

- Единственный источник правды по ролям — `CustomUser.is_platform_admin` (model property) и `CompanyMember.role` + `can_sell/can_buy`. Нет дублирования смыслов.
- Невозможно «случайно» дать админу коммерческий доступ — миграция 0010 вычищает CompanyMember для всех ADMIN'ов; `add_company_member` отвергает попытку добавить admin'а в компанию.
- Workspace-роли применимы только к матчующим типам компаний (`applicable_to_types` M2M) — нельзя присвоить SALES_MANAGER в CLIENT-компании.
- Ясное место для расширения: новая бизнес-роль = новая запись в `WorkspaceRole`, без правок SystemRole / migration / permissions глобально.

### Отрицательные

- Любой кросс-компанейский «менеджер платформы» (как раньше SALES_MANAGER в смысле «сотрудник RailTech, который ведёт всех клиентов») теперь не существует на уровне SystemRole. Если такой роли потребуется — её надо реализовать как Platform Admin (всё видит) или как сотрудника RailTech-компании со своей WorkspaceRole.
- Force-actions (Quote / Contract) у Platform Admin пересекаются с `OWNER`/`SALES_MANAGER` зонами — это намеренно, для эскалаций. ActivityLog маркирует `[FORCE_ADMIN]`, чтобы аудит отделил force от обычного потока.

### Открытые задачи (следующий инкремент)

1. UI селектор смены SystemRole в `AdminUsersPage` уже отдаёт error code `ADMIN_ROLE_REQUIRES_NO_MEMBERSHIPS` — добавить inline-warning «Сначала отвяжите пользователя от всех компаний».
2. Owner-страница распределения `can_sell` / `can_buy` среди членов команды — endpoint готов (`update-member-capabilities`), UI ещё нет.
3. WorkspaceRole-aware navigation в AppShell — сейчас меню гейтится по SystemRole + activeStatus, надо учесть workspace_role (например, скрывать Sales Analytics у LOGIST).

## Ссылки

- ADR-0001: Разделение Django Unfold Admin и React Admin (`Docs/adr/0001-admin-separation.md`)
- `accounts/migrations/0010_platform_admin_model.py` — миграция инварианта
- `accounts/services.is_platform_admin_viewer` / `.add_company_member` / `.change_user_role` — гейты
- `core/permissions.py` — `IsPlatformAdmin`, `IsCompanyMemberOrPlatformAdmin`, `IsSupplierWithActiveSubscription`
- `memory/platform_owner_semantics_2026_04_19.md` — RailTech-company ≠ привилегии
- `memory/capabilities_and_seller_implies_buyer_2026_04_19.md` — per-member capabilities
- `memory/seed_via_migrations_rule_2026_04_19.md` — Rule 1 amendment
