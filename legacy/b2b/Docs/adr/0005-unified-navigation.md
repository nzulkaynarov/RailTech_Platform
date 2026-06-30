# ADR-0005 — Единый навигационный стандарт (capability-driven)

Status: Accepted (2026-06-30). Owner-approved IA = **объектная навигация + фильтр направления**;
старт реализации = **Phase A + B**.

## Context

Навигация была захардкожена по персоне (`getBuyerNavigation` / `getSellerNavigation` /
`getAdminNavigation`) → 6 навигационных поверхностей на 2 shells, три словаря для одного объекта
(`Deal` = my-requests / crm-deals / admin-deals), осиротевшие маршруты, «весь nav серый до KYC»
(антипаттерн), и невозможность поддержать компанию, которая одновременно покупает и продаёт.
Цель владельца: ОДИН стандарт навигации для buyer/seller/admin; роли продавца/покупателя
размываются; после KYC компания получает минимум, после оплаты — расширение.

## Decision

1. **Объектная первичная навигация** (НЕ Входящие/Исходящие): `Главная · Сделки · Документы ·
   Номенклатура · Сообщения · Настройки`. «Входящие/Исходящие» = **фильтр направления**
   (Полученные/Отправленные/Нужен ответ) ВНУТРИ Сделок и Документов. Обоснование: inbox/outbox
   ломается, когда «исходящее КП продавца = входящее КП покупателя» (одна компания делает оба);
   e-invoicing/Peppol-аналоги (Envoice/Odoo) уже отказались от отдельного инбокса; NN/g против
   контейнерной навигации. Сохранены верные идеи владельца: Главная как work-feed, глобальная
   кнопка **+Создать** (стандарт QuickBooks/Salesforce), Номенклатура и Настройки как разделы.

2. **Capability-driven рендеринг**: ОДИН `buildNavigation(capabilities)` вместо трёх per-persona
   функций. Каждый пункт декларирует `requires` (kyc / subscription / anyPerm / buy / sell); движок
   **ПРЯЧЕТ** (не дизейблит) то, что не выдано. UI-гейтинг ≠ безопасность — бэкенд enforcement
   (member_has_permission / подписка / KYC-floor) остаётся независимым.

3. **Один tenant-shell для buyer+seller** (различие = роль-на-сделке + capability, не отдельный
   shell). **Platform Operator остаётся отдельной плоскостью** (ADR-0004) на том же nav-движке —
   это cross-tenant separation, не per-role.

4. **Прогрессивные тиры**: T0 (KYC pending) = Главная/Профиль/каталог-read; T1 (KYC L2, без
   подписки) = создать заявку, принять/отклонить КП, подписать как покупатель, КП-draft + видеть
   маржу (продавец); T2 (подписка active) = полный seller-цикл (отправить КП → договор → счёт →
   акт, цены, публикация). Источник истины — `/me.capabilities`.

## Capability matrix (сокр.)

| Пункт / действие | KYC | Subscription | CompanyRole perm | Тир |
|---|---|---|---|---|
| Главная / профиль / browse каталог | — | — | — | T0 |
| Создать заявку, принять/отклонить КП, подписать (buyer) | L2 | — | request.create / quote.approve / contract.sign | T1 |
| КП-draft, видеть маржу/цены (seller) | L2 | — | quote.build / view_cost_margin / edit_pricing | T1 |
| Отправить КП, сгенерировать договор/счёт/акт, цены, публикация | L2 | **да** | chain / catalog.* | T2 |
| Команда/Настройки компании | — | — | team.manage / settings.edit | по perm |
| Operator-плоскость | n/a | n/a | OperatorPermission | Operator |

## Migration plan

- **Phase A (frontend)** — config-driven nav-движок (`src/config/navigation.tsx` +
  `buildNavigation`), объектная IA в AppShell, hide-not-disable, удаление осиротевших маршрутов.
  ✅ Реализовано.
- **Phase B (backend)** — `/me.capabilities` (consolidated object: kyc_level / can_buy / can_sell /
  subscription_active / effective CompanyRole permissions / is_platform_admin / operator_permissions).
  ✅ Реализовано.
- **Phase C** — слияние shell buyer+seller (убрать контекст-свитчер; обе стороны по capability).
- **Phase D** — org-модель: U1 (seed дефолтных ролей + assign на invite + backfill ✅), U2 (гейтить
  admin-hub по permission, не WorkspaceRole), U4 (раскол «Мой профиль» (личное) ↔ «Компания»; doc-
  profile наследует реквизиты), U5 (margin-настройки ✅).
- **Phase E** — переключить enforcement на матрицу + **KYC-floor на бэкенде** (сейчас KYC не гейтит
  бизнес-логику — Layer 0 gap); U3 (депрекация WorkspaceRole как enforcement, CompanyRole — единственный
  источник).
- **Phase F** — недостающее: Клиенты-REST (`ContactViewSet`), unified document direction-view,
  глобальный +Создать. НЕ строить: «письмо»-сущность (переиспользовать Message/EmailLog),
  «услуги»-сущность (Product с domain_type=SERVICES).

## Risks

Размытие ролей не должно ослабить серверные гейты: себестоимость/маржа остаются за
`quote.view_cost_margin`; `can_sell`/`can_buy` дефолтят True → Type-floor в `is_seller` обязан
остаться; routing-скоупинг (`seller_visible_deal_ids`) силосит чужие заявки;
`ADMIN_VIEWER_CANNOT_ACT` на каждом write. KYC-floor (Phase E) обязателен прежде, чем объявлять
«после KYC = минимум» реальностью. Eyes-on проверять в работающем приложении (не только tsc/тесты).
