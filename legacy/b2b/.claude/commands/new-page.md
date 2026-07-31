# New Page

Создай новую страницу SPA и подключи её к hash-навигации и капабилити-меню.

## Аргумент

$ARGUMENTS — имя страницы (например: `SupplierRating`).

## Главный принцип: повторяй за свежим соседом

Найди последнюю добавленную страницу и повтори ВСЕ точки её подключения:

```bash
git log --oneline --diff-filter=A -10 -- frontend/src/pages/
```

Прочитай её файл + грепни её page-id по `App.tsx` и `src/config/navigation.tsx` — это и есть актуальный список мест подключения.

## Точки подключения (сверься с соседом — список мог измениться)

1. **Файл**: `src/pages/<Name>Page.tsx` — named export, PascalCase, props `activePage`/`onNavigate` как у соседа.
2. **App.tsx**: hash-роутинг (`#<page-id>` в kebab-case) — union-тип, valid types, switch-case, breadcrumbs — точно там же, где у соседа.
3. **Навигация**: ТОЛЬКО `buildNavigation(capabilities)` в `src/config/navigation.tsx` (ADR-0005). Никаких правок меню в AppShell — там его больше нет. Реши, каким капабилити гейтится пункт (тир T0/T1/T2, can_buy/can_sell, operator) — пункты СКРЫВАЮТСЯ, не дизейблятся.
4. **Гварды**: если страница требует авторизации/капабилити — как у соседа в `evaluatePageGuard` (cold-load дип-линки должны работать: гейты откладываются до bootstrap).

## Инварианты

- Данные — через хук на реальный API (`src/hooks/`, React Query). Никаких моков (Rule 1).
- Списки — `ResponsiveDataTable` (мобильные карточки, клавиатурная доступность).
- Все тексты через `t()`, ключи в ОБОИХ `ru.json` и `en.json`.
- Только shadcn/ui + семантические токены (см. `/design-check`).
- Пустое/loading/error состояния экрана осмысленны — не белый экран.

## Проверка

```bash
cd frontend && npm run build   # НЕ lint:tsc — build строже (tsc -b)
```

Затем **обязательно** `/ux-review` по флоу страницы: прод-сборка (`docker compose up -d --build frontend`), пройти глазами вход → страница → следующий шаг, скриншоты. Страница без пройденного сценария — не done (PRODUCT RULE 4).
