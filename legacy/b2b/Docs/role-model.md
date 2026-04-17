---
title: Ролевая модель (RBAC) — RailTech B2B
project: RailTech B2B Ecosystem
type: rbac
version: 6.0 (Actualized)
status: Active
date: 2026-04-17
---

# Ролевая модель и контроль доступа

Доступ регламентирован на двух уровнях: **системные роли** (`SystemRole` → `CustomUser.role`) определяют место в экосистеме RailTech, **workspace-роли** (`WorkspaceRole` → `CompanyMember.role`) определяют полномочия внутри одной компании-клиента. Изоляция данных обеспечивается кастомными permission-классами (`IsOwnerOrManagerOrAdmin`, `IsManagerOrAdmin`) и override `get_queryset` в каждом ViewSet.

---

## 1. Системные роли (коды в seed_data)

Хранятся в `accounts.SystemRole` и задаются через foreign key на `CustomUser.role`.

### 1.1. GUEST

- **Область:** публичный B2B-каталог (цены скрыты до регистрации).
- **Ограничения:** один `Deal` в статусе `DRAFT`; нет доступа к WebSocket-чату, PDF, ценам.

### 1.2. CLIENT

- **Область:** верифицированный покупатель (`Company.types` содержит `CLIENT`).
- **Права:**
  - Создание сделок, импорт Excel-спецификаций, просмотр цен, принятие КП (`QUOTE_SENT → CONTRACT_SIGNED`).
  - WebSocket-чат по своим сделкам (`ChatConsumer` проверяет `CompanyMember.company == Deal.company`).
- **Изоляция:** `Deal.objects.filter(company=user.company_member.company)`.

### 1.3. SALES_MANAGER

- **Область:** верхний уровень воронки внутри RailTech (`is_staff_level=True`).
- **Права:**
  - KYC-верификация, обработка `Deal`, запуск Excel-импортов (Celery), работа в Sourcing Hub.
  - Quote Builder, генерация PDF, отправка КП.
- **Изоляция:** `Deal.objects.filter(Q(manager=user) | Q(manager__isnull=True))` — свои + нераспределённые.

### 1.4. ACCOUNT_MANAGER

- **Область:** сопровождение клиентов (`is_staff_level=True`).
- **Права:** идентично `SALES_MANAGER` + конвертация одобренных КП в договоры, контроль статусов поставки, прикрепление закрывающих документов.
- **Изоляция:** свои назначенные сделки.

### 1.5. ADMIN

- **Область:** супер-администратор (`is_staff_level=True`).
- **Права:** полный CRUD без фильтрации в `get_queryset`. Управление справочниками (master_data, EquipmentGroup, CompanyType), назначение ролей, глобальная аналитика, KYC.
- **Изоляция:** нет.

---

## 2. Workspace-роли (внутри одной Company)

Хранятся в `accounts.WorkspaceRole` и задаются через `CompanyMember.role`. Применимы только к пользователям с ролью `CLIENT`.

| Код | Описание | Полномочия |
| --- | --- | --- |
| `OWNER` | Владелец компании | Приглашение сотрудников, управление KYC-документами, подписки, управление ролями внутри компании |
| `ACCOUNTANT` | Бухгалтер | Просмотр и выгрузка финансовых документов, работа со статусами оплаты |
| `PROCUREMENT_MANAGER` | Снабженец | Создание сделок, импорт Excel, чат с менеджерами RailTech |

Приглашение нового сотрудника: `POST /api/v1/accounts/companies/{id}/invite/` (только `OWNER` или `ADMIN`).

---

## 3. Типы компании (`CompanyType`, M2M)

Одна компания может иметь несколько типов одновременно. Задаётся при одобрении `CompanyRoleApplication`:

| Код | Смысл |
| --- | --- |
| `CLIENT` | Покупатель (Buyer) — может создавать запросы, получать КП |
| `MANUFACTURER` | Производитель — может выставлять `SupplierOffer` с базовой ценой FCA |
| `SUPPLIER` | Поставщик (Seller) — перепродажа с наценкой |
| `LOGISTICS_PROVIDER` | Логистический партнёр — участвует в расчёте Landed Cost |

Фронтенд-маппинг (`userStore.loadFromAuth()` в `src/store/userStore.ts`) переводит `company_types[]` в `activeStatus`:

- `CLIENT` → `BUYER`
- `SUPPLIER` → `SELLER`
- `MANUFACTURER` → `MANUFACTURER`

`AppShell` использует `activeStatus` для показа контекстного меню (`getNavigation()`).

---

## 4. Permission-классы (backend)

Определены в `core/permissions.py`. Установлены через DRF `permission_classes` во ViewSets.

| Класс | Проверка |
| --- | --- |
| `IsAuthenticated` | Default на уровне DRF |
| `AllowAny` | Публичные эндпоинты (`auth/*`, `crm/leads/`, `health/`) |
| `IsManagerOrAdmin` | `user.role.code in ('ADMIN', 'SALES_MANAGER', 'ACCOUNT_MANAGER')` или `is_superuser` |
| `IsOwnerOrManagerOrAdmin` | Object-level: `obj.client == user` или `obj.manager == user` или `IsManagerOrAdmin` |
| `CustomIsAdminUser` | `user.role.code == 'ADMIN'` или `is_superuser` |

---

## 5. Access к Django Unfold

По ADR-0001 Unfold — инструмент инженеров, не бизнес-пользователей.

- **Разрешён:** `is_superuser=True` или membership в Django-группе `system_engineers` (группа управляется вручную).
- **Запрещён:** обычные `ADMIN`-пользователи работают в React Admin (`/admin/*` в SPA).
- **Read-only для бизнес-моделей:** `ReadOnlyInspectionMixin` применён к `Company`, `Deal`, `Lead`, `Message`, `Product`, `SupplierOffer`, `CompanyRoleApplication`, `SupplierSubscription`. Редкие аварийные действия помечены `[Emergency]` и доступны только superuser'ам (декоратор `@superuser_only_action` в `core/admin_mixins.py`).

---

## 6. Уведомления (`Notification`)

| Роль | Что получает |
| --- | --- |
| `GUEST` / `CLIENT` | Статусы сделок, чат-сообщения, результаты Excel-импорта, одобрение/отказ KYC |
| `SALES_MANAGER` / `ACCOUNT_MANAGER` | Новые назначенные сделки, сообщения от клиентов, завершение Celery-задач |
| `ADMIN` | Новые регистрации компаний (KYC-queue), role-applications, критические ошибки системы |

---

## 7. См. также

- [business-logic.md](business-logic.md) — сценарии использования и FSM.
- [adr/0001-admin-separation.md](adr/0001-admin-separation.md) — обоснование разделения Unfold vs React Admin.
- [architecture-diagrams.md](architecture-diagrams.md) — диаграмма ролей и мультитенантности.
- [../CLAUDE.md](../CLAUDE.md) — IRON RULE 2 (сравнение по `code`, не по `name`) и IRON RULE 8 (business logic only в services).
