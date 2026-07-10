# ТЗ: Редизайн Profile & Settings — единый Settings Hub

_Статус: спецификация к реализации. Дата: 2026-07-10. Основано на внешнем UX-аудите + собственной верификации кода (все факты ниже проверены по коду, не по отчёту)._

## 0. Цель

Объединить `ProfilePage` и `SettingsPage` в единый Settings Hub с одноуровневой вертикальной навигацией по секциям (вместо «табы над табами»), привести все формы к читаемому двухколоночному паттерну, устранить найденные нарушения дизайн-системы и мёртвый функционал. **Без хардкода, без кастомного CSS, без костылей** — только существующие shadcn/ui-примитивы, семантические токены и уже принятые в репо конвенции.

## 1. Верифицированное текущее состояние (факты, file:line)

### 1.1 Структура
- `frontend/src/pages/ProfilePage.tsx` (275 строк): Tabs `personal` / `security`. Security = смена пароля (Dialog) + `<TwoFactorAuth/>` + `<ActiveSessions/>`.
- `frontend/src/pages/SettingsPage.tsx` (279 строк): табы `companyAdmin` / `team` / `company` (admin) / `platform` (admin). `CompanyAdminHub` содержит **вложенные** табы: `profile`, и при `canSell` — `documentProfile`, `defaults`, `numbering`, `templates`. `PlatformSettings` — inline-компонент внутри SettingsPage (:184-279).
- Гейтинг уже корректный (после 1eb21f9): `isAdmin = role==='ADMIN'`; `canEditCompany = isOwner || 'settings.edit' || 'charge_templates.manage'`; seller-подтабы за `capabilities.can_sell`.
- Компоненты в `src/components/Cabinet/` — все 9 живые, ни одного неиспользуемого: CompanyTeamSettings (685 строк — сверхлимит 500, требует разбиения), CompanyDocumentProfileSettings (325), CompanyDefaultsSettings (295), CompanyTab (287), ChargeTemplatesSettings (222), ProfileCompletionForm (onboarding, НЕ трогать), CompanyNumberingSettings (120), TwoFactorAuth (118), ActiveSessions (111).
- Навигация: hash-страницы `#profile` и `#settings` (`navigation.tsx:145-146`, `App.tsx:604-608`). React Router НЕ используется.

### 1.2 Бэкенд — всё реально существует
2FA (`core/urls.py:192-195`), сессии (`accounts/views/users.py:157-179`), system settings (`core/views/settings.py`), company settings / document profile / charge templates (`accountsApi.ts:293-345`). Моков нет.

### 1.3 Мёртвый / неработающий функционал (ПОДТВЕРЖДЕНО)
1. **`maintenance_mode`** — переключатель в PlatformSettings (SettingsPage.tsx:256-262) сохраняется в БД, но **ни одна middleware/код в backend его не читает**. Ничего не делает. **Решено в PR 5 (вариант Б): убран из UI, поле БД `core.SystemSettings.maintenance_mode` зарезервировано.**
2. **`is_two_factor_required`** — переключатель (:263-269) сохраняется, но login-flow его **не читает** (только определение поля `core/models.py:68` + serializer/admin). Ничего не делает. **Решено в PR 5 (вариант Б): убран из UI, поле БД `core.SystemSettings.is_two_factor_required` зарезервировано.**

### 1.4 Нарушения дизайн-системы (исправить в ходе редизайна)
- `TwoFactorAuth.tsx:73` — `text-green-600` / `text-amber-500` → `text-success` / `text-warning`.
- `TwoFactorAuth.tsx:94` — `bg-white` вокруг QR → `bg-card` или явно обоснованный токен (QR требует светлого фона — допустимо `bg-background` в светлой карточке; решить при реализации, но НЕ `bg-white`).
- `ActiveSessions.tsx:86` — `text-[10px]` → `text-xs`.
- `CompanyDocumentProfileSettings.tsx:226,232` — hex `#15294d` как дефолт accent-color документа: вынести в именованную константу с комментарием (это бренд-дефолт PDF-документа, не UI-цвет — допустимо, но не «магическим» литералом в двух местах).
- `CompanyDocumentProfileSettings.tsx:317` — `bg-white` на iframe-превью A4: оставить (бумага белая), добавить комментарий-обоснование.
- Inline-русские fallback-строки вторым аргументом `t()` (ChargeTemplatesSettings.tsx:139-141, CompanyDefaultsSettings.tsx:120-149) — убрать fallback'и, ключи уже существуют в ru.json/en.json.

### 1.5 Неиспользуемые конвенции (внедрить)
- `useUrlState` существует, но табы настроек — неконтролируемые `defaultValue`: deep-link и refresh теряют секцию.
- `ResponsiveDataTable` существует, но CompanyTeamSettings использует сырой `<Table>` — нарушение конвенции репо.

## 2. Целевая архитектура

### 2.1 Единый Settings Hub
- `SettingsPage.tsx` становится единственным хабом. `ProfilePage.tsx` **удаляется**; `#profile` остаётся рабочим deep-link'ом → редирект/алиас на `#settings?section=profile` (обратная совместимость ссылок; пункт «Профиль» в нижней навигации ведёт туда же или удаляется из nav — решение: **оставить один пункт «Настройки»** в `TENANT_BOTTOM_NAV`, `#profile` маппить на секцию profile).
- Убрать вложенные табы `CompanyAdminHub` — все секции становятся плоским списком одной вертикальной навигации.

### 2.2 Секции и гейтинг (единый source of truth)
Массив секций строится ОДНОЙ функцией (аналогично `buildNavigation(capabilities)` — ADR-0005), гейтинг по capabilities/permissions, секции **скрываются**, не дизейблятся:

| Секция (key) | Контент | Видимость |
|---|---|---|
| `profile` | персональные данные + аватар + язык/тема | все |
| `security` | пароль, 2FA, сессии | все |
| `company` | CompanyTab | `canEditCompany`; для ADMIN — read-only превью (текущий admin-таб `company`) |
| `documents` | CompanyDocumentProfileSettings | `canEditCompany && can_sell` |
| `defaults` | CompanyDefaultsSettings | `canEditCompany && can_sell` |
| `numbering` | CompanyNumberingSettings | `canEditCompany && can_sell` |
| `templates` | ChargeTemplatesSettings | `canEditCompany && can_sell` |
| `team` | CompanyTeamSettings | все не-ADMIN (как сейчас) |
| `platform` | PlatformSettings (вынести в отдельный файл) | ADMIN |

Дефолтная секция: та же логика, что сейчас (`platform` → `company` → `team` → `profile`), но `profile` всегда первый в списке для tenant-пользователей.

### 2.3 Навигация внутри хаба
- **НЕ** shadcn `<Sidebar>` — он зарезервирован за двумя shells. Использовать вертикальный список кнопок на базе существующих примитивов (`Button variant="ghost"` + `data-[active]`-стили через семантические токены, либо `Tabs orientation="vertical"` из shadcn) — выбрать при реализации то, что не требует ни одной строчки кастомного CSS.
- На мобильном (`useMediaQuery` из `use-mobile`) вертикальный список сворачивается в `Select` или горизонтальный скролл-Tabs — существующим примитивом.
- Активная секция синхронизируется через `useUrlState` (`?section=`) — deep-link и refresh сохраняют место. Внутрисекционные под-состояния (например, активный диалог) в URL не пишем.

### 2.4 Паттерн формы (для всех секций)
Двухколоночный: слева заголовок+описание секции, справа форма с капом ширины. ВАЖНО — согласовать с memory-стандартом «data/tables/previews fill viewport»: **кап ширины только для reading-форм** (profile, defaults, numbering); таблицы (team, templates, sessions) и PDF-превью (documents) — на всю ширину. Реализация — только Tailwind grid-утилиты (`grid gap-6 md:grid-cols-[240px_1fr]` и т.п.), без кастомного CSS.

### 2.5 Явно ОТКЛОНЁННЫЕ предложения внешнего аудита
- ❌ Glassmorphism, градиентные фоны/кнопки, «custom focus states», декоративные CSS-transitions — прямое нарушение Rule 4 («no decorative hacks»). Внешний вид — стандартные `Card`, семантические токены, ничего сверх.
- ❌ Пресеты бренд-цветов в color-picker documents — вне скоупа (отдельная фича, если понадобится).
- ✅ Locked-состояния унаследованных полей в documents: вместо `opacity-50 pointer-events-none` — `disabled` на инпутах + иконка `Lock` (lucide) + `Tooltip` (shadcn) с i18n-текстом «данные наследуются из профиля компании».

## 3. План реализации — фазы = отдельные PR

_Git-дисциплина: один PR на фазу, новые тесты каждого PR в СВОИХ файлах, никакого `git add -A`, проверка пуша перед анонсом._

### PR 1 — Каркас хаба + маршрутизация
- Новый layout-компонент `src/components/Settings/SettingsLayout.tsx` (вертикальная навигация + область контента + мобильный фолбэк) и `src/config/settingsSections.tsx` (buildSettingsSections(capabilities) — секции из §2.2).
- `SettingsPage.tsx` переводится на layout; существующие компоненты монтируются как есть (без визуальных правок). `PlatformSettings` выносится из SettingsPage в `src/components/Settings/PlatformSettings.tsx` (файл-лимит 500 строк, Rule «max 500»).
- `useUrlState('section')`; `#profile` → секция profile (алиас в App.tsx); удалить пункт profile из `TENANT_BOTTOM_NAV`; удалить `ProfilePage.tsx` (его содержимое переезжает как секции `profile`/`security` — компоненты `src/components/Settings/ProfileSection.tsx`, `SecuritySection.tsx`).
- Тесты: vitest на `buildSettingsSections` (гейтинг всех ролей: ADMIN / owner-seller / owner-buyer / член без прав), рендер layout.
- Ацептанс: все прежние экраны доступны, ни одна секция не пуста ни для одной роли, refresh сохраняет секцию.

### PR 2 — Profile + Security редизайн
- Двухколоночный паттерн, аватар, язык/тема; Security: карточки пароля/2FA/сессий.
- Исправить нарушения: `TwoFactorAuth` токены + `bg-white`, `ActiveSessions` `text-[10px]`.
- 2FA-флоу оставить функционально идентичным (setup→verify→disable); «прогресс-бар шагов» — только если реализуем существующими примитивами без кастома, иначе не делать.
- Тесты: компонентные (renderWithProviders) на ProfileSection/SecuritySection.

### PR 3 — Company + Documents
- CompanyTab: группировка секций (реквизиты / банк / KYC-документы) стандартными `Card`/`Separator` (не изобретать collapsible, если не нужен).
- Documents: locked-state с Lock+Tooltip (§2.5); превью и форма side-by-side на desktop (`grid lg:grid-cols-2`), превью full-width; hex-дефолт в константу.
- Убрать inline-RU fallback'и из `t()`.

### PR 4 — Defaults, Numbering, Templates, Team
- Defaults/Numbering: карточный layout, инлайн-валидация уже есть — сохранить.
- Templates + Team: перевод таблиц на `ResponsiveDataTable` (конвенция репо), keyboard-accessible rows.
- **CompanyTeamSettings (685 строк) разбить** на пакет `src/components/Settings/team/` (таблица участников, форма инвайта, roles-sheet) — каждый файл ≤500 строк, логика без изменений.

### PR 5 — Мёртвый функционал (отдельное решение владельца)
Два подтверждённо неработающих переключателя PlatformSettings:
- `maintenance_mode` — вариант А: реализовать middleware на бэкенде; вариант Б: убрать переключатель из UI (поле в БД оставить). 
- `is_two_factor_required` — вариант А: enforce в login-flow (редирект в setup 2FA); вариант Б: убрать из UI.
**Не реализовывать enforcement молча** — это изменение поведения продукта; в PR-описании явно спросить владельца, по умолчанию — вариант Б (убрать из UI, задокументировать в спеке как «поле зарезервировано»). Остальные переключатели (vat_rate, margins и т.д.) читаются реальным кодом — не трогать.

## 4. Требования к качеству (каждый PR)

1. **Никакого хардкода**: цвета — только семантические токены; размеры текста — только шкала Tailwind (`text-xs` минимум); никаких `style={{}}` для статики; enum-сравнения по `code`.
2. **Только shadcn/ui** из `@/components/ui/`; никакого custom CSS/`<aside>`/самописных табов.
3. **i18n**: весь текст через `t()`, ключи в ОБОИХ `ru.json` и `en.json`; прогнать `/check-i18n`.
4. **`/design-check`** перед каждым коммитом.
5. Никаких `as any` / `@ts-ignore`; API-ошибки — существующая обработка по `detail`-кодам.
6. Rule 6: читать каждый файл перед правкой; поведение (API-вызовы, валидации, гейтинг) — без изменений, кроме PR 5.
7. По ходу каждого PR агент обязан фиксировать в описании PR любой обнаруженный мёртвый код / неработающий функционал (список §1.3 — стартовый, не исчерпывающий).

## 5. Тестирование

### 5.1 Автоматика
- vitest: новые тесты в собственных файлах (`settingsSections.test.ts`, `ProfileSection.test.tsx`, …), через `renderWithProviders`.
- `make lint`, `make test-frontend`, `docker compose build frontend` (прод-сборка), CI-гейты i18n-symmetry / frontend-lint / frontend-test / frontend-build.

### 5.2 Браузерный тест (обязательный, после каждого PR)
Стенд: локальный Docker (`docker compose up -d --build frontend`), демо-пользователи из `make seed` + суперадмин. Прогнать матрицу роль × секция:

| Роль | Проверить |
|---|---|
| Platform ADMIN | видит только profile/security/platform/company-preview; сохранение platform-настроек; НЕ видит team/seller-секции |
| OWNER компании-продавца (can_sell) | все 9 секций; сохранение каждой формы реально пишет в БД (перезагрузка страницы показывает сохранённое); PDF-превью documents обновляется |
| OWNER компании-покупателя | НЕ видит documents/defaults/numbering/templates; ни одной пустой секции |
| Член без `settings.edit` | видит profile/security/team; company-секции скрыты |

Сквозные сценарии: смена пароля → релогин; полный цикл 2FA setup→verify→disable; revoke сессий; инвайт участника; создание/удаление charge template с подтверждением; deep-link `#settings?section=numbering` с холодной загрузки; `#profile` (старый URL) открывает секцию profile; мобильная ширина (375px) — навигация секций работает; тёмная тема — ни одного «слепого» элемента (особенно QR 2FA); переключение RU/EN — нет непереведённых строк.

## 6. Вне скоупа
- Изменение API/моделей бэкенда (кроме опционального PR 5 по решению владельца).
- Пресеты цветов, «премиальные» анимации, глассморфизм.
- ProfileCompletionForm (onboarding) — не трогать.
