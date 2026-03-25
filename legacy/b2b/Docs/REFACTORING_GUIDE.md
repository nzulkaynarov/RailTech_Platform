# Frontend Refactoring Guide — RailTech B2B Ecosystem

## 1. Установка новых пакетов

```bash
cd frontend
npm install react-i18next i18next i18next-browser-languagedetector react-hook-form zod
```

## 2. Что было изменено

### Новые файлы

| Файл | Назначение |
|------|-----------|
| `src/i18n/index.ts` | Конфигурация i18next (RU по умолчанию, с автодетектом) |
| `src/i18n/locales/ru.json` | Полный файл переводов — русский язык |
| `src/i18n/locales/en.json` | Полный файл переводов — английский язык |
| `src/components/UI/StatusBadge.tsx` | Унифицированный бейдж статусов (stock, deal, KYC) |
| `src/components/UI/EmptyState.tsx` | Пустые состояния с иконкой, текстом и CTA |
| `src/components/UI/LoadingSkeleton.tsx` | Скелетоны загрузки (KPI, таблицы, карточки, сетка) |
| `src/components/UI/KPICard.tsx` | Переиспользуемая KPI-карточка с трендом |
| `src/components/UI/LanguageSwitcher.tsx` | Переключатель языка RU/EN |
| `src/utils/validation.ts` | Zod-схемы + zodResolver для react-hook-form |

### Обновлённые файлы

| Файл | Что изменилось |
|------|---------------|
| `src/index.css` | Нормализованные дизайн-токены, типографическая шкала, skeleton-анимация, focus-ring |
| `src/main.tsx` | Подключён `import './i18n'` |
| `src/components/Auth/LoginPage.tsx` | i18n, react-hook-form + Zod, aria-*, focus-ring, тестовые креды спрятаны за `import.meta.env.DEV` |
| `src/components/Catalog/PublicCatalog.tsx` | i18n, EmptyState, CatalogGridSkeleton, keyboard nav в поиске, нормальные тексты |
| `src/components/Catalog/subcomponents/CatalogTable.tsx` | i18n, StatusBadge, человеческие заголовки, keyboard-accessible rows |
| `src/components/Cabinet/ClientDashboard.tsx` | i18n, KPICard, StatusBadge, EmptyState, TableSkeleton, QuickActionItem |
| `src/components/Dashboard/DealSplitView.tsx` | i18n, StatusBadge, EmptyState, proper tabs с role=tab, Skeleton loading, search filter |
| `src/components/Layout/ClientShell.tsx` | i18n, LanguageSwitcher, StatusBadge для KYC, aria-* на навигации, role=dialog на мобильном drawer |

## 3. Ключевые улучшения

### P0 — Критические
- **Двуязычность (RU/EN)** — все строки вынесены в JSON, переключатель в сайдбаре
- **Убран жаргон** — `ZERO_NODES_FOUND_IN_BUFFER` → «Ничего не найдено», `SYNCHRONIZING_GRID_DATA` → skeleton-загрузка
- **Empty states** — осмысленные пустые состояния с CTA-кнопками
- **Безопасность** — тестовые креды на LoginPage только в DEV-режиме

### P1 — Важные
- **Типографика** — нормализована к стандартной шкале (text-xs/sm/base/lg/xl)
- **Дизайн-система** — StatusBadge, KPICard, EmptyState, LoadingSkeleton — единые компоненты
- **Доступность** — aria-labels, role=tab/tabpanel, role=combobox, focus-ring, keyboard navigation

### P2 — Улучшения
- **Валидация форм** — react-hook-form + Zod на LoginPage (пример для остальных)
- **Skeleton loading** — вместо `—` и `...` — shimmer-анимации

## 4. Что осталось сделать (следующие итерации)

### Компоненты, которые нужно обновить аналогично:
- `ManagerShell.tsx` — добавить i18n + LanguageSwitcher (по аналогии с ClientShell)
- `AdminShell.tsx` — аналогично
- `AdminDashboard.tsx` — заменить хардкод на t(), использовать KPICard
- `QuoteBuilderGrid.tsx` — i18n, валидация маржи, индикатор unsaved changes
- `SourcingGrid.tsx` — i18n, EmptyState, StatusBadge
- `ExcelUpload.tsx` — i18n, нормальные ошибки
- `KYCRegistrationForm.tsx` — react-hook-form + Zod
- `ContextualChat.tsx` — i18n, индикатор WebSocket-статуса
- `ProductDetailModal.tsx` — focus trap, i18n
- `DomainAdaptiveSidebar.tsx` — i18n для названий доменов

### Архитектурные задачи:
- Установить shadcn/ui для Tabs, Dialog (с focus trap), Select
- Добавить Storybook для UI-компонентов
- Настроить ESLint-правило против `text-[Npx]` — только Tailwind-классы
- Focus trap для всех модалок (через Radix Dialog или @headlessui/react)
- Responsive: карточный вид таблиц на мобильных

## 5. Как добавлять новые переводы

```typescript
// 1. Добавить ключ в ru.json и en.json
// ru.json: "myFeature": { "title": "Мой раздел" }
// en.json: "myFeature": { "title": "My Section" }

// 2. Использовать в компоненте
import { useTranslation } from 'react-i18next';

const MyComponent = () => {
  const { t } = useTranslation();
  return <h1>{t('myFeature.title')}</h1>;
};
```

## 6. Как использовать StatusBadge

```tsx
import { StatusBadge, getStockVariant, getDealStageVariant } from '../UI/StatusBadge';

// Stock status
<StatusBadge label={t('catalog.stock.IN_STOCK')} variant={getStockVariant('IN_STOCK')} />

// Deal stage
<StatusBadge label={t('dashboard.stages.NEGOTIATION')} variant={getDealStageVariant('NEGOTIATION')} />

// Custom
<StatusBadge label="Custom" variant="info" size="md" />
```
