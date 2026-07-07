---
title: Архитектура интерфейсов (UX/UI) - RailTech B2B
project: RailTech B2B Ecosystem
type: ui-architecture
version: 5.0 (Unified Shell Architecture)
date: 2026-04-07
updated: 2026-04-07 (UI/UX audit refactor)
---

# Архитектура интерфейсов (4 Слоя)

## Слой 1: Landing Page (`railtech.uz`)
- **Тип:** Статический маркетинговый сайт.
- **Задача:** SEO-трафик, презентация компании как единого поставщика для промышленности (Оборудование, Материалы, Услуги), переход в B2B-портал.

## Слой 2: B2B Каталог (`CatalogShell`)
- **Тип:** Публичное SPA (React). Цены скрыты.
- **Shell:** `CatalogShell` — минимальный top navbar (логотип, навигация, языки, тема, корзина). Без sidebar.
- **Интерфейсы:**
  - *Фасетный поиск (Domain-Adaptive):* `DomainAdaptiveSidebar` с фильтрами динамически меняется в зависимости от выбранного Домена. Для ЖД появляются строгие фильтры по `EquipmentGroup` (Тепловозы/Электровозы/Вагоны). Для общих товаров — фильтры по категориям и атрибутам.
  - *Мультивидовость:* Переключение между «Компактной сеткой» и «Таблицей» (Data Grid). Пустые состояния каталога явно подсказывают о возможности загрузки Excel-спецификаций.
  - *Quick Order:* Быстрое добавление товаров и услуг в корзину через кнопку "В запрос".

## Слой 3: Личный кабинет клиента (`ClientShell`)
- **Тип:** Закрытое SPA (React Router, `/cabinet/*`).
- **Shell:** `ClientShell` — shadcn `<Sidebar>` с `collapsible="icon"`, `<SidebarTrigger>` для мобильных.
- **Навигация:** Home, Deals, Profile. KYC-статус в user dropdown.
- **Контент:** `p-6` padding, `h-14` header.
- **Интерфейсы:**
  - *Дашборд:* Интерактивные KPI-виджеты с role-based контентом (Buyer/Seller/Manufacturer).
  - *Deal View (Детализация):* Сплит-экран (70/30). Слева — спецификация с визуальной группировкой позиций по Доменам. Справа — контекстный чат (WebSockets) и зона PDF-документов.

## Слой 3b: Основное приложение (`AppShell`)
- **Тип:** Hash-based SPA (без React Router, `window.location.hash` навигация).
- **Shell:** `AppShell` — shadcn `<Sidebar>` с `collapsible="icon"`, `<SidebarProvider>`, `<SidebarInset>`.
- **Навигация:** Контекстно-зависимая (BUYER/SELLER/MANUFACTURER) через `getNavigation()`. Включает Collapsible подменю, Company Status Switcher, поиск.
- **Footer:** User dropdown с ролью, статусом компании, demo mode toggle.
- **Header:** `<SidebarTrigger>`, статус компании, валютный toggle (USD/UZS), корзина/чат/уведомления.
- **Контент:** `p-6` padding.

## Слой 4: Админ-панель / CRM

### AdminShell (`/admin/*`)
- **Тип:** React Router SPA.
- **Shell:** shadcn `<Sidebar>` с `collapsible="icon"`. Навигация: Home, Users, Nomenclature, Settings.
- **Контент:** `p-6` padding, `h-14` header с `<NotificationCenter>`, `<LanguageSwitcher>`, `<ThemeToggle>`.

### ManagerShell (`/crm/*`)
- **Тип:** React Router SPA.
- **Shell:** shadcn `<Sidebar>` с `collapsible="icon"`. Навигация: Dashboard, Analytics, Deals, Sourcing, KYC, Quote Pricing (admin-only).
- **Контент:** `p-6` padding, `h-14` header.

### Общие интерфейсы (Слой 4):
  - *KYC Pane:* Карточка контрагента с кнопкой проверки по базам.
  - *Quote Builder:* Сложная таблица с расчетом юнит-экономики (Закупка → Накладные → С/С → Цена). Визуальное разделение позиций ЖД-техники, общих товаров и услуг.
  - *Sourcing Hub:* Модуль для ручного маппинга импортированных из Excel позиций (`product=null`).
  - *Коммерческая Аналитика:* Дашборды с Conversion Rate, Pipeline Volume, и статусами сделок.

---

## Дизайн-система

### Компонентный стандарт
- **UI библиотека:** shadcn/ui (61 компонент) + Radix UI примитивы
- **Иконки:** lucide-react (единственный набор)
- **Тема:** Tailwind CSS v4, OKLch color space, dark mode через `.dark` class

### Унифицированные правила Shell-ов
| Аспект | Стандарт |
|--------|----------|
| Sidebar | shadcn `<Sidebar>` + `<SidebarProvider>` + `collapsible="icon"` |
| Header height | `h-14` |
| Content padding | `p-6` |
| Mobile toggle | `<SidebarTrigger>` |
| Notifications | `<NotificationCenter>` (Sheet) |
| User menu | `<DropdownMenu>` в `<SidebarFooter>` |

### Spacing стандарт (Tailwind scale)
| Уровень | Класс | px |
|---------|-------|-----|
| Page padding | `p-6` | 24 |
| Section gap | `space-y-6` / `gap-6` | 24 |
| Card grid gap | `gap-4` | 16 |
| Form fields | `space-y-4` | 16 |
| Label → field | `space-y-2` | 8 |
| Icon → text | `gap-2` | 8 |

### Типографика
| Элемент | Tailwind |
|---------|----------|
| Page title | `text-2xl font-bold tracking-tight` |
| Section title | `text-lg font-semibold` / `CardTitle` |
| Body text | `text-sm` |
| Meta/caption | `text-xs text-muted-foreground` |
| Minimum size | `text-xs` (NEVER `text-[9px]`) |