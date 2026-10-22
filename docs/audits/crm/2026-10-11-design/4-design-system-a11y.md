# RailTech CRM — Design System Audit + Accessibility Review (WCAG 2.1 AA, код)

Дата: 2026-10-11. Объект: `frontend/src` (React 18, Refine 5 / @refinedev/antd 6.0.3, antd 5.29.3). Код не менялся.
Входные данные: axe-core по 58 экранам (`a11y.json`), чтение всех `.tsx/.ts/.css` вне `src/api/`, проверка исходников antd/refine в `node_modules`, расчёт контраста скриптом (`ct/contrast.cjs`: `theme.getDesignToken()` antd + формула относительной яркости WCAG).

Пути ниже — относительно `frontend/src/`, если не указано иное.

---

## Часть 1. Design System Audit

### Summary

**Score: 62/100**

| Блок | Баллы | Комментарий |
|---|---|---|
| Токены / тема | 8 / 30 | `ConfigProvider` без `theme` — работают дефолтные токены antd, которые не проходят 4.5:1. В CSS 7 захардкоженных цветов, в TSX 9 цветов вне `domain/labels.ts`. Отступы и размеры через `px`/числа, `theme.useToken()` — 1 место. |
| Компоненты | 22 / 30 | Хороший набор: `PageHeader`, `PageState/QueryError`, `StageBadge`+семейство, `Owner`, `EntityLink`, `ChatThread`, `useConfirmDanger`, `lib/time.ts`, `domain/labels.ts`. Но нет общих компонентов для «ссылки на лида», «Да/Нет-тега», «обработчика ошибки мутации», «колонки действий». |
| Консистентность | 18 / 25 | 11 из 12 страниц внутри Shell используют `PageHeader`; `ProfilePage` обходит и `PageHeader`, и `PageState`. Ошибки вторичных запросов молча теряются в 7 местах. Обёртки страниц дают разный вертикальный ритм (16 или 32 px). |
| Именование / структура | 14 / 15 | В целом чисто. Мелкие проблемы: `StageBadge.tsx` экспортирует 5 компонентов и рендерит `Tag`, а не `Badge`; CSS-классы используются как утилиты не по назначению; `i18n/ru.ts` — 428 строк (лимит 400). |

### Token Coverage

**Где тема:** `app/App.tsx:93` — `<ConfigProvider locale={ruRU}>` без `theme`. Своих токенов **0**. `theme.useToken()` используется только в `app/Header.tsx:11` (`colorBgContainer`).

| Категория | Всего мест | Через токен / центр | Хардкод | Где хардкод |
|---|---|---|---|---|
| Цвета в CSS | 7 | 0 | **7** | `components/ChatThread.css:12` `#fafafa`, `:26` `#fff`, `:27` `rgba(0,0,0,.08)`, `:30` `#e6f4ff`, `:33` `#f6ffed`, `:36` `#fff7e6`; `pages/pages.css:7` `#f5f5f5` |
| Цвета в TSX (именованные preset-цвета antd) | 30 | 21 (`domain/labels.ts:31-44`: 4 карты) | **9** | `components/Owner.tsx:8` orange; `pages/inbox/InboxPage.tsx:59` orange; `pages/lead-detail/LeadSummary.tsx:25` blue; `pages/clients/ClientsPage.tsx:93`, `pages/users/UsersPage.tsx:90`, `pages/clients/ClientDetailPage.tsx:117` green; `components/DecisionsPanel.tsx:63` blue/red/gray (3) |
| Hex/rgb в TSX | 0 | — | 0 | — |
| Отступы в CSS | 11 объявлений | 0 | **11** | `pages/pages.css:6,14,19,30,33,36,40`; `components/ChatThread.css:4,11,17,24`. Вне шкалы 4/8: **`ChatThread.css:17` `margin: 6px 0`** |
| Отступы inline (`style={{ margin/padding }}`) | 9 | 0 | **9** | `app/Header.tsx:18` `0 16px`; `components/PageHeader.tsx:29` `margin:0`; `components/SchemaFields.tsx:28` `marginBottom:12`; `pages/settings/DryRunPanel.tsx:14` и `pages/kb/TestSearch.tsx:43` `margin:"12px 0"`; `pages/kb/TestSearch.tsx:65`, `pages/kb/KbPage.tsx:233` `margin:0`; `pages/kb/KbPage.tsx:129` `padding:0`; `pages/clients/ClientDetailPage.tsx:150` `marginTop:8` |
| `Space size={n}` | 16 | 0 (токенов `size="middle/large"` нет) | 16 | 16 ×6, 0 ×6, 4 ×3, 8 ×1. Значения на шкале, но числа, а не `"middle"/"large"` |
| Фиксированные ширины inline | 12 | 0 | **12** | `LeadsPage.tsx:31,36,46,59,92` (240/180/160/170/220); `AuditPage.tsx:31,42,51` (200/240/220); `ClientsPage.tsx:63` 260; `ClientDetailPage.tsx:153` 240; `TestSearch.tsx:24` 90; `SchemaFields.tsx:85` 200. Вне 8-шкалы: 170, 90 |
| `width: "100%"` inline | 14 | — | 14 | лечится одним классом `.stack` / `Flex vertical` |
| Ширины колонок таблиц | 13 | — | 13 | `KbPage`, `GapsPage`, `LeadsPage`, `AuditPage` (70/80/90/110/120/150) |
| Размер шрифта | 1 | 0 | **1** | `ChatThread.css:39` `font-size: 12px` (должен быть `token.fontSizeSM`) |
| Border-radius | 2 | 0 | **2** | `ChatThread.css:13` 8px, `:25` 12px (`borderRadiusLG`/свой токен) |
| Тени | 1 | 0 | 1 | `ChatThread.css:27` (`boxShadowTertiary`) |
| Заголовки | 3 места | 0 | 3 уровня вразнобой | `PageHeader.tsx:29` h4, `LoginPage.tsx:39` h3, `ChangePasswordPage.tsx:44` h4 |
| Формат дат в DatePicker | 3 | 0 | **3** | `"DD.MM.YYYY"` в `LeadsPage.tsx:84`, `ClientDocuments.tsx:214`; `"DD.MM.YYYY HH:mm"` в `LeadActionDialog.tsx:71` — нужны константы в `lib/time.ts` |

Итог: **~56 захардкоженных визуальных значений** (7 цветов в CSS + 9 в TSX + 20 отступов + 12 ширин + 1 шрифт + 2 радиуса + 1 тень + 3 формата дат + разные уровни заголовков), токенов темы 0. Плюс: hex в TSX нет, семантические цвета статусов вынесены в `domain/labels.ts`.

### Component Completeness / Consistency

| Компонент | Варианты / состояния | Где используется | Где страницы обходят / пробелы |
|---|---|---|---|
| `PageHeader` (`components/PageHeader.tsx`) | title, back, extra ✅; заголовок h4 ⚠️ | 11 страниц | **`pages/profile/ProfilePage.tsx:12`** — `Card title` вместо `PageHeader`. `LoginPage`/`ChangePasswordPage` — свои `Typography.Title` (h3/h4). `NotFound`/403 (`app/RouteGuard.tsx:25`) без заголовка страницы. Не ставит `document.title`. |
| `PageState` / `QueryError` | loading ✅ error ✅ 403 ✅ 404 ✅ retry ✅; **empty ❌** (оставлено antd) | 11 страниц | **`ProfilePage.tsx:10`** — свой `<Card loading />`, ошибки нет вообще. Ошибки вторичных запросов теряются: `ClientDocuments.tsx:44` (пустая таблица при 500), `LeadSummary.tsx:77` `LeadNotes`, `LeadDetailPage.tsx:43` (сообщения чата), `LeadDetailPage.tsx:96` + `DecisionsPanel.tsx:58` (при ошибке пишет «решений нет» — вводит в заблуждение), `AuditPage.tsx:65` (users), `GapsPage.tsx:26` (docs для модалки), `KbPage.tsx:78` (фрагменты). |
| Пустые состояния | — | — | Нет единого компонента. `InboxPage.tsx:101` — `Empty` SIMPLE + свой текст; `ChatThread.tsx:54` — `<Empty />` с дефолтным «Нет данных»; `DecisionsPanel.tsx:58` — дефолтная картинка + свой текст; таблицы и `List` в `ClientDetailPage.tsx:92,170`, `ServiceRequests.tsx:36` — дефолт antd. Три разных вида. |
| `StageBadge` / `PriorityTag` / `IngestTag` / `RequestStatusTag` / `LangTag` | цвета из `domain/labels.ts` ✅ | стабильно | Обход: «Активен Да/Нет» — `<Tag color="green">` продублирован в `ClientsPage.tsx:93` и `UsersPage.tsx:90`, а в `ClientDetailPage.tsx:84` тот же признак выводится текстом. «Пауза» `Owner.tsx:8`, «Непрочитано» `InboxPage.tsx:59`, продукты `LeadSummary.tsx:25` — свои цвета мимо `labels.ts`. Нужен `BooleanTag`/`ActiveTag` и метки в `labels.ts`. |
| `EntityLink` | ✅ | только `AuditPage.tsx:109` | Ссылка на лида `#id · имя` собирается вручную в 6 местах: `LeadsPage.tsx:107`, `InboxPage.tsx:55`, `ClientDetailPage.tsx:175`, `GapsPage.tsx:115`, `DryRunPanel.tsx:30`, `ServiceRequests.tsx:67`. Нужен `LeadLink`. |
| `Owner` | bot / paused / human ✅ | `LeadsPage`, `LeadSummary` | `InboxPage` показывает владельца неявно (разделение по колонкам) — нормально. |
| `ChatThread` | empty ⚠️ (без текста), sending ✅, read-only hint ✅; **error ❌**, **loading ❌** | `LeadDetailPage` | При загрузке сообщений показывает «Нет данных» (нет `loading`). |
| Время (`lib/time.ts`) | `formatDate/DateTime/When/fromNow`, `tashkent()` ✅ | все страницы ✅ | **`components/LeadActionDialog.tsx:48,74`** — `dayjs()` в часовом поясе браузера (отложить до / disabledDate), а не `tashkent()`. Литералы формата дат — см. таблицу токенов. |
| Ошибки мутаций | — | — | Одна и та же строка `message.error(errorText((e as ApiError).code, e.message))` скопирована **13 раз** (`LeadActions.tsx:61`, `MakeCustomer.tsx:34`, `ClientDetailPage.tsx:60`, `ClientDocuments.tsx:53`, `ServiceRequests.tsx:31`, `ClientsPage.tsx:37`, `EditClient.tsx:38`, `InboxPage.tsx:39`, `SettingsPage.tsx:34`, `GapsPage.tsx:39`, `KbPage.tsx:28`, `LeadDetailPage.tsx:50`, `UsersPage.tsx:28`), в двух местах без `message` (inbox, chat). Без обработчика ошибок: `DashboardPage.tsx:134` (refresh), `ModeSwitch.tsx:21`, `TestSearch.tsx:13`. → хук `useApiErrorToast()`. |
| Колонка действий таблицы | — | — | Пустой заголовок в 4 местах (`KbPage.tsx:175`, `GapsPage.tsx:122`, `UsersPage.tsx:93`, `ClientDocuments.tsx:145`). → общий `actionsColumn()` с заголовком `t.common.actions`. |
| Кнопка загрузки | — | — | `<Upload><a>…</a></Upload>` (`KbDialogs.tsx:68`, `ClientDocuments.tsx:201`) — `<a>` без `href` вместо `Button icon={<UploadOutlined/>}`. |
| Раскладка страницы | — | — | `KbPage.tsx:97`, `GapsPage.tsx:73`, `ClientDetailPage.tsx:72`, `LeadDetailPage.tsx:101` оборачивают в `Space size={16}` **и** `PageHeader` даёт `margin-bottom:16px` (`pages.css:36`) → между заголовком и контентом 32 px; на остальных страницах 16 px. Главные действия: `UsersPage`/`ClientsPage` — в `PageHeader.extra`, `KbPage.tsx:99` — отдельной строкой под заголовком. |
| Disabled | `LeadActions.tsx:31` — disabled + Tooltip с причиной ✅ (но a11y, см. O2) | — | `LeadActionDialog.tsx:58` OK отключён без объяснения. |

**Файлы > 400 строк:** `i18n/ru.ts` — 428 (CLAUDE.md §4: ≤ 400 → разделить по разделам). **Функции > 50 строк** (CLAUDE.md §4): `KbPage()` ~170, `GapsPage()` ~200, `ClientDocuments()` ~155, `ClientDetailPage()` ~150, `UsersPage()` ~135, `DashboardPage()` ~65, `LeadsPage.tsx` `Filters` ~58.

### Naming

| # | Проблема | Где | Рекомендация |
|---|---|---|---|
| N1 | Файл `StageBadge.tsx` экспортирует 5 компонентов-`Tag`; слово `Badge` путается с antd `Badge` | `components/StageBadge.tsx` | `components/LabelTags.tsx` (`StageTag`, `PriorityTag`, …) |
| N2 | Повторный экспорт `PriorityTag` из `EscalationReason` | `components/EscalationReason.tsx:8` | убрать, импортировать из одного места |
| N3 | Глобальные CSS-классы используются как утилиты не по смыслу: `.filters` на кнопке, `.auth-alert` на форме настроек | `pages/clients/ClientDocuments.tsx:90`, `pages/settings/SettingsPage.tsx:67` | утилиты `.mb-16` или `Flex gap` |
| N4 | `pages.css` импортируют 6 страниц, а классы из него используют 8 (`AuditPage.tsx:25`, `SettingsPage.tsx:67`, `ClientDocuments.tsx:90` не импортируют) — скрытая зависимость от порядка загрузки | `pages/pages.css` | импортировать один раз в `main.tsx` как `styles/layout.css` |
| N5 | Чистая логика лежит в `components/` | `components/leadActionRules.ts`, `components/schemaForm.ts` | `domain/` или `lib/` |
| N6 | Диалоги KB импортирует другая страница | `pages/gaps/GapsPage.tsx:11` ← `pages/kb/KbDialogs.tsx` | перенести в `components/kb/` |
| N7 | В словаре `t.page` нет `profile`; профиль берёт `t.profile.title` | `i18n/ru.ts:187` | добавить `page.profile`, `page.login`, `common.actions` |

### Priority Actions (Design System)

1. **Ввести тему** (`app/theme.ts` → `ConfigProvider theme={appTheme}` в `App.tsx:93`) с токенами из таблицы контраста ниже. Одно изменение закрывает 565 из 565 узлов `color-contrast`.
2. **Убрать хардкод из `ChatThread.css`/`pages.css`**: цвета пузырей → `token.colorFillQuaternary / colorPrimaryBg / colorSuccessBg / colorWarningBg` через CSS-переменные (`ConfigProvider theme={{ cssVar: true }}` даёт `--ant-color-*`); `font-size` → `var(--ant-font-size-sm)`; `6px` → `8px`.
3. **Новые общие компоненты:** `LeadLink`, `BooleanTag`, `actionsColumn()`, `EmptyState`, хук `useApiErrorToast()`; константы `DATE_FORMAT/DATETIME_FORMAT` в `lib/time.ts`; `LeadActionDialog` перевести на `tashkent()`.
4. **`PageState` для всех запросов:** `ProfilePage`, `ClientDocuments`, `LeadNotes`, сообщения чата, решения, фрагменты KB. В `PageState` добавить проп `empty`.
5. **Единая раскладка:** `PageHeader` без внешнего `margin` + обёртка `PageBody` (`Flex vertical gap={token.marginMD}`) на всех страницах. Главные действия — всегда в `PageHeader.extra`.
6. Разделить `i18n/ru.ts` и функции длиннее 50 строк (`KbPage`, `GapsPage`, `ClientDocuments`, `ClientDetailPage`, `UsersPage`).

---

## Часть 2. Accessibility Audit (WCAG 2.1 AA)

### Summary

Ручной обзор кода + axe по 58 экранам (11 правил, 669 узлов: color-contrast 565, aria-progressbar-name 16, page-has-heading-one 16, heading-order 25, label 24, empty-table-header 9, button-name 8, region 6, scrollable-region-focusable 4, landmark-one-main 2, aria-required-children 2). Горизонтальной прокрутки нет ни на одном экране (1.4.10 ✅).

| Серьёзность | Кол-во |
|---|---|
| Critical | 2 |
| Serious | 11 |
| Moderate | 11 |
| Minor | 8 |
| **Итого** | **32** |

Что сделано хорошо: `<html lang="ru">` (`index.html:2`); нет `onClick` на `div/tr`, нет кликабельных строк — навигация только через `<Link>`; нет `outline: none` в CSS проекта; все поля в модальных `Form` подписаны через `Form.Item label`; опасные действия подтверждаются (`useConfirmDanger`); ошибки входа — `Alert` с `role="alert"`; модалки и drawer'ы antd держат фокус внутри.

### Соответствие правил axe и кода

| Правило axe | Экраны | Источник в коде | Фикс |
|---|---|---|---|
| color-contrast (565) | 57/58 | `app/App.tsx:93` — тема по умолчанию | тема ниже |
| heading-order (25) | все desktop-страницы со списками | `components/PageHeader.tsx:29` `level={4}` после h1 логотипа (`App.tsx:72` → refine `ThemedTitle` = `Typography.Title`, т.е. h1) | P8 |
| page-has-heading-one (16) | все mobile + login | на mobile h1 логотипа спрятан в закрытом Drawer; `LoginPage.tsx:39` h3 | P8 |
| label (24) | leads ×4, audit ×3, kb ×1 | `LeadsPage.tsx:33,43,56,91`; `AuditPage.tsx:26,37,48`; `TestSearch.tsx:21` | U1 |
| empty-table-header (9) | clients/4, kb, gaps, users | `ClientDocuments.tsx:145`, `KbPage.tsx:175`, `GapsPage.tsx:122`, `UsersPage.tsx:93` | P10 |
| aria-progressbar-name (16) | dashboard | `DashboardPage.tsx:41` | R2 |
| button-name (8) | **kb** (не users) | `KbPage.tsx:166` `Switch` в таблице | R1 |
| scrollable-region-focusable (4) | leads/11 | `ChatThread.tsx:53` `.chat-list` | O1 |
| aria-required-children (2) | settings | `SettingsPage.tsx:108` `Tabs` (кнопка «ещё» `.ant-tabs-nav-operations` внутри `role="tablist"` при переполнении) | R3 |
| landmark-one-main (2), region (6) | **login desktop + mobile** | `LoginPage.tsx:37` (тот же паттерн в `ChangePasswordPage.tsx:42`) — вне `ThemedLayout`, нет `<main>` | P9 |

### Perceivable

| # | Проблема | Критерий | Серьёзность | Рекомендация | file:line |
|---|---|---|---|---|---|
| P1 | `colorPrimary #1677ff`: ссылки, link-кнопки и белый текст на primary-кнопках (4.10:1), выбранный пункт меню на `#e6f4ff` (3.66:1), вкладки и «Назад» на фоне `#f5f5f5` (3.76:1). 89 узлов | 1.4.3 | Serious | `colorPrimary/colorLink/colorInfo: #0958d9` + hover `#003eb3`, active `#002c8c` | `app/App.tsx:93`; примеры: `LeadsPage.tsx:107`, `KbPage.tsx:127`, `PageHeader.tsx:24`, `LeadDetailPage.tsx:70` |
| P2 | Вторичный текст `rgba(0,0,0,.45)` (#8c8c8c, 3.36:1; на #f5f5f5 — 3.30:1): `Typography type="secondary"`, заголовки `Statistic`, подписи `Descriptions`, `Empty`. 66 узлов | 1.4.3 | Serious | `colorTextTertiary` и `colorTextDescription`: `rgba(0,0,0,.6)` | `App.tsx:93`; источники: `DashboardPage.tsx:83,86`, `ClientDetailPage.tsx:78` (Descriptions прямо на фоне layout #f5f5f5), `LeadSummary.tsx:37`, `ProfilePage.tsx:13`, `InboxPage.tsx:67,73`, `Owner.tsx:16`, `ChatThread.tsx:25` |
| P3 | Preset-теги: green 3.37:1 (`Да`, «Подтверждён», стадия won), cyan 3.39:1 (стадия customer), orange 3.34:1 (handoff/warm/open/«Пауза»/«Непрочитано»), status-success `#52c41a` на `#f6ffed` 2.21:1 (индексация done) | 1.4.3 | Serious | `green7 #237804`, `cyan7 #006d75`, `orange7 #ad4e00`, `colorSuccess #237804` (+ явные `colorSuccessBg/Border`), `colorWarning #874d00` | `domain/labels.ts:30-44`; `ClientsPage.tsx:93`, `UsersPage.tsx:90`, `ClientDetailPage.tsx:117`, `Owner.tsx:8`, `InboxPage.tsx:59`, `KbPage.tsx:153` |
| P4 | Danger `#ff4d4f`: 3.27:1 (текст опасных кнопок, белый на danger-primary) | 1.4.3 | Serious | `colorError #cf1322`, `colorErrorHover #a8071a` | `LeadActions.tsx:103`, `ClientDetailPage.tsx:107`, `LeadActionDialog.tsx:58`, `hooks/useConfirmDanger.ts` |
| P5 | Placeholder `rgba(0,0,0,.25)` 1.84:1, а в фильтрах placeholder — единственная подпись поля | 1.4.3 | Serious | `colorTextPlaceholder: rgba(0,0,0,.55)` (4.74:1) + видимые подписи (U1) | `LeadsPage.tsx:27,69,85`, `ClientsPage.tsx:62`, `ClientDetailPage.tsx:152`, `MakeCustomer.tsx:72`, `LeadActionDialog.tsx:81` |
| P6 | Индикатор SSE: текст всегда «Онлайн» (`t.common.live`), состояние передаёт только цвет точки (зелёная/серая). Это ещё и функциональный баг: в офлайне написано «Онлайн» | 1.4.1, 4.1.3 | Serious | `text={live ? t.common.live : t.common.offline}` + `role="status"` на обёртке | `app/Header.tsx:23` |
| P7 | Таймлайн решений: «эскалировано» видно только по красному цвету точки | 1.4.1 | Minor | добавить текст/тег «Эскалация» в `DecisionBody` | `components/DecisionsPanel.tsx:63` |
| P8 | Нет корректной иерархии заголовков: заголовок страницы — h4; единственный h1 — логотип в сайдбаре (`ThemedTitle` → `Typography.Title`), на mobile он в закрытом Drawer, поэтому h1 нет. Логин — h3, смена пароля — h4, профиль и 404 — без заголовка. Заголовки карточек (`Card title`) — не заголовки | 1.3.1, 2.4.6 | Moderate | `PageHeader`: `<Typography.Title level={1} className="page-title">` (визуально как h4: `font-size: var(--ant-font-size-heading-4)`); в `App.tsx:72` заменить `ThemedTitle` на свой `Title` без заголовочного тега (`<Link><span>`); `LoginPage`/`ChangePasswordPage` → `level={1}`; `ProfilePage` → `PageHeader`; `QueryError` → `Result title={<h1>…</h1>}`; заголовки карточек на странице — `h2` | `components/PageHeader.tsx:29`, `app/App.tsx:72`, `pages/login/LoginPage.tsx:39`, `pages/login/ChangePasswordPage.tsx:44`, `pages/profile/ProfilePage.tsx:12`, `components/PageState.tsx:26-48` |
| P9 | Страницы входа и смены пароля без landmark'ов: контент вне `<main>` | 1.3.1 (best practice: landmark-one-main/region) | Moderate | `<main className="page-center">` вместо `<div>` | `pages/login/LoginPage.tsx:37`, `pages/login/ChangePasswordPage.tsx:42` |
| P10 | Пустой `<th>` у колонки действий | 1.3.1 | Moderate | `title: <span className="sr-only">{t.common.actions}</span>` (добавить утилиту `.sr-only`) или видимый «Действия» | `KbPage.tsx:175`, `GapsPage.tsx:122`, `UsersPage.tsx:93` (нет `title`), `ClientDocuments.tsx:145` |
| P11 | Таблица воронки с `showHeader={false}` — у данных нет заголовков | 1.3.1 | Minor | вернуть заголовки «Стадия / Кол-во» (можно `sr-only`) или сделать `List`/`dl` | `DashboardPage.tsx:101` |
| P12 | Контраст не-текстовых элементов: кольцо фокуса antd `colorPrimaryBorder` #85c0ff — 1.79:1; граница полей `#d9d9d9` — 1.41:1 | 1.4.11 | Moderate | глобально `:focus-visible { outline: 2px solid var(--ant-color-primary); outline-offset: 2px }` (6.16:1); `colorBorder: #949494` (3.03:1) — по желанию, заметно меняет вид | глобального CSS нет; `app/App.tsx:93` |
| P13 | Эмодзи и символы как содержимое: «📎» читается как «скрепка», «⚠️», «↳», «→» | 1.1.1 | Minor | `<span aria-hidden>📎</span> {t.lead.attachments}:`; `↳`/`→` → `aria-hidden` + текст | `ChatThread.tsx:30`, `DecisionsPanel.tsx:26`, `ServiceRequests.tsx:71`, `DryRunPanel.tsx:31` |

### Operable

| # | Проблема | Критерий | Серьёзность | Рекомендация | file:line |
|---|---|---|---|---|---|
| O1 | Лента чата `.chat-list` (`overflow-y:auto; max-height:60vh`) не получает фокус → без мыши историю не прокрутить | 2.1.1 | Serious | `tabIndex={0} role="log" aria-label={t.lead.chat}` (role="log" также даёт `aria-live="polite"`, см. R5) | `components/ChatThread.tsx:53` |
| O2 | Причина недоступности действия — только в `Tooltip` над **disabled**-кнопкой; disabled-кнопка не фокусируется, поэтому с клавиатуры и скринридером причину не узнать | 2.1.1, 1.3.1 | Serious | вместо `disabled` использовать `aria-disabled="true"` + блокировку в `onClick` и `aria-describedby` на скрытый текст причины; либо выводить причину текстом под панелью действий | `components/LeadActions.tsx:38-44` |
| O3 | Полная дата видна только во всплывающей подсказке на нефокусируемом `Typography.Text` | 2.1.1, 1.4.13 | Moderate | `<time dateTime={iso} title=…>` + `aria-label={formatDateTime(...)}` либо `tabIndex={0}` у триггера | `pages/inbox/InboxPage.tsx:72-74` |
| O4 | `document.title` никогда не меняется: всегда «RailTech CRM» | 2.4.2 | Serious | `<DocumentTitleHandler handler={…} />` из `@refinedev/react-router` (экспорт есть в 2.0.4) внутри `<Refine>` либо `useEffect` в `PageHeader`: `` `${title} · ${t.app.title}` `` (нужен строковый `title`) | `app/App.tsx:96-176`, `index.html:6` |
| O5 | Нет ссылки «Перейти к содержимому»: перед контентом каждой страницы — 10 пунктов меню | 2.4.1 | Moderate | skip-link первым элементом `Shell` (`App.tsx:66`) → `#main`; `id="main"` на `Layout.Content` (через `ThemedLayout` нельзя — поставить `id` на обёртку `<Outlet/>`) | `app/App.tsx:66-77` |
| O6 | Видимость фокуса: кольцо antd бледное (см. P12), своего стиля `:focus-visible` нет | 2.4.7 | Moderate | глобальный `:focus-visible` (P12) | `app/` (нет глобального CSS) |
| O7 | Иконочные кнопки refine получают имя из `aria-label` иконки по-английски: сворачивание сайдбара — «left/right», бургер на mobile — «bars»; у «Назад» имя «arrow-left Назад» | 2.4.6, 4.1.2 | Minor | передать в `ThemedLayout` свой `Sider` с `aria-label` для trigger/кнопки drawer; иконкам — `aria-hidden` (`<ArrowLeftOutlined aria-hidden />`) | `app/App.tsx:69-74`, `components/PageHeader.tsx:24` |
| O8 | Нет учёта `prefers-reduced-motion` (анимации antd, сворачивание меню) | 2.3.3 (AAA, рекомендация) | Minor | `token.motion = !matchMedia('(prefers-reduced-motion: reduce)').matches` в теме | `app/App.tsx:93` |
| O9 | Переключатель периода: варианты «7 / 30 / 90» без единиц, подпись «Период» не связана с группой | 2.4.6, 3.3.2 | Minor | `options={[{value:7,label:"7 дней"},…]}` + `aria-label={t.dashboard.period}` | `pages/dashboard/DashboardPage.tsx:141-142` |

### Understandable

| # | Проблема | Критерий | Серьёзность | Рекомендация | file:line |
|---|---|---|---|---|---|
| U1 | Поля без подписи (только placeholder; у сортировки нет и его). Нашёл axe: 8 `Select`. Тот же паттерн в модалках и формах | 3.3.2, 4.1.2, 1.3.1 | **Critical** | `aria-label={t.leads.stage}` и т.п. на каждом `Select/Input/InputNumber/DatePicker`; лучше — видимые подписи (`Form layout="inline"` + `Form.Item label`) | axe: `LeadsPage.tsx:33,43,56,91`, `AuditPage.tsx:26,37,48`, `kb/TestSearch.tsx:21`. Тот же паттерн: `LeadsPage.tsx:23,66,83`, `ClientsPage.tsx:59`, `TestSearch.tsx:31`, `GapsPage.tsx:204`, `AssignLead.tsx:45`, `MakeCustomer.tsx:59,71`, `LeadActionDialog.tsx:69,78`, `ClientDetailPage.tsx:151`, `SchemaFields.tsx:36` (`Form.Item` без label в локализованных полях) |
| U2 | Сообщения клиентов на uz/en отображаются внутри `lang="ru"` → скринридер читает их русским синтезом | 3.1.2 | Moderate | передавать `language` лида в `ChatThread`, `<div className="chat-text" lang={language}>`; для client-сообщений — `lang` лида | `components/ChatThread.tsx:28` |
| U3 | Ошибки, о которых пользователь не узнаёт: тест-поиск KB, «Обновить» на дашборде, переключатель режима; ошибка решений показывается как «решений нет» | 3.3.1 | Moderate | `onError` → `useApiErrorToast`; в `TestSearch` выводить `Alert type="error"`; `DecisionsPanel` — принимать `query` и показывать `QueryError` | `kb/TestSearch.tsx:13`, `DashboardPage.tsx:134`, `ModeSwitch.tsx:21`, `DecisionsPanel.tsx:58` |
| U4 | В диалоге «Заметка» кнопка OK отключена, пока текст пуст, но причина не объясняется; поле подписано только placeholder | 3.3.2 | Minor | `Form.Item label` + `required`, вместо отключения — валидация с сообщением | `components/LeadActionDialog.tsx:58,78` |
| U5 | Пустое значение «—» (`t.common.none`) скринридер читает как «тире» | 3.3.2 / понятность | Minor | `<span aria-label="нет данных">—</span>` в общем `Empty value` компоненте | `i18n/ru.ts:181` (использование во всех таблицах) |

### Robust

| # | Проблема | Критерий | Серьёзность | Рекомендация | file:line |
|---|---|---|---|---|---|
| R1 | `Switch` (`<button role="switch">`) в таблице без имени — скринридер говорит «переключатель, включено» без указания, чего он касается | 4.1.2 | **Critical** | `aria-label={`${t.kb.active}: ${d.title}`}`; в документах клиента — `` `${t.clients.visible}: ${d.title}` `` | `pages/kb/KbPage.tsx:166`, `pages/clients/ClientDocuments.tsx:121` |
| R2 | `Progress` (`role="progressbar"`) без имени | 4.1.2 | Serious | `<Progress aria-label={reasonLabel(key)} …/>` (antd пробрасывает `aria-*`) или `aria-labelledby` на подпись | `pages/dashboard/DashboardPage.tsx:41` |
| R3 | `Tabs` настроек: при переполнении antd кладёт кнопку «ещё» внутрь `role="tablist"` → нарушено `aria-required-children` | 4.1.2 | Moderate | на desktop `tabPosition="left"` (вкладки не переполняются), на mobile — `Select`/`Segmented` для выбора раздела; иначе — известная проблема antd, держать в исключениях axe с комментарием | `pages/settings/SettingsPage.tsx:108` |
| R4 | Тосты `message.success/error` не озвучиваются: в antd 5.29 у `message` нет `role`/`aria-live` (проверено в `node_modules/antd/lib/message`). Затронуты все результаты действий («Сохранено», ошибки API) | 4.1.3 | Serious | хук `useAnnounce()` + один скрытый `<div role="status" aria-live="polite" className="sr-only">` в `Shell`; `useApiErrorToast` пишет и туда. Ошибки — через `notification` (у неё `role="alert"`) | 13 мест (см. «Ошибки мутаций»), `InboxPage.tsx:38`, `LeadActions.tsx:57` |
| R5 | Новые сообщения в чате (по SSE) не озвучиваются, только прокрутка | 4.1.3 | Moderate | `role="log"` на `.chat-list` (O1); не перерисовывать весь список — ключи уже стабильные | `components/ChatThread.tsx:53` |

### Таблица контраста: текущие и предложенные цвета

Рассчитано скриптом: `theme.getDesignToken()` antd 5.29.3 + формула WCAG 2.1. Полупрозрачные цвета смешаны с фоном.

| Токен / пара | Текущее | на #fff | на #f5f5f5 | на #e6f4ff | Предложено | на #fff | на #f5f5f5 | на #e6f4ff |
|---|---|---|---|---|---|---|---|---|
| colorPrimary / colorLink (текст) | #1677ff | 4.10 ❌ | 3.76 ❌ | 3.66 ❌ | **#0958d9** | 6.16 ✅ | 5.65 ✅ | 5.50 ✅ |
| белый на colorPrimary (кнопка) | #1677ff | 4.10 ❌ | — | — | #0958d9 | 6.16 ✅ | — | — |
| colorPrimaryHover (текст/фон кнопки) | #4096ff | 2.99 ❌ | — | — | **#003eb3** | 8.97 ✅ | — | — |
| colorLinkHover | #69b1ff | 2.25 ❌ | — | — | **#003eb3** | 8.97 ✅ | — | — |
| colorPrimaryActive / colorLinkActive | #0958d9 | 6.16 ✅ | — | — | **#002c8c** | 12.08 ✅ | — | — |
| colorTextSecondary | rgba(0,0,0,.65) | 7.00 ✅ | 6.73 ✅ | — | без изменений | 7.00 ✅ | 6.73 ✅ | — |
| colorTextTertiary / colorTextDescription | rgba(0,0,0,.45) | 3.36 ❌ | 3.30 ❌ | 3.29 ❌ | **rgba(0,0,0,.6)** | 5.74 ✅ | 5.59 ✅ | 5.52 ✅ |
| то же на #fafafa / #f6ffed / #fff7e6 (пузыри чата) | .45 | 3.31 / 3.35 / 3.31 ❌ | | | .6 | 5.67 / 5.70 / 5.62 ✅ | | |
| colorTextPlaceholder | rgba(0,0,0,.25) | 1.84 ❌ | — | — | **rgba(0,0,0,.55)** | 4.74 ✅ | — | — |
| colorError (текст, белый на danger) | #ff4d4f | 3.27 ❌ | — | — | **#cf1322** | 5.57 ✅ | — | — |
| colorErrorHover | #ff7875 | 2.56 ❌ | — | — | **#a8071a** | 7.75 ✅ | — | — |
| colorErrorText на colorErrorBg | #ff4d4f / #fff2f0 | 2.99 ❌ | | | #cf1322 / **#fff2f0** | 5.10 ✅ | | |
| colorSuccess на colorSuccessBg (тег «success») | #52c41a / #f6ffed | 2.21 ❌ | | | **#237804** / **#f6ffed** | 5.44 ✅ | | |
| colorWarning на colorWarningBg | #faad14 / #fffbe6 | 1.83 ❌ | | | **#874d00** / **#fffbe6** | 6.53 ✅ | | |
| colorInfo на colorInfoBg | #1677ff / #e6f4ff | 3.66 ❌ | | | **#0958d9** / #e6f4ff | 5.50 ✅ | | |
| Tag green (green7 на green1) | #389e0d / #f6ffed | 3.37 ❌ | | | **#237804** | 5.44 ✅ | | |
| Tag cyan (cyan7 на cyan1) | #08979c / #e6fffb | 3.39 ❌ | | | **#006d75** | 5.82 ✅ | | |
| Tag orange (orange7 на orange1) | #d46b08 / #fff7e6 | 3.34 ❌ | | | **#ad4e00** | 5.09 ✅ | | |
| Tag red / blue / geekblue / purple | #cf1322 / #0958d9 / #1d39c4 / #531dab | 5.07 / 5.50 / 7.89 / 8.88 ✅ | | | без изменений | ✅ | | |
| Кольцо фокуса (не-текст, 3:1) | #85c0ff | 1.79 ❌ | | | outline `#0958d9` | 6.16 ✅ | | |
| Граница поля (не-текст, 3:1) | #d9d9d9 | 1.41 ❌ | | | `colorBorder #949494` (опционально) | 3.03 ✅ | | |
| Disabled-текст | rgba(0,0,0,.25) | 1.82 | | | без изменений | исключение WCAG для неактивных элементов | | |

**Предлагаемая тема** (`app/theme.ts`, подключить в `App.tsx:93`: `<ConfigProvider locale={ruRU} theme={appTheme}>`):

```ts
import type { ThemeConfig } from "antd";

const reduceMotion =
  typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export const appTheme: ThemeConfig = {
  cssVar: true, // --ant-* переменные для ChatThread.css / pages.css
  token: {
    colorPrimary: "#0958d9",
    colorPrimaryHover: "#003eb3",
    colorPrimaryActive: "#002c8c",
    colorInfo: "#0958d9",
    colorLink: "#0958d9",
    colorLinkHover: "#003eb3",
    colorLinkActive: "#002c8c",
    colorTextTertiary: "rgba(0,0,0,0.6)",
    colorTextDescription: "rgba(0,0,0,0.6)",
    colorTextPlaceholder: "rgba(0,0,0,0.55)",
    colorError: "#cf1322",
    colorErrorHover: "#a8071a",
    colorErrorBg: "#fff2f0",
    colorErrorBorder: "#ffccc7",
    colorSuccess: "#237804",
    colorSuccessBg: "#f6ffed",
    colorSuccessBorder: "#b7eb8f",
    colorWarning: "#874d00",
    colorWarningBg: "#fffbe6",
    colorWarningBorder: "#ffe58f",
    green7: "#237804", // текст preset-тегов (antd: textColor = token[`${color}7`])
    cyan7: "#006d75",
    orange7: "#ad4e00",
    // colorBorder: "#949494", // 1.4.11 для границ полей — по решению дизайна
    motion: !reduceMotion,
  },
};
```

Явные `*Bg/*Border` нужны: при сид-цвете `colorSuccess #237804` antd генерирует фон `#adb8a5`, и контраст падает до 2.71:1 (проверено). Переопределение `green7/cyan7/orange7` проверено через `getDesignToken`: в результирующих токенах значения применяются, а preset-тег берёт текст из `token[`${color}7`]` (`antd/lib/theme/util/genPresetColor.js:13`).

Плюс глобальный CSS (новый `src/styles/a11y.css`, импорт в `main.tsx`):

```css
:focus-visible { outline: 2px solid var(--ant-color-primary); outline-offset: 2px; }
.sr-only { position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0 0 0 0); white-space:nowrap; border:0; }
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { scroll-behavior:auto !important; transition-duration:.01ms !important; animation-duration:.01ms !important; } }
```

### Priority Fixes (a11y)

1. **Тема из таблицы выше** (`App.tsx:93`) — закрывает все 565 узлов `color-contrast` (P1–P5) и выравнивает hover/active.
2. **Имена элементов управления** — R1 `Switch` (`KbPage.tsx:166`, `ClientDocuments.tsx:121`), U1 подписи фильтров (`LeadsPage`, `AuditPage`, `TestSearch` и модалки), R2 `Progress` (`DashboardPage.tsx:41`), P10 заголовки колонок действий (4 места).
3. **Структура страницы:** `PageHeader` → h1, логотип без заголовочного тега (`App.tsx:72`), `<main>` на логине и смене пароля, `document.title` по маршруту (`DocumentTitleHandler`), skip-link.
4. **Чат:** `.chat-list` с `tabIndex={0} role="log" aria-label` (O1 + R5), `lang` у сообщений (U2).
5. **Статусы и ошибки:** live-регион для тостов (R4), «Онлайн/Офлайн» текстом (`Header.tsx:23`, P6), причины недоступных действий без tooltip-only (`LeadActions.tsx:38-44`, O2), видимые ошибки вторичных запросов (U3).
6. **Фокус:** глобальный `:focus-visible` (O6/P12); по желанию `colorBorder` и `motion`.
7. **Регрессия:** перенести текущий axe-скан в Playwright (`@axe-core/playwright`) как CI-гейт с `impact ∈ {critical, serious}` = 0; для компонентов — `vitest-axe` в unit-тестах `ChatThread`, `LeadActions`, `PageHeader`.

**Что проверить человеку на dev** (не проверяется кодом): работа с NVDA/VoiceOver (озвучка тостов и новых сообщений чата после R4/R5), проход Tab по карточке лида и настройкам, масштаб 200% и 400% (1.4.4/1.4.10), визуальная приемлемость `colorBorder #949494`.
