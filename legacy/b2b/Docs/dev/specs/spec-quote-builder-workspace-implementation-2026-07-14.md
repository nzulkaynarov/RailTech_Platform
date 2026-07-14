# ТЗ на имплементацию: КП-конструктор — волны 0–1 (мультиагентный прогон)

**Дата:** 2026-07-14 · **База:** main `8a5ea3c` · **Родитель:** `spec-quote-builder-ux-refactor-2026-07-14.md` (§2 дефекты, §7 раскладка)
**Режим:** этапы по 1–3 параллельных Opus-агента в worktree; один PR = одно изменение; CI мёртв (GitHub billing) — ВСЕ гейты локально.

## Общие требования ко всем WP

- Читать CLAUDE.md перед работой. Ключевое: i18n-ключи в ОБА `ru.json`/`en.json`; только shadcn/ui + семантические токены (`text-foreground`, никаких `text-white`/`bg-amber-*`/`text-[10px]`); коды ошибок `{"detail": CODE}`; сравнение по `code`; бизнес-логика в services; файлы ≤500 строк для НОВОГО кода (новые компоненты выделять файлами).
- Тесты каждого PR — в СОБСТВЕННОМ новом файле (append-conflict trap).
- Гейты фронта: `npx tsc --noEmit`, `npx vitest run`, `npx eslint . --max-warnings=0`, `npm run build`. Гейты бэка: `docker compose exec -T backend pytest <targeted>` + `backend/core/tests/test_error_shape.py`.
- Если меняется API-контракт (сериализаторы/вьюсеты/пагинация) — регенерировать OpenAPI (spectacular) + `schema.d.ts` (`gen:api-types`) в том же PR.
- Git: ветка от свежего `origin/main`, после push проверить `git branch -r --contains HEAD`; НИКОГДА не пушить в ветку уже смерженного PR (осиротеет — урок #306); PR открывать `gh pr create`, в конце вернуть URL.
- Не ломать: cost-redaction (`econ === null`), живой rail экономики, 202-паттерн AI, существующие тесты.

## Этап 1 (параллельно)

### WP-A — hotfix P0-1: пагинация режет КП (backend + контракт)
1. `backend/crm/views/quotes.py` `QuoteItemViewSet` → `pagination_class = None` (по образцу QuoteStatusViewSet:984).
2. Фронт: `crmApi.getQuoteItems` сейчас читает `response.data.results` — после снятия пагинации DRF вернёт голый массив. Обновить типы/чтение (`QuoteItem[]`), проверить grep'ом ВСЕХ потребителей `crm/quote-items`.
3. Регенерация schema.json + schema.d.ts (api-contract).
4. Тест (свой файл `backend/crm/tests/test_quote_items_no_pagination.py`): 25 позиций → API отдаёт 25; фильтр `quote__deal_id` жив.
Acceptance: КП на 25+ позиций целиком виден в билдере (все строки приходят одним ответом).

### WP-B — два малых PR workflow-фиксов (frontend)
PR-B1: `QuoteApprovalQueue.tsx:47` — переход на `deal-quote/{quote.deal}` вместо `crm-deals` (изучить сигнатуру onNavigate по Dashboard/AppShell).
PR-B2: кнопка «Создать новую версию» после REJECTED: `RequestDetailPage.tsx` (~:100 `canBuildQuote`) — при `active_quote.status_code === 'REJECTED'` и seller-side показать кнопку → существующая create-quote мутация (backend `perform_create` автоинкрементит версию — ПРОВЕРИТЬ по `crm/views/quotes.py:218,229` и `services/quotes.py`, что создание при frozen REJECTED active_quote разрешено; если запрещено — поправить сервис + тест). i18n оба языка; тесты в своих файлах.

### WP-C — workspace-лейаут билдера (frontend, ядро этапа)
Реализовать §7 родительской спеки ЦЕЛИКОМ:
1. `DealQuotePage`: заголовок → один тулбар 48px (back, title+сделка truncate, пилюля статуса согласования, индикатор сохранения, Чат/Договор/Отправить справа); заметка покупателя — однострочный collapsible; страница — `100dvh` flex-колонка без второго скролла; выяснить, как AppShell оборачивает контент (`p-6`), и добавить чистый opt-out для этой страницы (full-bleed), не ломая остальные.
2. `QuoteBuilderGrid`: убрать `h-[calc(100vh-14rem)]`/`min-h-[520px]`-контракт (родитель даёт высоту, грид — `flex-1 min-h-0`); «Расходы и скидки» → вкладка `Tabs` «Позиции | Расходы и скидки (N)» в области таблицы (компонент QuoteChargesSection переиспользовать как есть); sticky-футер 40px: Позиций N · маржа (если canViewCost) · ИТОГО с НДС · кнопка Сохранить + unsaved-индикатор (Alert-баннер убрать); Alert про несохранённое заменить индикатором.
3. `QuoteApprovalChain`: компактный режим — пилюля «статус · шаг k/n» + Popover с существующим содержимым (шаги/кнопки работают из popover); actionable-кнопка текущего шага пользователя — рядом с пилюлей. Развёрнутый режим сохранить для других мест использования, если есть.
4. Фокус-режим ⛶ в тулбаре таблицы: оверлей `fixed inset-0 z-50 bg-background`, Esc — выход.
5. Новые части — отдельными файлами в `frontend/src/components/QuoteBuilder/` (начало распила 904-строчного файла): минимум `StickyTotalsBar.tsx`, `ApprovalPill.tsx` (или в CRM/), `BuilderToolbar.tsx` — по месту виднее, но не раздувать QuoteBuilderGrid.
Acceptance: на окне 1280×768 в таблице видно ≥12 строк без страничного скролла; один вертикальный скролл (внутри таблицы); итоги видны всегда; все действия на местах из §7; vitest-тест на рендер вкладок/пилюли (свой файл).

## Этап 2 (после мержа WP-C; параллельно D+E, затем F)

- **WP-D** — `useQuoteDraft` (машина черновика): dirty-tracking по строкам, merge server-рефетча только в чистые строки, navigation-guard (beforeunload + hash), числовой ввод (запятая→точка, пустое ≠ «0», onWheel blur, `inputMode="decimal"`, разряды на blur, клампы обеих границ).
- **WP-E** — backend bulk-PATCH `POST crm/quote-items/bulk-update/`: транзакция, пер-строчные ошибки `{index, field, code}`, один пересчёт каскада; сервис в `crm/services/quotes.py`, thin view; schema regen; тесты свой файл.
- **WP-F** — `usePricingMirror` (локальный пересчёт суммы/маржи/итогов на decimal.js, зеркало серверного каскада, контрактный тест на фикстурах) + перевод Save на bulk-endpoint + add-row: остаётся открытой, Enter = «добавить и продолжить», поля qty/цена в add-row, автофокус.

## Этап 3 — адверсариальное ревью (обязательный, урок #301/#307)

Отдельный агент на каждый смерженный этап: проверить, что живые поверхности реально питаются новым кодом (не только та копия, что в ТЗ), потеря ввода невозможна во всех трёх сценариях P0-3, и гейты зелёные на объединённом main.

## Вне скоупа этого прогона
Клавиатурная навигация/мультиселект/Excel-paste/typeahead (волна 2), виртуализация/TanStack/optimistic-locking строк/каскад-визуализация charges (волна 3), ранние KYC/entitlement-баннеры (отдельный PR после WP-C, чтобы не конфликтовать).
