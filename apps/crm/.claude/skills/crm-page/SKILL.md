---
name: crm-page
description: Добавить страницу CRM на Refine + Ant Design — ресурс, хуки запросов из orval-клиента, скрытие по правам, доступность (h1, title, пустые состояния, axe 0), Vitest и Playwright smoke.
---

# Страница CRM

Типы API — только сгенерированные (`frontend/src/api/generated/`), ручные дубли запрещены. Компоненты без бизнес-логики — логика в `src/domain/*.ts` (чистые функции, таблицы тестов) и хуках `src/hooks/`. Язык интерфейса — русский (`src/i18n/ru/*.ts`; uz/en для UI — открытый Q-012). Образцы: `pages/inbox/InboxPage.tsx` (менеджер), `pages/clients/ClientsPage.tsx` (таблица + модалка).

## Шаги

1. Страница и роли — по таблице `SPEC §10.1`; режим «Менеджер» скрывает админские разделы (`SPEC §10.2`).
2. Бэкенд-эндпоинт готов и в OpenAPI? Нет — сначала `api-endpoint`, затем `make openapi`.
3. Ресурс Refine — `src/app/App.tsx` (список `resources`, `meta.label` из `t.nav`), маршрут под `RouteGuard resource="…"`; карта «ресурс → право» — `src/app/providers/access.ts`; заголовок вкладки — `t.page.<resource>` (`core.ts`, иначе в title будет ключ).
4. Данные — хуки TanStack Query над orval-клиентом: `src/api/queries.ts` (рабочее место) или `adminQueries.ts` (админ); ключи — в `keys`; мутации инвалидируют связанные ключи; живые события — `hooks/useEventStream.ts keysFor`. Refine `dataProvider` (`providers/data.ts`) — только для списков Refine (useTable).
5. Права — `allowed(perms, resource, action)` из `providers/access.ts`: только скрытие/блокировка UI; 403 с бэка показывает `useApiErrorToast` (текст по `details.reason`).
6. Каркас страницы: `PageBody` → `PageHeader` (единственный h1, `back` при вложенности) → `PageState` (загрузка/ошибка/повтор) → контент; пустые списки — `EmptyState` с действием; ссылки на сущности — `LeadLink`/`EntityLink`; да/нет — `BooleanTag`; действия в строках таблицы — `RowActions` (меню «⋯»).
7. Тексты — `src/i18n/ru/<раздел>.ts`, без хардкода; коды API (стадии, причины, роли) — через `domain/labels.ts`, никаких сырых ключей на экране (тест `labels.test.ts looksLikeCode`).
8. Адаптив: телефон `Grid.useBreakpoint().sm === false` (≤ 575 px) — карточки вместо таблицы, цели касания ≥ 44 px (`.touch-target`), без горизонтальной прокрутки; планшет `md === false` — вкладки вместо колонок.
9. Доступность: цвета только токенами темы (`--ant-*`, `app/theme.ts`), иконки `aria-hidden`, кнопки-иконки с `aria-label`, статусы в `role="status"`/sr-only; проверка — скилл `ui-review` (axe 0 нарушений на 1440 и 390 px для каждой роли).
10. Тесты: Vitest для `domain/` и хуков (образцы `*.test.ts(x)` рядом с кодом); Playwright smoke в `frontend/e2e/<role>.spec.ts` (вход → страница → ключевое действие), запуск `make test-e2e-local BASE_URL=http://localhost` с `E2E_*_PASSWORD`.
11. `make check`; в PR — шаги «Проверить на dev» для каждой роли и для телефона.
