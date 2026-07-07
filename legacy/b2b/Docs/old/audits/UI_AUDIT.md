# RailTech SaaS B2B — UI Audit (жёсткий прогон по каждой кнопке)

**Дата:** 2026-04-18
**Checkout:** `HEAD = 6652840`
**Скоуп:** весь `frontend/src/` — навигация, страницы, диалоги, формы, кнопки, формы, дропдауны, эмпти-стейты, i18n, дизайн-токены.

**Цель** — найти всё, что создаёт у пользователя одно из четырёх впечатлений:
1. «Кнопка есть, но ничего не происходит».
2. «Меня молча выкинуло на главную».
3. «Я вижу интерфейс, но меня в нём нет» (роль не совпадает с фичей).
4. «Вижу куски чужого языка / mock-данных / заглушек».

Визуальный gap-матрица: [`ui_gap_table.drawio`](./ui_gap_table.drawio) (20 menu-items × 5 ролей, 20 багов c severity).

---

## TL;DR

| Метрика | Значение |
|---|---|
| Критических дефектов (CRIT) | **8** |
| Высоких (HIGH) | **8** |
| Средних (MED) | **4** |
| Низких (LOW) | **2** |
| Захардкоженные English-строки в UI | **≥ 10** (только в `RequestDetailPage`) |
| `window.confirm()` вместо AlertDialog | **2** |
| Кнопки без `onClick` / с битым target | **4** |
| Пункты меню, редиректящие роль на dashboard | **1** (TRAP: SELLER → Leads) |
| Роль без необходимой страницы (menu gap) | **5** (BUYER, MFG × 4) |
| Страницы полностью пустые для роли | **1** (`BuyerAnalytics`) |

---

## 1. Role-parity матрица

Сводная таблица — какие пункты меню показываются каким ролям. Сгенерирована из `frontend/src/layouts/AppShell.tsx` (`getBuyerNavigation`, `getManufacturerNavigation`, `getSellerNavigation`, `getBottomNavigation`) и `frontend/src/App.tsx` (`ADMIN_PAGES`, `KYC_ALLOWED_PAGES`, role-guard в `useEffect`).

Условные обозначения:

- ✓ — видно и кликабельно по назначению
- — — пункта **нет** в сайдбаре этой роли
- **mgr/admin** — пункт виден только при `role ∈ {ADMIN, MANAGER}`
- **TRAP** — пункт **виден, но role-guard редиректит** на Dashboard
- *n/a* — намеренно отсутствует по бизнес-смыслу

| Menu ID | BUYER | SELLER | MFG | MFG+MANAGER | ADMIN | Комментарий |
|---|:---:|:---:|:---:|:---:|:---:|---|
| dashboard | ✓ | ✓ | ✓ | ✓ | ✓ | |
| products (catalog) | ✓ | ✓ | ✓ | ✓ | ✓ | |
| my-requests | ✓ | — | — | — | — | только BUYER |
| crm-deals | ✓ | ✓ | ✓ | ✓ | — | |
| crm-quotes | ✓ | ✓ | ✓ | ✓ | — | |
| crm-clients | mgr/admin | ✓ | — | — | — | **MFG не видит клиентов** |
| **leads** | — | **TRAP** | — | — | ✓ | **SELLER видит кнопку, guard редиректит** |
| sourcing-requests | — | ✓ | ✓ | ✓ | — | |
| **sourcing-import** | — | ✓ | **—** | **—** | — | **MFG лишён Excel-импорта** |
| sourcing-match | — | ✓ | ✓ | ✓ | — | |
| **supplier-bids** | **—** | ✓ | ✓ | ✓ | — | **BUYER не видит ставок на свой RFQ** |
| contracts | ✓ | ✓ | ✓ | ✓ | — | |
| invoices | ✓ | ✓ | ✓ | ✓ | — | |
| **payments** | ✓ | ✓ | **—** | **—** | — | **MFG лишён Payments** |
| acts | ✓ | ✓ | ✓ | ✓ | — | |
| fulfillments | ✓ | ✓ | ✓ | ✓ | — | |
| **analytics** | mgr/admin* | mgr/admin | mgr/admin | ✓ | — | *`BuyerAnalytics` — пустая страница* |
| categories | — | ✓ | ✓ | ✓ | ✓ | |
| equipment-groups | — | ✓ | ✓ | ✓ | ✓ | |
| admin-* (8 pages) | — | — | — | — | ✓ | |
| help / settings | ✓ | ✓ | ✓ | ✓ | ✓ | |

**5 gap'ов в навигации:**

1. 🔴 **BUYER — нет Supplier Bids.** `getBuyerNavigation` (AppShell.tsx:100-124) не добавляет `supplier-bids`. Backend отдаёт ставки через `/api/v1/crm/supplier-bids/` (фильтрует по deal.client), но UI у BUYER нет → победителя выбрать невозможно.
2. 🔴 **SELLER — Leads = TRAP.** `AppShell.tsx:189` показывает пункт «Leads» внутри CRM-подменю. `App.tsx:217-222` включает `'leads'` в `ADMIN_PAGES`. Role-guard в `App.tsx:248-251` и `:299-302` молча редиректит на dashboard.
3. 🔴 **MFG — нет Excel Import.** `getManufacturerNavigation` (AppShell.tsx:138-143) показывает только `sourcing-requests` и `sourcing-match`. У SELLER (AppShell.tsx:179) в том же блоке есть `sourcing-import`.
4. 🔴 **MFG — нет Clients, Leads, My Requests.** MFG с `role=MANAGER` всё равно не получает эти пункты — условие `role === 'MANAGER'` в `AppShell.tsx:158` добавляет только `productionAnalytics`.
5. 🔴 **MFG — нет Payments.** `AppShell.tsx:148-156` (билинг MFG) не содержит пункта `payments`, у BUYER (`:113`) и SELLER (`:198`) — есть.

---

## 2. Дефекты кнопок / форм / меню (20 находок)

> Классификация: **CRIT** — ломает сценарий роли; **HIGH** — нарушает IRON RULE 5 (i18n) или UX; **MED** — косметика/дизайн-токены; **LOW** — улучшение.

### 🔴 CRIT-1 — BUYER не видит «Supplier Bids»
- **Где:** `frontend/src/layouts/AppShell.tsx:100-124` (`getBuyerNavigation`)
- **Как проявляется:** Buyer создаёт RFQ → Manager открывает его в `RFQ_OPEN` → supplier'ы шлют `SupplierBid` → Buyer должен увидеть список ставок и принять одну из них. Вместо этого в сайдбаре нет пункта `supplier-bids`, и buyer попадает на страницу только по прямому URL-хэшу.
- **Фикс:** добавить пункт в `getBuyerNavigation`, на backend уже есть permission — bids по deal'ам, где `deal.client == user`.

### 🔴 CRIT-2 — SELLER «Leads» → редирект на Dashboard
- **Где:**
  - `frontend/src/App.tsx:217-222` — `ADMIN_PAGES` содержит `'leads'`
  - `frontend/src/layouts/AppShell.tsx:189` — SELLER CRM-меню показывает пункт
  - `frontend/src/App.tsx:248-251` и `:299-302` — role-guard
- **Как проявляется:** SELLER нажимает «Leads» → `handleNavigate('leads')` → guard срабатывает (`ADMIN_PAGES.has('leads') && role !== 'ADMIN'`) → `navigateTo({ type: 'dashboard' })`. Тоста нет, пользователь не понимает, почему его «швырнуло».
- **Фикс:** выделить `SELLER_PAGES` отдельно или перенести `leads` в общий пул, а guard делать по менеджерской способности.

### 🔴 CRIT-3 — MFG без Excel Import
- **Где:** `frontend/src/layouts/AppShell.tsx:138-143`
- **Фикс:** добавить дочерний пункт `sourcing-import` в Sourcing-блок MFG.

### 🔴 CRIT-4 — MFG без CRM → Clients / Leads / My Requests
- **Где:** `frontend/src/layouts/AppShell.tsx:126-162`
- **Следствие:** MFG с ролью MANAGER не может вести клиентскую базу, несмотря на то, что backend-пермишены `IsManagerOrAdmin` это позволяют.

### 🔴 CRIT-5 — MFG без Payments в Billing
- **Где:** `frontend/src/layouts/AppShell.tsx:148-156`
- **Следствие:** MFG-менеджер может создавать инвойс, но пункт «платежи» не доступен — хотя `PaymentsPage.tsx` существует и читает `/crm/payments/`.

### 🔴 CRIT-6 — QuotesPage «Создать КП» — без onClick
- **Где:** `frontend/src/pages/QuotesPage.tsx:116`
  ```tsx
  actions={isBuyer ? undefined : [{ label: t('pages.quotes.createQuote') }]}
  ```
- **Проблема:** `PageShell` в `shared/PageShell.tsx:30` рендерит `<Button onClick={a.onClick}>` — где `a.onClick` undefined. Кнопка видна, нажимается, **ничего не делает**.
- **Фикс:** диалог `CreateQuoteDialog` + мутация `useCreateQuote`.

### 🔴 CRIT-7 — MyRequestsPage «Новая заявка» → Dashboard
- **Где:** `frontend/src/pages/MyRequestsPage.tsx:33`
  ```tsx
  onClick: () => onNavigate?.('catalog')
  ```
- **Проблема:** в `App.tsx:285-296` `validTypes` не содержит `'catalog'` (есть только `'products'`). `handleNavigate` (`:297-306`) падает в `else` → `navigateTo({ type: 'dashboard' })`.
- **Фикс:** заменить `'catalog'` → `'products'` (либо завести выделенный CreateRequestDialog).

### 🔴 CRIT-8 — SourcingRequestsPage «Создать запрос» — тот же баг
- **Где:** `frontend/src/pages/SourcingRequestsPage.tsx:40`
- Идентичная ошибка target `'catalog'`.

---

### 🟠 HIGH-9 — RequestDetailPage: ≥10 хардкод-English строк
- **Где:** `frontend/src/pages/flow/RequestDetailPage.tsx`
  - `:73` «Start Calculation»
  - `:77` «Send Quote»
  - `:83` «Approve»
  - `:86` «Reject»
  - `:90` «Deal Accepted»
  - `:93` «No actions available»
  - `:107` «Quote v{quote.version}»
  - `:111` «Total Incl VAT»
  - `:123` «Base Price»
  - `:125` «Final Price»
- **Нарушает IRON RULE 5** (CLAUDE.md): «ALL user-facing text wrapped in t()».
- **Фикс:** вынести все строки в `ru.json`/`en.json`.

### 🟠 HIGH-10 — RequestDetailPage: `rejectQuote` с хардкод-причиной
- **Где:** `frontend/src/pages/flow/RequestDetailPage.tsx:85`
  ```tsx
  onClick={() => rejectQuote(quote.id, "Rejected by user")}
  ```
- **Проблема:** все отклонения записываются с одинаковым английским текстом. Backend ждёт `reason` (`crm/services.py:271`) — смысл теряется.
- **Фикс:** `RejectQuoteDialog` с `Textarea` для причины, аналог есть в `ContractsPage` → `cancelReason`.

### 🟠 HIGH-11 — `BuyerAnalytics` — пустая страница
- **Где:** `frontend/src/pages/AnalyticsPage.tsx:12-28`
  ```tsx
  <PageShell ...>
  </PageShell>    // ← закрывающий тег без детей
  ```
- **Проблема:** BUYER открывает «Analytics» (видно, если `role ∈ {ADMIN, MANAGER}`), видит 2 stat-карточки и пустоту — ни графика, ни таблицы.
- **Фикс:** либо убрать пункт из `getBuyerNavigation`, либо подключить реальные чарты.

### 🟠 HIGH-12 — Dashboard: два DropdownMenuItem без onClick
- **Где:** `frontend/src/pages/Dashboard.tsx:64-65`
  ```tsx
  <DropdownMenuItem>{t('dashboardPage.export')}</DropdownMenuItem>
  <DropdownMenuItem>{t('dashboardPage.showAll')}</DropdownMenuItem>
  ```
- **Следствие:** клик по «Export» или «Показать все» — ничего не делает, ни toast, ни navigate.
- **Фикс:** либо удалить, либо привязать `onClick` (например, `onClick: handleExport(topProducts)` / `onNavigate('products')`).

### 🟠 HIGH-13 — `QuoteBuilderGrid`: нативный `confirm()`
- **Где:** `frontend/src/components/Admin/QuoteBuilderGrid.tsx:111`
  ```tsx
  if (!confirm(t('quote.deleteItem'))) return;
  ```
- **Нарушает IRON RULE 4** (только shadcn/ui). Ломает e2e-тесты, показывает браузерный диалог в вид «Chrome/native».
- **Фикс:** заменить на `AlertDialog` + controlled state.

### 🟠 HIGH-14 — `CompanyProfile`: `confirm()` для удаления компании
- **Где:** `frontend/src/components/Cabinet/CompanyProfile.tsx:56`
- Аналогично HIGH-13.

### 🟠 HIGH-15 — Dashboard: прямая манипуляция location.hash
- **Где:** `frontend/src/pages/Dashboard.tsx:233`
  ```tsx
  onClick={() => window.location.hash = '#profile'}
  ```
- **Проблема:** не проходит через `navigateTo` (`App.tsx:239-244`) → `useState` не обновится одноразово; history пишет двойной pushState.
- **Фикс:** пробросить `onNavigate` в Dashboard и использовать его.

### 🟠 HIGH-16 — `t('common.actions') || 'Actions'` — OR-фолбэк
- **Где:** `frontend/src/pages/flow/RequestDetailPage.tsx:63`
- Сигнализирует о missing i18n-key. Эту конструкцию следует удалить, добавив ключ в локали.

---

### 🟡 MED-17 — OnboardingTour получает `onNavigate`, но не использует
- **Где:** `frontend/src/components/Shared/OnboardingTour.tsx:26`
  ```tsx
  export function OnboardingTour({ open, onClose, onNavigate: _onNavigate }: OnboardingTourProps) {
  ```
- Префикс `_` = prop намеренно проигнорирован. `App.tsx:475` передаёт `handleNavigate`, но тур не умеет вести пользователя к конкретной странице → теряется весь смысл онбординга.
- **Фикс:** в каждом step добавить `targetPage?: string` + `Button "Перейти"`.

### 🟡 MED-18 — `validTypes` в App.tsx включает всё, но 2 страницы недоступны из меню
- **Где:** `frontend/src/App.tsx:285-296`
- `'leads'` и `'supplier-bids'` валидируются как маршруты, но у части ролей пункта меню нет. Пользователь с прямым URL #supplier-bids попадёт на страницу BUYER'ом — backend позволит, а UX неконсистентен.
- **Фикс:** либо привязать меню к каждой роли (см. CRIT-1), либо проверять доступность через role-guard для non-admin pages.

### 🟡 MED-19 — EmptyState без CTA
- **Где:** `MyRequestsPage`, `ClientsPage`, `LeadsPage`, `AdminKYCPage`, `PaymentsPage` и ещё ~5 страниц
- **Проблема:** при пустой выдаче показывается только иконка + «Нет данных». Нет кнопки «Создать первую…». Пользователь упирается.
- **Фикс:** `EmptyState` должен принимать `action?: {label, onClick}` (в PageShell уже есть `actions`, но на уровне заголовка — нужен inline-CTA внутри пустой карточки).

### 🟡 LOW-20 — KYC-гард молча редиректит
- **Где:** `frontend/src/App.tsx:254-259`
- Если `kycStatus !== 'verified'`, клик по любому не-allowed пункту молча уходит на dashboard. Нет объяснения, кроме `KYCPendingBanner` на самом dashboard. Пользователь пробует второй, третий раз.
- **Фикс:** добавить `toast.info(t('kyc.requiredToast'))` перед редиректом.

---

## 3. Сценарии «end-to-end» — что реально работает для каждой роли

### 3.1 BUYER (заказчик)

| Шаг | Возможно ли? | Как / где ломается |
|---|---|---|
| Dashboard → видеть свои сделки | ✓ | `Dashboard.tsx` топ-продукты, KYC баннер, стат-карточки |
| Каталог → найти продукт | ✓ | `ProductManagement.tsx`, `ProductDetail.tsx` |
| Создать заявку (RFQ) | ⚠ | «Новая заявка» редиректит на dashboard (CRIT-7) |
| Загрузить Excel-спецификацию | ✓ | `SourcingImportPage` — но пункта меню нет у BUYER. Доступ через `/sourcing-import` URL-хэшем работает, только если role ADMIN/MANAGER. Для обычного BUYER-клиента — тупик: ни в меню, ни по факту |
| Увидеть ставки поставщиков | **🔴 НЕТ** | `supplier-bids` нет в меню BUYER (CRIT-1) |
| Принять/отклонить КП | ✓ | `QuotesPage` → DropdownMenu Approve/Reject (wired) |
| Посмотреть контракт / подписать | ✓ | `ContractsPage` → `signClient`, `uploadSigned` |
| Увидеть инвойс и записать платёж | ✓ | `InvoicesPage` — `record-payment` диалог |
| Принять акт | ✓ | `ActsPage` — `signAct` |
| Закрыть сделку (CLOSED_WON) | ⚠ | кнопки в React нет; делается менеджером |

### 3.2 SELLER (поставщик)

| Шаг | Возможно ли? | Как / где ломается |
|---|---|---|
| Создать Product / Category / EquipmentGroup | ✓ | `ProductManagement`, `CategoriesPage`, `EquipmentGroupsPage` |
| Загрузить прайс (Excel) | ✓ | `SourcingImportPage` |
| Увидеть открытые RFQ | ✓ | `SourcingRequestsPage` (но кнопка «Создать» сломана, CRIT-8) |
| Подать Supplier Bid | ✓ | `SupplierBidsPage` + `SupplierBidSubmitDialog` |
| Работать с Leads | **🔴 TRAP** | кнопка есть, guard редиректит (CRIT-2) |
| Smart Match | ✓ | `SourcingHub` |
| CRM сделки, КП | ✓ | `DealsPage`, `QuotesPage` (кроме «Создать КП» — CRIT-6) |
| Billing full cycle | ✓ | все 5 страниц есть |

### 3.3 MANUFACTURER

| Шаг | Возможно ли? | Как / где ломается |
|---|---|---|
| Нoменклатура | ✓ | 3 подменю |
| Загрузить Excel | **🔴 НЕТ** | Пункта нет (CRIT-3) |
| RFQ / Smart Match | ✓ | — |
| Supplier Bids | ✓ | — |
| CRM: Clients / Leads / My Requests | **🔴 НЕТ** | Пункты отсутствуют (CRIT-4) |
| Billing: Payments | **🔴 НЕТ** | Пункт отсутствует (CRIT-5) |

### 3.4 ADMIN (React SPA)

| Шаг | Возможно ли? | Замечания |
|---|---|---|
| Users: CRUD + change role + toggle-active + delete | ✓ | `AdminUsersPage` — всё замьючено |
| Companies: CRUD + invite | ✓ | `AdminCompaniesPage` |
| KYC: L1/L2/L3 verify + upload docs | ✓ | `AdminKYCPage` — полный workflow |
| Subscriptions: CRUD + activate/suspend/delete | ✓ | `AdminSubscriptionsPage` |
| Role Applications: approve/reject | ✓ | `AdminRoleApplicationsPage` |
| Admin Deals: force stage + delete | ✓ | `AdminDealsPage` |
| Master Data: CRUD lookups | ✓ | `AdminMasterDataPage` (использует `as unknown as` — осторожно) |
| Catalog / Categories / Groups / Offers | ✓ | 4 отдельные страницы |

Вывод: **ADMIN контур чист**. Все мутации вызывают реальные endpoint'ы.

---

## 4. Поиски по шаблонам IRON RULES

| Шаблон | Найдено | Файлов | Серьёзность |
|---|---|---|---|
| `window.confirm`, `window.alert` | 2 | `QuoteBuilderGrid.tsx`, `CompanyProfile.tsx` | MED |
| Хардкод English строк (без `t()`) | ≥ 10 | `RequestDetailPage.tsx` | HIGH |
| `onNavigate?.('catalog')` (неверный target) | 2 | `MyRequestsPage.tsx`, `SourcingRequestsPage.tsx` | CRIT |
| `DropdownMenuItem` без `onClick` | 2 | `Dashboard.tsx:64,65` | HIGH |
| `actions: [{ label: ... }]` без `onClick` | 1 | `QuotesPage.tsx:116` | CRIT |
| `as any` | 0 в prod-коде (только тесты) | test/setup.ts | ok |
| `as unknown as` | 6 | `AdminMasterDataPage`, `ProfilePage`, `CatalogTable`, `authStore` | LOW (валидные type-assert'ы) |
| `@ts-ignore` / `@ts-expect-error` | 0 | — | ok |
| Hardcoded colors (`bg-emerald`, `text-white`) | 0 | — | ok |
| Arbitrary pixel sizes (`text-[9px]`, `text-[11px]`) | 0 | — | ok |
| Custom `<aside>` вместо shadcn Sidebar | 0 | — | ok |
| `stage.name` в логике (должно быть `.code`) | 0 в активных путях | — | ok |
| `data/products.ts` legacy import | 0 использований | — | ok (файла нет) |
| `mock`, `fake`, `dummy`, `stub` в prod-коде | 0 | — | ok |
| `alert(` / `console.log` в обработчиках | 0 | — | ok |

---

## 5. Приоритеты и оценка трудозатрат

| # | Задача | Severity | Оценка |
|---|---|---|---|
| 1 | Добавить `supplier-bids` в `getBuyerNavigation` | CRIT | 10 мин |
| 2 | Вывести `leads` из `ADMIN_PAGES`; сделать `SELLER_PAGES` либо проверять `role` точечно | CRIT | 30 мин |
| 3 | Дополнить `getManufacturerNavigation`: `sourcing-import`, `crm-clients`, `leads` (если MANAGER), `payments`, `my-requests` | CRIT | 1 ч |
| 4 | `QuotesPage`: `CreateQuoteDialog` + `useCreateQuote` + `onClick` | CRIT | 2 ч |
| 5 | `MyRequestsPage` и `SourcingRequestsPage`: заменить `'catalog'` → `'products'` (или завести CreateRequestDialog) | CRIT | 15 мин |
| 6 | `Dashboard.tsx:64-65`: удалить или подключить Export/ShowAll | HIGH | 30 мин |
| 7 | `RequestDetailPage.tsx`: вынести 10+ строк в локали; добавить `RejectQuoteDialog` с причиной | HIGH | 1.5 ч |
| 8 | `BuyerAnalytics`: убрать пункт или наполнить реальными чартами | HIGH | 2 ч |
| 9 | Заменить `window.confirm` на `AlertDialog` в 2 файлах | MED | 45 мин |
| 10 | `Dashboard.tsx:233`: заменить прямой `hash=` на `onNavigate('profile')` | MED | 10 мин |
| 11 | `OnboardingTour`: использовать `onNavigate` с `targetPage` в каждом шаге | MED | 1 ч |
| 12 | KYC-гард: добавить toast перед редиректом | LOW | 15 мин |
| 13 | EmptyState с inline CTA на 5 страниц | LOW | 2 ч |

**Итого: ≈ 12-14 часов активной разработки**, после чего UI станет консистентным и не будет «немых» кнопок.

---

## 6. Конкретные патчи (заготовки)

### 6.1 Добавить Supplier Bids в меню BUYER
```ts
// frontend/src/layouts/AppShell.tsx — внутри getBuyerNavigation
items.push({
  label: t('shell.supplierBids'),
  icon: <Gavel className="h-4 w-4" />,
  id: 'supplier-bids',
  active: activePage === 'supplier-bids',
});
```

### 6.2 Убрать leads из ADMIN_PAGES
```ts
// frontend/src/App.tsx
const ADMIN_PAGES = new Set([
  'admin-users', 'admin-kyc', 'admin-subscriptions', 'admin-role-apps',
  'admin-catalog', 'admin-categories', 'admin-equipment-groups', 'admin-offers',
  'admin-companies', 'admin-deals', 'admin-master-data',
  // 'leads' ← удалить
]);
const SELLER_MANAGER_PAGES = new Set(['leads']);

// role-guard:
if (SELLER_MANAGER_PAGES.has(page.type) && !['SELLER', 'ADMIN', 'MANAGER'].includes(activeStatus + role)) { ... }
```

### 6.3 Починить «Новая заявка» / «Создать запрос»
```ts
// frontend/src/pages/MyRequestsPage.tsx:33
actions={[{ label: t('pages.myRequests.newRequest'), onClick: () => onNavigate?.('products') }]}
// frontend/src/pages/SourcingRequestsPage.tsx:40 — аналогично
```

### 6.4 QuotesPage actions
```ts
const [createOpen, setCreateOpen] = useState(false);
actions={isBuyer ? undefined : [
  { label: t('pages.quotes.createQuote'), onClick: () => setCreateOpen(true) }
]}
// + <CreateQuoteDialog open={createOpen} onOpenChange={setCreateOpen} />
```

---

## 7. Файлы

- [`ui_gap_table.drawio`](./ui_gap_table.drawio) — визуальная сводка (20 menu × 5 ролей + 20 багов по severity)
- [`AUDIT_COMPARISON.md`](./AUDIT_COMPARISON.md) — предыдущий backend-audit (для контекста)
- [`README.md`](./README.md) — изначальные SJM-диаграммы

После правок CRIT-1 … CRIT-8 исходные 6 диаграмм путей (buyer/seller/manufacturer/…) потеряют большинство «красных» узлов в верхней части — имеет смысл перегенерить их скриптом `outputs/build_diagrams.py`.
