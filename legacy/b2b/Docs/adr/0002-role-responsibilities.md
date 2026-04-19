# ADR-0002: Роли и зоны ответственности

**Status:** Accepted
**Date:** 2026-04-19
**Deciders:** Product owner + Engineering
**Related:** ADR-0001 (admin separation), `memory/platform_owner_semantics_2026_04_19.md`, `memory/admin_viewer_mode_2026_04_19.md`, `memory/capabilities_and_seller_implies_buyer_2026_04_19.md`

## Контекст

После принятия ADR-0001 у платформы два админ-периметра (Unfold — инженеры; React Admin — бизнес) и пять бизнес-ролей (Platform Engineer, Platform Admin, Sales Manager, Account Manager, Company Owner). Обязанности ролей раньше существовали только неявно в коде (permissions, services, меню). Это приводило к:

- эскалациям на Platform Engineer по задачам, решаемым в React Admin (KYC, подписки, role applications);
- путанице между «RailTech-компания» (равный участник рынка) и «`admin@railtech.uz`» (платформенный аккаунт модератора) — см. `platform_owner_semantics_2026_04_19.md`;
- смешению зон Sales Manager и Platform Admin при force-изменении Deal stage / Quote status;
- отсутствию канонического документа для onboarding новых сотрудников и агентов (Claude Code / прочих LLM).

## Решение

Фиксируем зоны ответственности пяти ролей + пути эскалации. Документ — **канонический источник истины**; Help-страница в SPA и раздел в `CLAUDE.md` — производные.

### Два админ-периметра (из ADR-0001)

| Периметр | Для кого | Когда |
|---|---|---|
| Django Unfold (`/admin/`) | Инженеры / DBA | Редкие ситуации: справочники, аварийные фиксы, аудит-просмотр |
| React Admin (пункты в меню SPA при `role=ADMIN`) | Бизнес-админ | Ежедневные операции |

### Роль 1 — Platform Engineer (`is_superuser=True`)

Инструмент: Unfold + терминал (compose / manage.py / миграции).

| Отвечает | Где именно |
|---|---|
| Развёртывание, миграции, Celery Beat расписание | `make up`, `make migrate`, Unfold → Periodic tasks |
| Master data: Currency / Country / Unit / DeliveryBasis | Unfold (ModelAdmin редактируемые) |
| SystemSettings (VAT, margin, exchange rate, maintenance_mode, 2FA) | Unfold `/admin/core/systemsetting/` или React Admin → Settings → Платформа |
| System roles (ADMIN / SALES_MANAGER / ACCOUNT_MANAGER) — назначение через Django | Unfold → CustomUser (пока REST-endpoint `assign-role` неполный) |
| Аварийные фиксы данных (битые записи после импорта, исправление статусов) | Unfold ReadOnlyInspectionMixin — временно снять → поправить → вернуть |
| Пересборка фронта/бэка при расхождениях | `docker compose build` |
| Суперадмин seed | `manage.py init_superadmin`, `core_seed` |
| Аудит: ActivityLog, QuoteItemHistory, pghistory | Unfold (read-only) |

**НЕ делает:** работу с клиентами / сделками / контрактами — это бизнес-роли.

### Роль 2 — Platform Admin (`role=ADMIN`, `is_staff=False`)

Инструмент: React SPA, нижнее меню (все `admin-*` страницы). Бизнес-операции от лица компаний **не совершает** (см. `admin_viewer_mode_2026_04_19.md`, backend отказ `ADMIN_VIEWER_CANNOT_ACT`).

| Отвечает | Где в UI |
|---|---|
| Пользователи: создать / редактировать / сменить роль / toggle-active / удалить | Admin → Пользователи |
| Компании: реестр, правка реквизитов, команда (invite members) | Admin → Компании |
| KYC-верификация: L1→L2→L3, revoke, загрузка документов | Admin → KYC |
| Подписки поставщиков: создать / активировать / приостановить / продлить / зафиксировать оплату | Admin → Подписки |
| Заявки на роли (SUPPLIER / MANUFACTURER): approve / reject | Admin → Заявки на роли |
| Force-change Deal stage (эскалация от менеджера) | Admin → Сделки (админ) |
| Админ-каталог: товары / категории / группы оборудования / офферы | Admin → Каталог |
| SystemSettings: правка VAT / margin / exchange rate / maintenance / 2FA | Settings → Платформа |

**НЕ делает:** технический deploy, миграции БД, прямые правки моделей через Django shell, **бизнес-операции от лица компаний** (покупать, продавать, подписывать, платить, подавать / принимать bid).

### Роль 3 — Sales Manager (`role=SALES_MANAGER`)

Инструмент: React SPA, CRM и Sourcing секции.

| Отвечает | Где в UI |
|---|---|
| FSM сделки: DRAFT → SOURCING → CALCULATING → QUOTE_SENT → CONTRACT_SIGNED → CLOSED_WON | Сделки → Detail Sheet → change-stage |
| Формирование Quote из QuoteItems (после импорта Excel или Smart Match) | Quotes → Create Quote |
| Landed Cost расчёт (logistics / customs / margin) | Quote Builder (per item) |
| PDF quote-а и `send_to_client` (замораживает цены) | Quote Detail → Generate PDF / Send |
| Quote → APPROVED / REJECTED (с причиной) | Quotes → Approve / Reject |
| После CLOSED_WON: генерация Contract / Invoice / Act | Контракты → Generate |
| Leads → Convert to Deal | Leads |
| Аналитика продаж | Sales Analytics |

**НЕ делает:** верификацию KYC, создание компаний, правку master data.

### Роль 4 — Account Manager (`role=ACCOUNT_MANAGER`)

Инструмент: React SPA, CRM + помощь клиентам.

| Отвечает | Где в UI |
|---|---|
| Сопровождение существующих клиентов | Clients |
| KYC-ассист: помогает клиенту загрузить документы, эскалирует Platform Admin на approve | KYC (view-only), координация через Admin |
| Чат в сделке, сообщения | Deal → Messages |
| Просмотр Acts / Fulfillments | Billing → Acts, Fulfillments |
| Повторные продажи, cross-sell в рамках верифицированных клиентов | Deals (фильтр по company) |

**НЕ делает:** смена Deal stage в CALCULATING / QUOTE_SENT (зона Sales Manager), force-actions.

### Роль 5 — Company Owner (`workspace_role=OWNER` в `CompanyMember`)

Инструмент: React SPA в контексте своей компании (не платформы). Per-member capabilities (`can_sell` / `can_buy`) распределяет сам — см. `capabilities_and_seller_implies_buyer_2026_04_19.md`.

| Отвечает | Где в UI |
|---|---|
| Profile / Company registry правка (только до верификации) | Profile |
| Приглашение членов команды (`POST /companies/{id}/invite/`) | Profile → Team |
| Распределение `can_sell` / `can_buy` между членами команды | Profile → Team → Capabilities |
| Загрузка KYC документов | Profile / KYC |
| Подача `CompanyRoleApplication` для апгрейда CLIENT → SUPPLIER / MANUFACTURER | Role Apps |
| Оплата `SupplierSubscription` (если SELLER / MANUFACTURER) | Settings → Billing |

**НЕ делает:** видит только свои данные, всё по multi-tenancy через `CompanyMember`.

### Матрица зон

| Функция | Plat Eng | Plat Admin | Sales Mgr | Account Mgr | Owner |
|---|---|---|---|---|---|
| Миграции БД / deploy | ✅ | — | — | — | — |
| Master data CRUD | ✅ | — (read) | — | — | — |
| SystemSettings (VAT / margin) | ✅ | ✅ | — | — | — |
| Создание users / company | — | ✅ | — | — | — |
| KYC verify (L1→L2→L3) | — | ✅ | — | — | — |
| Subscription activate / suspend / pay (от лица платформы) | — | ✅ | — | — | — |
| Role application approve / reject | — | ✅ | — | — | — |
| Force Deal stage change | — | ✅ | — | — | — |
| Normal Deal stage change (FSM) | — | — | ✅ | — | — |
| Create Quote / Generate PDF / Send | — | — | ✅ | — | — |
| Approve / Reject Quote | — | — | ✅ | — | — |
| Contract generate + send-for-sign | — | — | ✅ | — | — |
| Client chat / messages | — | — | ✅ | ✅ | — |
| Lead convert | — | — | ✅ | — | — |
| Company own profile edit | — | — | — | — | ✅ |
| Invite team member | — | ✅ (for any) | — | — | ✅ (own) |
| Distribute `can_sell` / `can_buy` | — | — | — | — | ✅ |
| Upload KYC docs | — | ✅ (for any) | — | — | ✅ (own) |
| Pay own subscription | — | — | — | — | ✅ |
| Audit log view | ✅ (Unfold) | ✅ (React Admin) | ✅ (свои) | ✅ (свои) | — |

### Эскалация

```
Owner / Company user problem → Account Manager → Sales Manager → Platform Admin → Platform Engineer
            (UX / общий вопрос)     (процесс сделки)    (стратегия / спор)  (KYC / биллинг)     (технический сбой)
```

**Правило:** не эскалировать на Platform Engineer, пока не проверен React Admin контур (KYC, подписки, role applications). ~90% «сломалось» решается на уровне Platform Admin без Unfold.

## Последствия

### Положительные

- Каноничный документ для onboarding сотрудников и LLM-агентов.
- Снимает конфликт «RailTech-компания vs. `admin@railtech.uz`» — закрепляет, что платформенные права принадлежат пользовательскому аккаунту, а не юрлицу.
- Чёткий путь эскалации — меньше прямых обращений на Platform Engineer.
- Для новых features легко определить «где это живёт»: смотрим матрицу, находим роль, берём её периметр (Unfold / React Admin / SPA-cabinet).

### Отрицательные

- Требует поддержки в трёх местах: `Docs/adr/0002-*.md`, Help-страница в SPA, `CLAUDE.md`. При изменении ADR-0002 — обновлять все три.
- Force-actions у Platform Admin частично пересекаются с зоной Sales Manager (force Deal stage) — это сделано намеренно (эскалация), но требует логирования actor в ActivityLog, чтобы отличать force от обычного.

### Открытые задачи (следующий инкремент)

1. **Lead convert CRIT-2** — проверить реальный фикс (роут `#leads` → Convert работает, не redirect на dashboard).
2. **Назначение SystemRole в React Admin** — добавить dropdown ролей в `AdminUsersPage` через существующий `change-role` endpoint, чтобы Platform Engineer перестал быть единственной точкой назначения ролей.
3. **Кнопка «Оплатить» в AdminSubscriptions** — подключить существующий хук `paySubscription` к UI-кнопке.
4. **Force-страницы Quote / Contract для Platform Admin** — endpoint + страница для эскалаций (cancel contract, force-approve quote), чтобы не идти через Unfold.

## Ссылки

- ADR-0001: Разделение Django Unfold Admin и React Admin (`Docs/adr/0001-admin-separation.md`)
- `memory/platform_owner_semantics_2026_04_19.md` — RailTech-company ≠ привилегии
- `memory/admin_viewer_mode_2026_04_19.md` — admin как viewer
- `memory/capabilities_and_seller_implies_buyer_2026_04_19.md` — per-member capabilities
- `memory/seed_via_migrations_rule_2026_04_19.md` — Rule 1 amendment
