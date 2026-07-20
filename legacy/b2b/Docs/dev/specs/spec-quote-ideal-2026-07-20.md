# КП-конструктор → идеал: аудит + план рефакторинга/дебага (2026-07-20)

_База: main `4954b78` (после #355). Аудит проведён 4 параллельными Opus-агентами (frontend, backend-pricing, seller-flow/калькулятор, долги/тесты/i18n) + живой локальный смоук. Статус: **план УТВЕРЖДЁН владельцем 2026-07-20, реализация НЕ начата (продолжение на другом компьютере).**_

> **РЕШЕНИЯ ВЛАДЕЛЬЦА (2026-07-20):**
> - **DT1 (маржа):** реализовать **per-line override** — per-line `margin_percent` должна реально применяться в `calculate_item_prices`/`recalculate_quote` (передавать `None` для позиций, где хотят позиционную маржу; иначе — `quote.margin_percent`). Обновить аудит-историю (`pricing.py:209`) на эффективную маржу. Как в Salesforce CPQ/Odoo.
> - **F3 (калькулятор):** `Deal.company` → **nullable** (не self-компания). Обязателен аудит None-guard перед миграцией (номер КП, PDF-заголовок `KP_{company.inn}_…` lifecycle.py:133, register_new_deal, любые `deal.company.name/.inn`).
> - **Порядок волн:** не зафиксирован — начать с любой на свежей сессии; рекомендация автора — Волна A (money-path) первой.

Цель владельца: довести КП-конструктор (основная рабочая область продавцов) до уровня мировых CPQ (Salesforce CPQ, Odoo, QuickBooks/Xero, PandaDoc, Stripe). Решения — по мировому опыту, не по частным хотелкам.

---

## 0. Что подтверждено КОРРЕКТНЫМ (не трогаем)

- **Движок маржи исправен.** «final==base» в смоуке — неполный сид (не выставлен `quote.margin_percent`); маржа ставится на весь КП, per-line `margin_percent` — «задел». Наценка на себестоимость (`final=landed*(1+margin)`), 20% markup = 16.7% margin-on-price.
- **`billable()`-фильтр полон** (subtotal/economics/COGS/инвойс/контракт/PDF) — S1-BLOCKER не рецидивирует. Единственный `.items.all()` (seller-экспорт) — презентационный, display_type-aware, не суммирует.
- **Каскад charges, compute_quote_economics (все ветки), FSM-переходы, below_cost hard-block, S7a below-floor** — корректны и атомарны.
- **Виртуализация проверена глазами** (60 строк, скролл, inline-edit в середине) — работает; наблюдался scroll-to-top при клике (см. B3).
- **Офлайн-клиент: модель + сервис + email + публичный токен + гейты — солидный фундамент** (нужна одна routing-строка, см. F1).
- Прод-код чист: 0 TODO/FIXME, i18n симметричен, нет `as any`/hex/`text-[Npx]`.

---

## 1. BUGS — корректность (чинить первыми)

| # | Severity | Что | Файл | Фикс |
|---|----------|-----|------|------|
| **B1** | **HIGH** | **Валюта инвойса/контракта = валюта СЕБЕСТОИМОСТИ строки, суммы — в UZS.** При non-UZS себестоимости (импортная ж/д техника, USD/EUR) юр. документ показывает «$1 200 000» вместо 1,2 млн сум (~12000× мисрепрезент). | `crm/services/billing.py:98`, `crm/services/contracts.py:91` | `currency=quote.quote_currency` (презентационная, гарантированно UZS) в обоих материализаторах. Тривиально, эффект крупный. |
| **B2** | MED | **Столбец имени обрезается рано + пустота справа.** Нет резиновой колонки-поглотителя (`w-full`) + flex-цепочка не пробрасывает ширину (`min-w-0`/`w-full` отсутствуют на обёртках). | `QuoteBuilder/GridTable.tsx:65`, `GridRow.tsx:167-168`, `ProductNameCell.tsx:138` | `w-full` на `<th>`/`<td>` имени + `min-w-0 w-full` на 2 flex-обёртки; `title`-tooltip уже есть. ~10 строк CSS, высокий визуальный эффект. Мировая практика: резиновое имя + фикс-числовые. **Ручной drag-resize НЕ делаем** (переусложнение для quote-editor). |
| **B3** | MED | **Виртуализация: scroll-to-top при клике + дрейф при разворачивании.** (1) `measureElement` ref обёрнут в свежую стрелку на каждый рендер → churn ResizeObserver → сброс окна на любой ре-рендер фасада. (2) main- и detail-строка несут ОДИН `data-index` → в кеш высот попадает только detail, `getTotalSize()` занижен. | `GridRow.tsx:91-105,112,312` | Стабилизировать ref (`virtualizer.measureElement` напрямую / `useCallback`); один измеряемый узел на индекс (detail — вне виртуалього потока или отдельный индекс). **Обязательно проверить реальной прокруткой.** |
| **B4** | MED | **Гонка одиночного PATCH оптимистичной блокировки (TOCTOU).** `update()` читает version обычным SELECT, инкремент без `WHERE version=old`, не в `atomic`. Два параллельных PATCH затирают друг друга. Bulk-путь защищён `select_for_update`, одиночный — нет. | `crm/views/quotes/items.py:161-191` | Обернуть в `transaction.atomic` + `select_for_update`/условный UPDATE по version. Выровнять с bulk. |
| **B5** | LOW-латент | **`send_quote_email` при отсутствии получателя молча пропускает письмо, но КП помечается SENT** — «отправлен в никуда». | `crm/tasks.py:422-424` | Жёсткий синхронный гейт `RECIPIENT_REQUIRED` в `send_to_client` (пересекается с F3-калькулятором). |

---

## 2. DEBT / ловушки

| # | Severity | Что | Где | Решение |
|---|----------|-----|-----|---------|
| **DT1** | MED | **Per-line `margin_percent` записываемо, но игнорируется пересчётом** (`quote.margin_percent` побеждает). Менеджер задаёт маржу на позицию через грид/bulk/Excel — сохраняется, пишется в аудит, но КП считается по КП-марже. «Наполовину сделанная» фича. Аудит-история пишет НЕ применённую маржу. | `serializers/item.py:67,173`, `bulk.py:36,196`, `pricing.py:209`, `useQuoteBuilderActions.ts:118` | **OWNER-РЕШЕНИЕ**: (а) сделать read-only на входе (проще, ⌂ текущему движку) ИЛИ (б) реально задействовать per-line override (гибче, ближе к части CPQ). |
| **DT2** | MED | **`economics` — нетипизированный `SerializerMethodField`** (`{[key]:unknown}`); фронт активно читает `economics.below_floor/below_cost/min_margin_percent` из локального типа → бэк и фронт расходятся МОЛЧА, без CI-сигнала. `below_floor` в schema.d.ts 0 раз. | `crm/serializers/quote.py` (economics), `EconomicsRail.tsx`, `ChargeCascadeTable.tsx:41` | Аннотировать через `@extend_schema_field` (typed dict/inline serializer) → форма в OpenAPI → типобезопасный фронт. |
| **DT3** | MED | **RULE >500/>50**: фасад `Admin/QuoteBuilderGrid.tsx` 528; `lifecycle.py` 596 (`send_to_client` ~188); `views/quotes/quotes.py` 640. | — | Распил: фасад → `<GridDialogs/>` + `useRailState`; `send_to_client` → хелперы (гейты/audit); approval-цепочка views → mixin. Совместить с добором тестов T1/T3. |
| **DT4** | MED | **Perf: pricing-assist делает N последовательных `await PATCH`** (N рефетчей + мерцание); `GridRow` не мемоизирован (любой ре-рендер фасада ре-рендерит все видимые строки). | `useQuoteBuilderActions.ts:429`, `GridRow.tsx` | Один bulk-update; `React.memo` на GridRow + вынос `marginCell`/`lineSignal`. |
| **DT5** | LOW | **S7b — локализация lookup-`name`**: `QuoteApprovalQueue.tsx:59` (`status_name`), `QuotesPage.tsx:233` (фильтр) рендерят RU-`name` в EN-UI. Мапа `quoteStatusLabelKey` УЖЕ готова (`lib/codes.ts:76`), надо применить. | — | Разнести вызовы. Дёшево. |
| **DT6** | LOW | Типо-небезопасность: `as unknown as Record` на bulk-эндпоинтах (`useQuoteBuilderActions.ts:231,322`); `eslint-disable exhaustive-deps` в `usePricingMirror.ts:364` (риск устаревшего preview «денег до копейки»). | — | Типизировать bulk-контракт; пересмотреть deps. |
| **DT7** | LOW | a11y: непоследовательные `aria-label` на icon-кнопках (`GridRow.tsx:305` только `title`); чекбокс через `onClick`+`shiftKey`-каст вместо `onCheckedChange`. | — | `aria-label` везде; аккуратный shift-range. |
| **DT8** | LOW | WorkspaceRole legacy-мост `_has_legacy_send_role` для un-migrated members — документирован, слегка расходится с «U3 COMPLETE». Умрёт, когда у всех CompanyRole. | `access.py:107-123` | Оставить, отметить. |
| **DT9** | LOW | Fast-follows (остаток): тихий кламп bulk → toast; тесная ячейка chevron+error на узких; Enter на последней add-row роняет фокус; SERVICES-preview завышает landed_cost до сохранения. | — | Мелочи, батчем. |

---

## 3. UX до уровня CPQ-лидеров

| # | Что отсутствует vs лидеры | Value/Effort |
|---|---------------------------|--------------|
| **U1** | **Реордер ITEM-строк** — ↑/↓ swap есть только у SECTION/NOTE; у товарных строк нет ни кнопок, ни drag. Бэк уже умеет swap position. | Высокий / низкий — **лучший value/effort** |
| **U2** | **Вертикальный хром съедает высоту грида на 14"** (корень жалобы владельца «видно 3 строки»): page-toolbar + note + send-banner + builder-toolbar + selection-toolbar + Tabs + sticky-totals. Fullscreen есть, но дефолт тесный. | Высокий / средний |
| **U3** | **Свободный ввод имени ITEM не сохраняется** — печать без выбора из typeahead откатывается на blur (`imported_raw_name` не редактируется inline). Против ожиданий line-editor'ов. | Средний / низкий |
| **U4** | Нет поиска/фильтра внутри длинного КП. | Средний / низкий |
| **U5** | Нет группировки/сворачивания/отступа позиций под секцией (плоские heading-строки). | Средний / средний |
| **U6** | Клавиатура неполная: нет Left/Right между колонками, Tab не по-ячейкам, нет redo, нет copy-out выделенных. | Средний / средний |
| **U7** | Density-переключатель (comfortable/compact) — вторично (корень — хром U2, не высота строк). | Низкий / низкий |

---

## 4. FEATURE: продавцовый «КП с нуля» + офлайн-клиент + калькулятор

_Ответ на второй вопрос владельца. Фундамент офлайн-клиента почти готов — не хватает одной routing-строки и UI-входа._

| Волна | Что | Разрыв | Объём |
|-------|-----|--------|-------|
| **F1** | **Починить keystone офлайн-пути**: авто-`DealSellerRouting(seller_company=primary_seller_company(actor))` при создании сделки по `contact_id`. Сейчас офлайн-сделка НЕВИДИМА создателю (`seller_visible_deal_ids` = routing-only) → нельзя claim/build/send. | GAP-2/3 (BUG) | Малый — разблокирует уже написанный backend end-to-end |
| **F2** | **Продавцовый UI-вход «Новый КП»**: кнопка на продавцовой стороне → диалог «из книги контрагентов / создать инлайн (reuse `CreateOfflineClientDialog`) / без клиента» → deal с `contact_id` → редирект в билдер. Даёт кейс (B) — КП для компании не на платформе. | GAP-1 | Средний |
| **F3** | **Калькулятор-черновик (кейс A)**: `Deal.company` → nullable + None-guards (номер КП, PDF-заголовок, register_new_deal); scoping по creator; билдер с пустой company + баннер «Черновик без клиента»; жёсткий гейт `RECIPIENT_REQUIRED` на «Отправить» + диалог «выбрать/создать получателя». | GAP-4 + B5 | Средне-крупный (миграция + аудит None-guard) |
| **F4** | Промоут-инвайт проставляет `deal.client` на исторических сделках контакта (после регистрации клиент видит ранее отправленные КП). | GAP-5 | Малый, не блокер |

Гейты (KYC L2 продавца, `quote.send` entitlement, below_cost/FX/below_floor) завязаны на seller_company — офлайн-получатель их НЕ ослабляет. Дедуп/книга изолированы по тенанту (чужой контрагент не утечёт). **OWNER-РЕШЕНИЕ по F3**: `Deal.company` nullable (чище данные) vs служебная «self»-компания (меньше scoping-правок, грязнее).

---

## 5. TESTS

| # | Дыра | Оценка |
|---|------|--------|
| **T1** | Below-floor justification **FRONTEND**-флоу (2 cost-visibility пути в ConfirmActionDialog) — верифицирован вручную (#355) + глазами сегодня, но нет vitest. | Med / S |
| **T2** | Виртуализация — только unit-хелпер; поведение (sticky/keyboard через окно/Shift-select по невидимым) — Playwright/eyes-on (частично закрыто сегодняшним смоуком). | Med / M |
| **T3** | `quote.sent_below_floor` audit-event — нет явного теста записи ActivityLog. | Low-Med / S |

---

## 6. Предлагаемая последовательность (волны, каждая = PR через ревью + локальную проверку + owner-merge)

**Волна A — Money-path + быстрые победы (max value / low effort):**
- B1 валюта инвойса/контракта (**HIGH bug**), B2 ширина имени, DT5 S7b i18n, B5 гейт `RECIPIENT_REQUIRED` (safety-часть).

**Волна B — Виртуализация + робастность грида:**
- B3 measureElement + data-index (+ eyes-on), DT4 GridRow memo + bulk pricing-assist.

**Волна C — Схема/типизация + распил + решение по марже:**
- DT2 типизация economics, DT3 распил (фасад/lifecycle/views) + добор T1/T3, DT1 маржа (после owner-решения).

**Волна D — UX до CPQ:**
- U1 реордер ITEM (первым — value/effort), U2 сжатие хрома, U3 free-text имя, затем U4/U6/U5/U7.

**Волна E — Продавцовый КП / офлайн / калькулятор:**
- F1 → F2 → F3 → F4 (в этом порядке; F1 разблокирует, F3 после owner-решения по nullable).

**Волна F — Тест-долг:** T1, T3, T2/Playwright.

**OWNER-блокеры (не код):** CI billing-dead (гейты локально); Click/Payme/E-IMZO by design; coverage 30→70 ждёт живого CI.

**Решения владельца, нужные до кода:** (1) DT1 маржа — read-only vs per-line override; (2) F3 — `Deal.company` nullable vs self-company; (3) приоритет волн D vs E (полировка UX vs новая фича продавцового КП).
