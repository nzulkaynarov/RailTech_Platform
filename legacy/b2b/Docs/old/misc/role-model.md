---
title: Ролевая модель (RBAC) — RailTech B2B
project: RailTech B2B Ecosystem
type: rbac
version: 7.0 (Actualized)
status: Active
date: 2026-06-11
---

# Ролевая модель и контроль доступа

> **Канонический источник — [adr/0002-role-responsibilities.md](adr/0002-role-responsibilities.md).**
> Этот файл — краткая актуальная сводка. При расхождении верить ADR-0002 и коду
> (`accounts/constants.py`, `accounts/services/permissions.py`).

Доступ регламентирован на **трёх независимых уровнях** (не взаимозаменяемых):

1. **`SystemRole`** (`CustomUser.role`) — место в экосистеме платформы.
2. **`WorkspaceRole`** (`CompanyMember.role`) — должность внутри одной компании.
3. **Per-member capabilities** (`CompanyMember.can_sell` / `can_buy`) — что член команды может делать.

Изоляция данных — кастомные permission-классы + override `get_queryset` в каждом ViewSet.

---

## 0. Доменная модель (owner-confirmed 2026-06-10)

- **ООО RailTech** — владелец платформы **И** её пользователь в роли **ПРОДАВЦА** (seller).
  Продавец — это команда (OWNER + Менеджер продаж + ВЭД + Директор = цепочка
  согласования КП). Сейчас система работает в формате **Покупатель ↔ Продавец**.
- **Поток:** Покупатель формирует **заявку** (`Deal`) → **Продавец** готовит **КП**
  (`Quote`) → одобренное КП становится Спецификацией договора.
  **Покупатель НИКОГДА не строит КП** (это была «каша по ролям» — исправлено).
- **MANUFACTURER** — пока только справочное измерение каталога (происхождение товара),
  компании создаёт бизнес-админ. Реальных пользователей-производителей нет.

---

## 1. SystemRole (`accounts.SystemRole` → `CustomUser.role`)

> ⚠️ Миграция `accounts/0010_platform_admin_model` **удалила** `SALES_MANAGER` и
> `ACCOUNT_MANAGER` как системные роли. Они теперь существуют **только** как
> `WorkspaceRole`. Остались **две** системные роли:

| Код | Кто | Инструмент |
| --- | --- | --- |
| `ADMIN` | Platform Admin — модерация платформы, **без** membership в компаниях | `PlatformAdminShell` (SPA, `/admin/*`) |
| `USER` | Все остальные (члены компаний) | `AppShell` (контексты Buyer/Seller/Manufacturer) |

Platform Engineer (`is_superuser=True`) — отдельный уровень: Unfold + терминал,
деплой/миграции/master data, **не** ведёт бизнес-операции от лица компаний.

Platform Admin **не может** действовать от лица компании: backend возвращает
`ADMIN_VIEWER_CANNOT_ACT` (`is_platform_admin_viewer`).

---

## 2. WorkspaceRole (`accounts.WorkspaceRole` → `CompanyMember.role`)

Применимость роли к типу компании ограничена полем `applicable_to_types`.

| Код | Сторона | Назначение |
| --- | --- | --- |
| `OWNER` | любая | Владелец: приглашения, KYC-документы, подписки, раздача `can_sell`/`can_buy` |
| `SALES_MANAGER` | seller | Сборка и отправка КП, аналитика продаж |
| `FOREIGN_TRADE_SPECIALIST` (ВЭД) | seller | Согласование КП (Landed Cost / импорт) |
| `CONTRACT_MANAGER` | seller | Договоры, спецификации |
| `LOGIST` | seller | Поставка/fulfillment |
| `PROCUREMENT_MANAGER` | buyer | Создание заявок, импорт Excel |
| `BUYER_MANAGER` | buyer | Приём/отклонение КП, оплата, приёмка |

Приглашение сотрудника: `POST /api/v1/accounts/companies/{id}/invite/` (только `OWNER`/`ADMIN`).

---

## 3. Типы компании (`CompanyType`, M2M)

| Код | Frontend `activeStatus` | Смысл |
| --- | --- | --- |
| `CLIENT` | `BUYER` | Покупатель — создаёт заявки, принимает КП |
| `SUPPLIER` | `SELLER` | Продавец — строит/владеет КП, перепродажа с наценкой |
| `MANUFACTURER` | `MANUFACTURER` | Производитель — `SupplierOffer` с базовой ценой FCA |

Маппинг — `userStore.loadFromAuth()`; `AppShell` показывает контекстное меню по `activeStatus`.

---

## 4. Capabilities и определение «продавца/покупателя»

`CompanyMember.can_sell` / `can_buy` — **по умолчанию `True`**.

> 🔴 **КРИТИЧНО:** определять «продавец» по одному `can_sell` НЕЛЬЗЯ — он defaults `True`,
> поэтому свежезарегистрированный CLIENT прошёл бы как продавец и увидел чужие сделки
> (реальная утечка, исправлена 2026-06-11). «Продавец» = член компании, чей
> `CompanyType` ∈ `SELLER_COMPANY_TYPES` (`SUPPLIER`, `MANUFACTURER`) **И** `can_sell`.

Реализация — `accounts/services/permissions.py`:

- `is_seller(user)` / `primary_seller_company_id(user)` — требуют
  `company__types__code__in=SELLER_COMPANY_TYPES`.
- `is_member_of(user, company_id, capability='sell'|'buy')` — членство + capability.
- `is_platform_admin_viewer(user)` — Platform Admin, действие запрещено.
- `company_has_operational_subscription(company_id)` — гейт для продавца-писателя.

КП-гейты (`crm/views/quotes.py`): create требует `is_seller`
(`ONLY_SELLER_CAN_BUILD_QUOTE`), `prepared_by` штампуется сервером;
approve/reject требуют `can_buy` у `deal.company`.

---

## 5. Типизированные константы (single source of truth)

Сравнение по `code` (IRON RULE 2) теперь через константы, не магические строки:

- Backend: `accounts/constants.py` (`SystemRoleCode`, `WorkspaceRoleCode`,
  `CompanyTypeCode`, `VerificationStatusCode`, `SELLER_COMPANY_TYPES`),
  `crm/constants.py` (`DealStageCode`, `QuoteStatusCode`).
- Frontend: `frontend/src/lib/codes.ts` (`DealStage`, `QuoteStatus`,
  `ContractStatus`, `FulfillmentStatus`, `SupplierBidStatus`, `CompanyType`,
  `VerificationStatus`).

---

## 6. Доступ к Django Unfold

По ADR-0001 Unfold — инструмент инженеров. Разрешён `is_superuser=True`.
Бизнес-операции — в React Admin (`PlatformAdminShell`). Бизнес-модели в Unfold —
read-only (`ReadOnlyInspectionMixin`); аварийные действия `[Emergency]` — только superuser.

---

## 7. См. также

- [adr/0002-role-responsibilities.md](adr/0002-role-responsibilities.md) — **канонический** источник.
- [adr/0001-admin-separation.md](adr/0001-admin-separation.md) — Unfold vs React Admin.
- [business-logic.md](business-logic.md) — заявка → КП → договор, FSM, цепочка согласования.
- [../CLAUDE.md](../CLAUDE.md) — IRON RULE 2 (сравнение по `code`) и IRON RULE 8 (логика в services).
