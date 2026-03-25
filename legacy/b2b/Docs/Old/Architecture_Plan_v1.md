---
title: Архитектурный план — Frontend Routing, State Management & User Flow
project: RailTech B2B Ecosystem
type: architecture-plan
version: 1.0
status: На утверждение
author: Senior Fullstack Architect
date: 2026-03-16
---

# Архитектурный план: Маршрутизация, Управление состоянием и User Flow

---

## 0. Преамбула: Критические находки аудита

Перед описанием целевой архитектуры зафиксирую ключевые расхождения между текущим кодом и бизнес-требованиями, которые данный план призван устранить.

### 0.1. Что уже есть и работает

Backend полностью готов к мультиролевой модели: `CompanyMember` (промежуточная модель user↔company) поддерживает привязку одного пользователя к нескольким компаниям с разными `WorkspaceRole`. Модель `Company.types` (M2M → `CompanyType`) позволяет одной компании быть одновременно CLIENT, MANUFACTURER, SUPPLIER. Это критически важный фундамент.

### 0.2. Что отсутствует на фронтенде (Gap Analysis)

| # | Проблема | Текущее состояние | Целевое состояние |
|---|----------|-------------------|-------------------|
| G1 | **Единственная роль** | `authStore.role` хранит одну `UserRole` | Пользователь видит контекст активного workspace + может переключаться |
| G2 | **Нет контекста компании** | Фронтенд не знает о `CompanyMember`, `Company.types` | `workspaceStore` хранит список доступных workspace'ов и активный |
| G3 | **Жесткая изоляция доменов** | `b2b.*`, `cabinet.*`, `crm.*` — физически разные SPA | Единый SPA с переключением контекста через sidebar |
| G4 | **Нет workspace-переключателя** | Отсутствует UI для смены роли/компании | Dropdown в header/sidebar для переключения |
| G5 | **Interceptor не обрабатывает 403** | Только 401 → refresh → logout | 403 → редирект на "Доступ запрещен" с навигацией |

---

## 1. Инфраструктурная топология (3 узла)

```
┌─────────────────────────────────────────────────────────────────┐
│                    GITHUB PAGES (CDN)                           │
│  railtech.uz — Статический Landing (HTML/Tailwind/anime.js)    │
│  Ссылки: "Войти" → app.railtech.uz/auth/login                  │
│          "Каталог" → app.railtech.uz/catalog                    │
└───────────────────────────┬─────────────────────────────────────┘
                            │ redirect
┌───────────────────────────▼─────────────────────────────────────┐
│                       VPS-1 (Nginx)                             │
│  app.railtech.uz — React SPA (единая точка входа)              │
│  Nginx: try_files → index.html (SPA fallback)                  │
│  Все роуты обрабатываются React Router                         │
└───────────────────────────┬─────────────────────────────────────┘
                            │ API calls (HTTPS)
┌───────────────────────────▼─────────────────────────────────────┐
│                       VPS-2 (Docker)                            │
│  api.railtech.uz — Django/Daphne (ASGI)                        │
│  PostgreSQL, Redis, Celery Worker/Beat                          │
│  WebSocket: wss://api.railtech.uz/ws/                          │
└─────────────────────────────────────────────────────────────────┘
```

### Решение по доменам

**Отказ от мультидоменной маршрутизации.** Текущая схема с 4 субдоменами (b2b/cabinet/crm/admin) создает непреодолимые препятствия для переключения ролей — пользователю пришлось бы перелогиниваться при переходе между доменами (разные cookie origins). Вместо этого:

- `railtech.uz` — Landing (GitHub Pages, неизменно)
- `app.railtech.uz` — Единый React SPA для всех ролей (VPS-1)
- `api.railtech.uz` — Backend API + WebSocket (VPS-2)

Это позволяет переключать роль buyer↔seller внутри одной сессии без потери JWT и без перезагрузки.

---

## 2. Карта роутов (Routes Tree)

### 2.1. Полное дерево URL

```
app.railtech.uz
│
├── /auth
│   ├── /login                    — Форма входа (публичная)
│   ├── /register                 — Регистрация с ИНН (публичная)
│   ├── /setup-password           — Установка пароля по ссылке-инвайту
│   └── /complete-profile         — Онбординг после первой регистрации (CLIENT, L1)
│
├── /catalog                      — B2B Каталог (публичный, цены скрыты для неавторизованных)
│   └── /catalog/:productId       — Карточка товара (опционально, можно оставить модалку)
│
├── /workspace                    — Рабочая зона (требует авторизации)
│   │
│   ├── /workspace/home           — Unified Dashboard (адаптируется под activeContext)
│   │
│   │   ── BUYER CONTEXT (activeContext.type === 'BUYER') ──────────
│   ├── /workspace/deals                — Мои заявки (список сделок)
│   ├── /workspace/deals/:id            — Детализация сделки (SplitView: спецификация + чат)
│   ├── /workspace/deals/:id/import     — Excel-импорт в сделку
│   ├── /workspace/company              — Профиль компании + команда
│   ├── /workspace/company/team         — Управление сотрудниками (для OWNER)
│   ├── /workspace/documents            — Закрывающие документы, счета
│   │
│   │   ── SELLER CONTEXT (activeContext.type === 'SELLER') ────────
│   ├── /workspace/crm                  — CRM Dashboard (Воронка, Pipeline)
│   ├── /workspace/crm/deals/:id        — Quote Builder для конкретной сделки
│   ├── /workspace/crm/sourcing         — Sourcing Grid (нераспознанные товары)
│   ├── /workspace/crm/kyc             — KYC-верификация контрагентов
│   ├── /workspace/crm/analytics        — Коммерческая аналитика
│   ├── /workspace/crm/clients          — Карточки контрагентов
│   │
│   │   ── ADMIN CONTEXT (role === 'ADMIN') ────────────────────────
│   ├── /workspace/admin/users          — Управление пользователями
│   ├── /workspace/admin/nomenclature   — Управление каталогом (CRUD Products)
│   ├── /workspace/admin/companies      — Управление компаниями
│   ├── /workspace/admin/settings       — Системные настройки
│   ├── /workspace/admin/logs           — Журнал активности
│   │
│   │   ── ОБЩИЕ (доступны во всех контекстах) ────────────────────
│   ├── /workspace/profile              — Личный профиль пользователя
│   ├── /workspace/notifications        — Полный центр уведомлений
│   └── /workspace/settings             — Персональные настройки (тема, язык)
│
└── /error
    ├── /error/403                — Доступ запрещен
    └── /error/404                — Страница не найдена
```

### 2.2. Таблица соответствия Route → Роли → Shell

| URL Pattern | Доступные роли | Layout Shell | Контекст |
|-------------|----------------|--------------|----------|
| `/auth/*` | Все (публичные) | AuthShell (минималистичный) | — |
| `/catalog` | Все (публичный) | CatalogShell | — |
| `/workspace/home` | CLIENT, SALES_MANAGER, ACCOUNT_MANAGER, ADMIN | WorkspaceShell | Адаптивный |
| `/workspace/deals*` | CLIENT + workspace.OWNER/MANAGER | WorkspaceShell | BUYER |
| `/workspace/company*` | CLIENT + workspace.OWNER | WorkspaceShell | BUYER |
| `/workspace/documents` | CLIENT + workspace.OWNER/ACCOUNTANT | WorkspaceShell | BUYER |
| `/workspace/crm/*` | SALES_MANAGER, ACCOUNT_MANAGER, ADMIN | WorkspaceShell | SELLER |
| `/workspace/admin/*` | ADMIN | WorkspaceShell | ADMIN |
| `/workspace/profile` | Все авторизованные | WorkspaceShell | Общий |
| `/workspace/notifications` | Все авторизованные | WorkspaceShell | Общий |

### 2.3. Принцип: один Shell — адаптивный Sidebar

Вместо 3 отдельных Shell'ов (ClientShell, ManagerShell, AdminShell) предлагаю **единый `WorkspaceShell`** с динамическим Sidebar, который перестраивается при переключении контекста:

```
WorkspaceShell
├── Header
│   ├── Logo + Breadcrumbs
│   ├── WorkspaceSelector (dropdown переключения контекстов)
│   ├── NotificationBell (badge с unread count)
│   └── UserMenu (profile, settings, logout)
│
├── Sidebar (адаптивный)
│   ├── [BUYER context]  → Дашборд, Заявки, Компания, Документы, Каталог
│   ├── [SELLER context] → CRM, Сделки, Sourcing, KYC, Аналитика
│   └── [ADMIN context]  → Пользователи, Номенклатура, Компании, Настройки
│
└── Content Area (Outlet)
```

---

## 3. Архитектура Zustand-хранилища (State Management)

### 3.1. Карта сторов (текущие + новые)

```
stores/
├── authStore.ts          ✅ СУЩЕСТВУЕТ → модификация (убрать одиночный role)
├── workspaceStore.ts     🆕 НОВЫЙ → контекст компании и роли
├── domainStore.ts        ✅ СУЩЕСТВУЕТ → без изменений
├── cartStore.ts          ✅ СУЩЕСТВУЕТ → привязать к активному workspace
├── themeStore.ts         ✅ СУЩЕСТВУЕТ → без изменений
├── taskStore.ts          ✅ СУЩЕСТВУЕТ → без изменений
├── loadingStore.ts       ✅ СУЩЕСТВУЕТ → без изменений
└── notificationStore.ts  🆕 НОВЫЙ → замена поллинга на управляемый стор
```

### 3.2. authStore (модификация)

**Что меняется:** authStore перестает хранить `role` напрямую. Вместо этого он хранит только аутентификационное состояние. Определение «что видит пользователь» переезжает в `workspaceStore`.

```
authStore
├── user: User | null               — профиль из /api/v1/accounts/users/me/
├── accessToken: string | null       — JWT access
├── refreshToken: string | null      — JWT refresh
├── isAuthenticated: boolean         — флаг авторизации
├── isLoading: boolean               — загрузка сессии
├── systemRole: SystemRole | null    — глобальная системная роль (GUEST/CLIENT/SALES_MANAGER/...)
│
├── login(email, password) → Promise<void>
├── logout() → void
├── initAuth() → Promise<void>       — восстановление сессии + подгрузка workspace'ов
└── refreshTokens() → Promise<void>  — ручной refresh для interceptor'а
```

**Ответ API `/accounts/users/me/` должен возвращать:**
```
{
  id, email, first_name, last_name, phone,
  role: { code: "CLIENT", name: "Клиент", is_staff_level: false },
  memberships: [
    {
      id: 1,
      company: { id: 5, name: "ТрансМаш", inn: "...", types: ["CLIENT", "SUPPLIER"], verification_status: "L2_VERIFIED" },
      workspace_role: { code: "OWNER", name: "Владелец" },
      is_primary: true,
      is_active: true
    },
    {
      id: 2,
      company: { id: 12, name: "РемТехСнаб", inn: "...", types: ["CLIENT"], verification_status: "PROFILE_SUBMITTED" },
      workspace_role: { code: "MANAGER", name: "Снабженец" },
      is_primary: false,
      is_active: true
    }
  ]
}
```

### 3.3. workspaceStore (НОВЫЙ — ядро переключения)

Это ключевой новый стор, который решает задачу dual-role:

```
workspaceStore
│
├── STATE:
│   ├── memberships: Membership[]           — все активные привязки user↔company
│   ├── activeWorkspace: Membership | null  — текущий выбранный workspace
│   ├── activeContext: WorkspaceContext      — вычисляемый контекст для UI
│   └── isInitialized: boolean              — загружены ли workspace'ы
│
├── COMPUTED (getters):
│   ├── availableContexts → WorkspaceContext[]   — все доступные контексты
│   ├── canSwitchContext → boolean               — есть ли куда переключаться
│   ├── isBuyerContext → boolean                 — текущий контекст = покупатель
│   ├── isSellerContext → boolean                — текущий контекст = продавец
│   ├── isAdminContext → boolean                 — текущий контекст = администратор
│   ├── currentCompany → Company | null          — компания активного workspace
│   ├── workspaceRole → WorkspaceRole | null     — роль в текущей компании
│   └── kycStatus → VerificationStatus | null    — KYC статус текущей компании
│
├── ACTIONS:
│   ├── initWorkspaces(memberships) → void       — вызывается после login/initAuth
│   ├── switchWorkspace(membershipId) → void     — переключить workspace
│   ├── switchContext(contextType) → void         — переключить buyer/seller
│   └── reset() → void                           — очистка при logout
```

### 3.4. Типы данных (TypeScript interfaces)

```
interface Membership {
  id: number
  company: CompanyBrief
  workspace_role: LookupItem        // { code: 'OWNER', name: 'Владелец' }
  is_primary: boolean
  is_active: boolean
}

interface CompanyBrief {
  id: number
  name: string
  inn: string
  types: CompanyTypeCode[]           // ['CLIENT', 'SUPPLIER']
  verification_status: string        // 'L2_VERIFIED'
}

type CompanyTypeCode = 'CLIENT' | 'MANUFACTURER' | 'SUPPLIER' | 'LOGISTICS_PROVIDER'

type ContextType = 'BUYER' | 'SELLER' | 'ADMIN'

interface WorkspaceContext {
  type: ContextType
  membership: Membership | null       // null для ADMIN (системная роль, не привязан к компании)
  label: string                       // "ТрансМаш · Покупатель"
  icon: string                        // lucide icon name
}
```

### 3.5. Логика формирования доступных контекстов

Алгоритм `availableContexts` (вычисляемый getter):

```
1. Для каждого membership пользователя:
   a. Если company.types содержит 'CLIENT' → добавить контекст BUYER
      - label: "{company.name} · Покупатель"
      - Условие: company.verification_status in ['L2_VERIFIED', 'L3_CONTRACTED']
        (для PROFILE_SUBMITTED — контекст доступен, но с ограничениями)
   b. Если company.types содержит 'SUPPLIER' или 'MANUFACTURER' → добавить контекст SELLER
      - label: "{company.name} · Поставщик"
      - Условие: verification_status = 'L2_VERIFIED' или выше

2. Если user.systemRole.is_staff_level === true:
   - Добавить контекст SELLER автоматически (сотрудник RailTech — всегда на стороне продавца)

3. Если user.systemRole.code === 'ADMIN':
   - Добавить контекст ADMIN
      - label: "Администратор"
```

**Пример:** Пользователь — OWNER в компании "ТрансМаш" (types: ['CLIENT', 'SUPPLIER']):

```
availableContexts = [
  { type: 'BUYER',  label: 'ТрансМаш · Покупатель', membership: {...} },
  { type: 'SELLER', label: 'ТрансМаш · Поставщик',  membership: {...} },
]
```

### 3.6. Персистентность

```
workspaceStore → persist to localStorage('railtech-workspace')
  Сохраняем: activeWorkspace.id, activeContext.type
  При initAuth: восстанавливаем активный контекст из localStorage,
                если membership всё ещё валидный (есть в свежем списке)
```

### 3.7. Диаграмма потока данных

```
Login/initAuth
     │
     ▼
API: /accounts/users/me/
     │
     ├──→ authStore.setUser(user)           → systemRole, tokens, isAuthenticated
     │
     └──→ workspaceStore.initWorkspaces(user.memberships)
              │
              ├── Формирует availableContexts
              ├── Восстанавливает из localStorage или выбирает is_primary
              └── Устанавливает activeContext
                      │
                      ▼
              React Router видит activeContext.type
                      │
                      ├── BUYER  → /workspace/home (Buyer dashboard)
                      ├── SELLER → /workspace/crm  (CRM dashboard)
                      └── ADMIN  → /workspace/admin/users
```

---

## 4. Защита роутов (Protected Routes)

### 4.1. Трёхуровневая модель защиты

```
Уровень 1: АУТЕНТИФИКАЦИЯ (ProtectedRoute)
    └── Проверяет: isAuthenticated === true
        Иначе: redirect → /auth/login?redirect={current_path}

Уровень 2: КОНТЕКСТ (ContextGuard)
    └── Проверяет: activeContext.type соответствует требуемому для роута
        Иначе: автоматическое переключение контекста или redirect → /error/403

Уровень 3: РАЗРЕШЕНИЯ (PermissionGuard)
    └── Проверяет: granular permissions (workspace_role, kycStatus)
        Пример: /workspace/company/team доступен только workspace_role === 'OWNER'
        Иначе: redirect → /error/403
```

### 4.2. Компонент ProtectedRoute (переработка)

Текущий `ProtectedRoute` проверяет `allowedRoles[]`. Предлагаю заменить на более гибкую систему:

```
<ProtectedRoute> — Уровень 1
  Вход: нет параметров
  Логика:
    1. isLoading → Показать Loader (slate-950 bg, spinner)
    2. !isAuthenticated → Navigate to /auth/login?redirect=encodeURI(pathname)
    3. isAuthenticated → <Outlet />

<ContextGuard requiredContext="BUYER"> — Уровень 2
  Вход: requiredContext: ContextType | ContextType[]
  Логика:
    1. Если activeContext.type совпадает → <Outlet />
    2. Если у пользователя ЕСТЬ подходящий контекст в availableContexts:
       → Показать модалку "Переключить контекст на {label}?" с кнопками "Да / Нет"
       → "Да" → switchContext() + продолжить
       → "Нет" → redirect на /workspace/home
    3. Если подходящего контекста НЕТ → redirect → /error/403

<PermissionGuard check={(ctx) => ctx.workspaceRole === 'OWNER'}> — Уровень 3
  Вход: check: (context: WorkspaceContext) => boolean
  Логика:
    1. check(activeContext) === true → <Outlet />
    2. Иначе → redirect → /error/403

KYC-гейт (встроенный в ContextGuard для BUYER):
  Если activeContext.type === 'BUYER':
    - kycStatus === 'L1_UNVERIFIED' → redirect → /auth/complete-profile
    - kycStatus === 'PROFILE_SUBMITTED' → разрешить /workspace/home,
      показать banner "Ваш профиль на проверке"
    - kycStatus in ['L2_VERIFIED', 'L3_CONTRACTED'] → полный доступ
```

### 4.3. Применение в роутере (пример структуры)

```
<Routes>
  {/* Публичные */}
  <Route path="/auth/*" element={<AuthShell />}>...</Route>
  <Route path="/catalog" element={<CatalogShell />}>...</Route>

  {/* Защищенные — уровень 1 */}
  <Route element={<ProtectedRoute />}>
    <Route element={<WorkspaceShell />}>

      {/* Общие */}
      <Route path="/workspace/home" element={<UnifiedDashboard />} />
      <Route path="/workspace/profile" element={<UserProfile />} />

      {/* BUYER — уровень 2 */}
      <Route element={<ContextGuard requiredContext="BUYER" />}>
        <Route path="/workspace/deals" element={<DealSplitView />} />
        <Route path="/workspace/deals/:id" element={<DealSplitView />} />
        {/* OWNER only — уровень 3 */}
        <Route element={<PermissionGuard check={ctx => ctx.workspaceRole === 'OWNER'} />}>
          <Route path="/workspace/company/team" element={<CompanyTeamSettings />} />
        </Route>
      </Route>

      {/* SELLER — уровень 2 */}
      <Route element={<ContextGuard requiredContext="SELLER" />}>
        <Route path="/workspace/crm" element={<ManagerDashboard />} />
        <Route path="/workspace/crm/deals/:id" element={<QuoteBuilderGrid />} />
        <Route path="/workspace/crm/sourcing" element={<SourcingGrid />} />
      </Route>

      {/* ADMIN — уровень 2 */}
      <Route element={<ContextGuard requiredContext="ADMIN" />}>
        <Route path="/workspace/admin/*" element={<AdminRoutes />} />
      </Route>

    </Route>
  </Route>

  {/* Ошибки */}
  <Route path="/error/403" element={<AccessDenied />} />
  <Route path="*" element={<Navigate to="/error/404" />} />
</Routes>
```

### 4.4. Axios Interceptor (обработка 401 и 403)

```
ТЕКУЩИЙ INTERCEPTOR (client.ts):
  401 → refresh token → retry → на неудачу: logout + redirect /

ЦЕЛЕВОЙ INTERCEPTOR:
  401 (Unauthorized):
    1. Попытка refresh token
    2. Успех → retry оригинальный запрос
    3. Неудача → authStore.logout() + redirect /auth/login?session_expired=true
       (показать toast "Сессия истекла, войдите снова")

  403 (Forbidden):
    1. НЕ делать logout (пользователь авторизован, но нет прав)
    2. Отклонить промис (let component handle via react-query onError)
    3. Показать toast "Недостаточно прав для данного действия"
    4. Опционально: если ошибка содержит code: 'WRONG_CONTEXT'
       → предложить переключить контекст

  422 (Business Logic Violation):
    1. Показать toast с error.message из ответа
    2. Не трогать auth state

  500 (Server Error):
    1. Показать generic toast "Ошибка сервера. Попробуйте позже"
    2. Логировать в console для отладки
```

---

## 5. User Flow: пошаговый сценарий

### 5.1. Сценарий A: Новый клиент (Покупатель)

```
Шаг 1: Лендинг (railtech.uz)
  → Пользователь нажимает "Войти в B2B портал"
  → Редирект на app.railtech.uz/auth/login

Шаг 2: Регистрация
  → Нажимает "Регистрация" → /auth/register
  → Заполняет: email, пароль, ИНН, название компании
  → POST /api/v1/accounts/register/
  → Backend создает: User (role=CLIENT), Company (type=CLIENT, status=L1_UNVERIFIED),
    CompanyMember (user↔company, role=OWNER, is_primary=true)
  → Auto-login: JWT выдается сразу
  → Redirect → /auth/complete-profile

Шаг 3: Онбординг (заполнение профиля)
  → Страница /auth/complete-profile
  → Пользователь загружает Устав и заполняет реквизиты
  → POST /api/v1/accounts/kyc/ → Company.verification_status = PROFILE_SUBMITTED
  → Redirect → /workspace/home

Шаг 4: Ожидание верификации
  → Dashboard (/workspace/home) показывает:
    - Amber banner: "Ваш профиль на проверке менеджером RailTech"
    - Ограниченные возможности: просмотр каталога без цен, 1 черновик сделки
  → Менеджер RailTech через CRM верифицирует компанию → L2_VERIFIED
  → Notification (WebSocket/polling) → обновление kycStatus в workspaceStore

Шаг 5: Полный доступ покупателя
  → Dashboard обновляется: KPI-карточки, история сделок
  → Sidebar: Дашборд, Заявки, Компания, Документы, Каталог
  → Пользователь может: создавать сделки, импортировать Excel, чат с менеджером
```

### 5.2. Сценарий B: Переключение Покупатель → Поставщик

**Предусловие:** Компания "ТрансМаш" имеет types: ['CLIENT', 'SUPPLIER']. Пользователь авторизован как Покупатель.

```
Шаг 1: Текущее состояние
  → Пользователь на /workspace/deals (контекст BUYER)
  → В header видит: [🏢 ТрансМаш · Покупатель ▼]

Шаг 2: Открытие WorkspaceSelector
  → Клик на dropdown в header
  → Появляется список:
    ✓ ТрансМаш · Покупатель          (активный, галочка)
      ТрансМаш · Поставщик            (доступный)
  → При наведении на "Поставщик" — подсказка о возможностях

Шаг 3: Переключение
  → Клик на "ТрансМаш · Поставщик"
  → workspaceStore.switchContext('SELLER')
  → Backend вызов: POST /api/v1/accounts/switch-context/
    Body: { context: 'SELLER', company_id: 5 }
    → Backend может вернуть обновленные permissions/features
  → Sidebar мгновенно перестраивается:
    CRM Dashboard, Сделки, Sourcing, KYC, Аналитика
  → URL меняется: /workspace/crm (redirect на seller home)
  → Header обновляется: [🏢 ТрансМаш · Поставщик ▼]
  → Тема Sidebar: меняется accent color (buyer=blue, seller=indigo)

Шаг 4: Работа в контексте поставщика
  → Пользователь видит CRM dashboard с его входящими сделками
  → Может: обрабатывать заявки, формировать КП, работать в Sourcing Grid
  → Все API запросы отправляются с header X-Workspace-Context: SELLER

Шаг 5: Обратное переключение
  → Клик на selector → выбор "Покупатель"
  → Мгновенное переключение обратно, сессия сохранена
```

### 5.3. Сценарий C: Сотрудник RailTech (Менеджер)

```
Шаг 1: Вход
  → Переход на app.railtech.uz/auth/login
  → Авторизация с email сотрудника
  → Backend: user.role = SALES_MANAGER (is_staff_level = true)
  → memberships: [{ company: RailTech, workspace_role: MANAGER }]

Шаг 2: Определение контекстов
  → availableContexts = [
      { type: 'SELLER', label: 'RailTech · Менеджер' }
    ]
  → Только один контекст → selector показывается но не кликабелен
  → Auto-redirect → /workspace/crm

Шаг 3: Рабочий процесс
  → CRM Dashboard: воронка сделок, входящие заявки, KYC на проверку
  → Sidebar: CRM, Мои сделки, Sourcing, KYC, Аналитика
```

### 5.4. Сценарий D: Администратор с полным доступом

```
Шаг 1: Вход (role = ADMIN)
  → availableContexts = [
      { type: 'SELLER', label: 'RailTech · Менеджер' },
      { type: 'ADMIN',  label: 'Администратор' }
    ]
  → По умолчанию: ADMIN context → /workspace/admin/users

Шаг 2: Переключение Admin → Seller
  → Через selector: переключение на "RailTech · Менеджер"
  → Sidebar: CRM-инструменты (как у менеджера)
  → Может работать с конкретными сделками в режиме менеджера

Шаг 3: Обратно в Admin
  → Переключение → полная админ-панель
  → Пользователи, Номенклатура, Настройки
```

### 5.5. Сценарий E: Переход из каталога в сделку (анонимный → авторизованный)

```
Шаг 1: Анонимный просмотр
  → Пользователь заходит на app.railtech.uz/catalog
  → Видит товары без цен, фильтры по доменам
  → Нажимает "В запрос" на товаре

Шаг 2: Перехват авторизации
  → cartStore добавляет товар (работает без авторизации)
  → CartDrawer открывается с кнопкой "Оформить заявку"
  → Клик → проверка isAuthenticated → false
  → Redirect: /auth/login?redirect=/workspace/deals&action=create_from_cart

Шаг 3: После логина
  → Успешный вход → authStore + workspaceStore инициализированы
  → Redirect обратно на /workspace/deals с параметром action=create_from_cart
  → Автоматическое создание Deal из корзины
  → cartStore.clearCart()
```

---

## 6. Sidebar: навигационная структура по контекстам

### 6.1. BUYER Context

```
📊  Дашборд                /workspace/home
📋  Мои заявки             /workspace/deals
    ├── Все                (фильтр: все статусы)
    ├── В работе           (фильтр: CALCULATING)
    └── КП на утверждении  (фильтр: QUOTE_SENT)
🏢  Компания               /workspace/company
    ├── Профиль            /workspace/company
    └── Команда            /workspace/company/team      [только OWNER]
📄  Документы              /workspace/documents
🛒  Каталог                /catalog                     [открывает в новом контексте]
───────
👤  Профиль                /workspace/profile
⚙️  Настройки              /workspace/settings
```

### 6.2. SELLER Context

```
📊  CRM Dashboard          /workspace/crm
📋  Сделки                 /workspace/crm/deals
    ├── Мои                (фильтр: manager=me)
    └── Нераспределенные   (фильтр: manager=null)
🔍  Sourcing               /workspace/crm/sourcing
✅  KYC Проверка           /workspace/crm/kyc
📈  Аналитика              /workspace/crm/analytics
🏢  Клиенты                /workspace/crm/clients
───────
👤  Профиль                /workspace/profile
⚙️  Настройки              /workspace/settings
```

### 6.3. ADMIN Context

```
📊  Обзор                  /workspace/admin/home
👥  Пользователи           /workspace/admin/users
📦  Номенклатура           /workspace/admin/nomenclature
🏢  Компании               /workspace/admin/companies
⚙️  Системные настройки    /workspace/admin/settings
📜  Журнал                 /workspace/admin/logs
───────
[Все пункты из SELLER context — Admin видит CRM как read-only обзор]
───────
👤  Профиль                /workspace/profile
```

---

## 7. Миграционный план (от текущего к целевому)

Чтобы не ломать существующий функционал, предлагаю поэтапную миграцию:

### Фаза 1: Backend API (1-2 дня)
- Расширить `/accounts/users/me/` для возврата `memberships[]` с вложенными `company.types`
- Создать endpoint `POST /accounts/switch-context/` (опционально, для аудита переключений)
- Добавить middleware для чтения `X-Workspace-Context` header

### Фаза 2: Новые сторы (1 день)
- Создать `workspaceStore.ts` с полной типизацией
- Модифицировать `authStore.ts` — вынести `role` logic в workspace
- Обновить persist-конфигурацию

### Фаза 3: Unified Shell + Router (2-3 дня)
- Создать `WorkspaceShell` с адаптивным Sidebar
- Переписать Router на новую структуру `/workspace/*`
- Имплементировать `ContextGuard` и `PermissionGuard`
- Создать `WorkspaceSelector` (dropdown в header)

### Фаза 4: Миграция страниц (2-3 дня)
- Переместить существующие компоненты в новую структуру роутов
- Обновить все хуки и API-вызовы для учета activeContext
- Добавить `X-Workspace-Context` header в Axios interceptor

### Фаза 5: Тестирование и legacy cleanup (1-2 дня)
- Убрать domain-based routing из App.tsx
- Удалить ClientShell, ManagerShell, AdminShell (заменены на WorkspaceShell)
- E2E тестирование всех сценариев переключения
- Редиректы со старых URL (`/cabinet/*` → `/workspace/*`, `/crm/*` → `/workspace/crm/*`)

**Итого: 7-11 рабочих дней**

---

## 8. Открытые вопросы для обсуждения

1. **WebSocket-комната для контекста:** Нужно ли создавать отдельные WS-каналы для buyer/seller контекстов, или достаточно одного канала с фильтрацией на сервере?

2. **Каталог внутри workspace:** Каталог (`/catalog`) сейчас публичный. Нужен ли отдельный вид каталога внутри workspace с ценами для верифицированных клиентов, или достаточно показывать цены в том же публичном каталоге после авторизации?

3. **Переключение компаний:** Если пользователь состоит в 2+ компаниях (например, владелец двух юрлиц), как должен работать переключатель? Вариант A: плоский список (ТрансМаш·Покупатель, ТрансМаш·Поставщик, РемТех·Покупатель). Вариант B: сгруппированный (ТрансМаш → Покупатель/Поставщик; РемТех → Покупатель).

4. **API-контекст:** Отправлять `X-Workspace-Context` header с каждым запросом или передавать `company_id` как query-параметр?

5. **Оффлайн-переключение:** Должно ли переключение контекста работать полностью на клиенте (мгновенно) или требовать подтверждения от сервера (задержка, но безопаснее)?

---

*Документ подготовлен для утверждения. Код не будет написан до получения команды «План утвержден».*
