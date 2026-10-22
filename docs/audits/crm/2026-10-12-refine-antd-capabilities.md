# Возможности Refine и Ant Design: что используем и что внедрить (2026-10-12)

Вопрос владельца: все ли современные возможности Refine и Ant Design используются в дизайне и функционале.

Установлено (`pnpm ls`): @refinedev/core 5.0.12, @refinedev/antd 6.0.3, @refinedev/react-router 2.0.4,
antd 5.29.3 (последняя ветки 5), @ant-design/icons 5.6.1, TanStack Query 5.104, orval 8.40.

## Итог

- **Ant Design используется широко** (≈45 компонентов), но не используются удобные возможности, которые уже есть
  в установленной версии: липкая шапка и раскрытие строк в таблицах, пресеты дат, копирование телефонов,
  `Splitter`, `Upload.Dragger`, `Tour`, `QRCode`, графики.
- **Refine используется только как оболочка** (вход, права, раскладка, заголовки, уведомления). Слой данных
  Refine не работает: все данные идут через собственные хуки поверх orval и TanStack Query
  (`src/api/*Queries.ts`, ≈580 строк). Это расходится с ADR-0002 («Refine даёт dataProvider и CRUD-страницы»).
  Нужно решение владельца (раздел «Решение по слою данных»).
- **Один самописный механизм дублирует Refine:** предупреждение о несохранённых изменениях
  (`hooks/useUnsavedChangesPrompt.ts`) — в Refine для этого есть `UnsavedChangesNotifier`.

## Что используем

| Возможность | Статус | Где |
|---|---|---|
| Refine: вход, права по `/me/permissions` | да | `app/providers/auth.ts`, `access.ts` |
| Refine: `ThemedLayout` + своё меню | да | `App.tsx`, `AppSider.tsx` (счётчики, режим Админ/Менеджер) |
| Refine: dataProvider, `useTable`, `useList`, `useModalForm` | нет | `data.ts` — заглушка; таблицы на antd `Table` |
| Фильтры в адресе страницы | вручную | `hooks/leadFilters.ts`; в Аудите — нет |
| Refine `UnsavedChangesNotifier` | нет, своя замена | `hooks/useUnsavedChangesPrompt.ts` |
| Refine liveProvider | нет | SSE обновляет кэш TanStack (`useEventStream.ts`) — верно при текущем слое данных |
| antd `App`, `ConfigProvider`, токены, `cssVar` | да | `app/theme.ts` (контраст AA) |
| antd `Descriptions`, `Segmented`, `Result`, `Skeleton`, `Empty`, `Steps`, `Timeline`, `Collapse` | да | по всем экранам |
| antd `Table`: `sticky`, `expandable`, серверная сортировка | почти нет | sticky 0, expandable 0, sorter 1 |
| antd `DatePicker` с `presets` | нет | 6 экранов с датами |
| antd `Splitter`, `Tour`, `QRCode`, `Upload.Dragger`, `Watermark`, `FloatButton` | нет | есть в 5.29 |
| `Typography` copyable | 1 место | телефоны и email не копируются |
| Графики `@ant-design/plots` | внедряется | волна 4 UX-предложения |
| `@ant-design/x` (чат-интерфейс ИИ) | нет | чат и песочница — свои компоненты |

## Что внедрить

**P1 — быстро, без новых зависимостей (один PR, ≈1 день)**

1. `UnsavedChangesNotifier` из `@refinedev/react-router` + `useWarnAboutChange` вместо своего хука.
2. Таблицы: липкая шапка (Лиды, Аудит, База знаний, Сделки), сортировка кликом по колонке в Лидах,
   плотность `small` один раз в `ConfigProvider`, а не на каждой странице.
3. `DatePicker` с пресетами «Сегодня · 7 дней · Этот месяц · Прошлый месяц» в Лидах, Сделках, Аудите.
4. Копирование телефона, email и Telegram одним кликом (`Typography.Text copyable`) в карточках лида и клиента.
5. `keepPreviousData` в списках с пагинацией — таблица не мигает пустотой при смене страницы.

**P2 — заметная польза, ½–1,5 дня каждое**

6. Графики `@ant-design/plots` на Дашборде и в Расходах (волна 4) с ленивой загрузкой.
7. `Splitter` — изменяемая ширина «переписка ↔ вкладки» в карточке лида и «список ↔ предпросмотр» во Входящих.
8. `Upload.Dragger` — загрузка документов перетаскиванием (База знаний, документы клиента).
9. orval генерирует хуки TanStack Query сам (`client: "react-query"`) вместо ≈500 строк ручных хуков —
   типы всегда совпадают с API. Только при варианте A ниже, по одному файлу, с переписанной инвалидацией SSE.

**P3 — по желанию**

10. `Tour` — обучение нового менеджера (Входящие → «Забрать» → ответ → «Почему»).
11. `QRCode` со ссылкой на бота на «Подключениях» — проверить бота с телефона.
12. Тёмная тема (`darkAlgorithm`) — только с отдельной палитрой и проверкой контраста.
13. `@ant-design/x` 1.x — пилот только в «Проверить бота» (песочнице); основной чат не трогать —
    в нём доработанная доступность.

## Чего не внедрять

- **antd 6** — вышел, но @refinedev/antd 6.0.3 требует antd 5; ждём официальной поддержки в Refine.
- **@ant-design/pro-components** — дублирует и слой данных, и Refine; ветка 3.x требует antd 6.
- **antd-style** — 4.x требует antd 6; у нас уже `cssVar`.
- **Refine `useExport`/`useImport`, auditLogProvider** — выгрузка и аудит правильно сделаны на сервере.
- **Refine `<List>/<Show>`, `ThemedSider`** — потеряем доработки доступности и счётчики, выигрыша нет.
- **Глобальный compact-режим** — на телефоне уменьшит зоны касания ниже нормы WCAG.

## Решение по слою данных (нужно решение владельца)

- **Вариант A (рекомендую):** единый слой «orval + TanStack Query», Refine — оболочка. Правим ADR-0002 под
  фактическое состояние. Дёшево, полная типизация, SSE работает как сейчас.
- **Вариант B:** полный dataProvider Refine на ≈15 ресурсов — открывает `useTable` с синхронизацией с адресом,
  `useModalForm`, liveProvider, отменяемые действия. Но записи Refine не типизированы, кэш и SSE переделываются,
  это крупная разовая миграция.

Смешивать два слоя нельзя.

## Порядок

1. Волны 2–4 UX-предложения (идут).
2. PR P1 (п. 1–5).
3. ADR по слою данных + правка ADR-0002 — после решения владельца.
4. P2 по одному PR; P3 — по желанию.
5. antd 6 — отдельной фазой после поддержки в Refine.

Источники: refine.dev/docs (use-table, realtime, notifications), ant.design/docs/react/migration-v6,
orval.dev/docs/guides/react-query; версии — `npm view` на 2026-10-12.
