# ТЗ: КП-секции/optional items + консолидация настроек + код-гигиена — мультиагентный план

**Дата:** 2026-07-17 · **База:** main `d353347` · **Статус:** НА УТВЕРЖДЕНИИ владельцем
**Родители:** `spec-quote-builder-ux-refactor-2026-07-14.md` (§5 п.17/19 — последние не начатые), `session-handoff-2026-07-16-policy-wave3.md` (реестр остатка).

## 0. Скоуп и процесс

Закрывает ВЕСЬ оставшийся кодовый бэклог, не требующий внешних сервисов: (S1) секции/заметки/optional items в КП; (S2) консолидация настроек КП; (S3) распил backend-гигантов; (S4) гигиена OpenAPI-контракта + coverage-гейт; (S5) рефреш master-system-document; (S6) мелочь-хвост из ревью; (S7 — опционально, отдельное «да») два продуктовых пункта. Итого **~9 PR в 3 волны**.

Процесс прежний (отработан волнами #294–#345): 1 backend-агент в main-репо (Docker) + frontend-агенты в worktree; грид-файлы сериализуются; адверсариальное ревью объединённой волны ДО мержа (обязательно `npm run build`, `pytest --create-db`, линт с репо-root конфигом, **HTTP-маршрут-тесты** для новых эндпоинтов — урок #343); мерж по подтверждению владельца; проверка деплоя+бандла.

---

## 1. S1 — Секции, заметки и опциональные позиции КП (спека §5 п.19, Odoo-стандарт)

**Зачем:** КП на 50+ позиций нечитаемо (бенчмарк: Odoo sections+notes, Qwilr/Proposify optional items — растущий стандарт). Продавец хочет группировать («Механика», «Электрика»), комментировать и предлагать опции.

**Дизайн (мировая практика = Odoo `display_type`):** та же таблица QuoteItem, без новой модели.
- **Backend (1 PR):** `QuoteItem.display_type` (`ITEM` default / `SECTION` / `NOTE`) + `QuoteItem.is_optional` (bool, default False) + `QuoteItem.position` (Integer, ordering; backfill существующих по id) — одна миграция. SECTION/NOTE: без цен (guard — pricing-поля игнорируются/нулевые, `calculate_item_prices` пропускает); **optional-позиции НЕ входят в итоги** (subtotal/каскад/НДС — пропуск в `recalculate_quote`). Сериализатор: поля + валидация (SECTION/NOTE не принимают цены; коды ошибок). bulk-create/bulk-update принимают новые поля. Ordering по `position` во всех выдачах. **PDF** (`quote_pdf.html`): секции — жирный заголовок + подытог секции; заметки — курсив; optional — отдельный блок «Опционально (не входит в итог)» с ценами. Тесты: пересчёт исключает optional; SECTION/NOTE без цен; PDF-рендер снапшот-логика; HTTP-маршрут.
- **Frontend (1 PR, грид):** в add-row/тулбаре — «+ Секция» / «+ Заметка» (создание строки с display_type); грид рендерит секцию (жирная строка на всю ширину + живой подытог секции из pricing mirror), заметку (курсив, colspan), optional-позицию (чекбокс/бейдж «опция», исключена из итогов зеркала); **перемещение строк — кнопки ↑/↓ на строке** (меняют `position`; drag-and-drop НЕ делаем — конфликтует с виртуализацией/sticky, up/down keyboard-friendly и достаточно; мировая практика допускает); Excel-paste/duplicate/bulk не ломаются (display_type=ITEM по умолчанию); виртуализация учитывает секции/заметки (обычные строки списка).
- **Вне скоупа (волна 4, отдельное решение):** интерактивный выбор optional-позиций ПОКУПАТЕЛЕМ с пересчётом (наш публичный КП — PDF by design, интерактив = отдельная фича с переговорной семантикой).

## 2. S2 — Консолидация настроек КП (спека §5 п.17)

**Сейчас:** базис поставки (Incoterm) — в rail (`DeliveryBasisSelect` в `EconomicsRail`), маржа/НДС/валюта/сроки — в `QuoteSettingsDialog`, `valid_until` вводится в ДВУХ местах (GenerateQuoteDialog при создании + Settings).
**Дизайн (1 frontend PR):** базис поставки переезжает в `QuoteSettingsDialog` (секция «Поставка»); в rail остаётся read-only chip базиса (клик → открывает Settings); `valid_until` — ЕДИНСТВЕННОЕ место в Settings: из `GenerateQuoteDialog` поле убирается (создание КП предзаполняет +14 дней молча, как дефолт — меньше шагов на старте, стандарт «сначала создай, потом настрой»). Тесты обновить. Backend не трогается.

## 3. S3 — Распил backend-гигантов (лимит 500, зеркало распила грида #339)

Механический, БЕЗ изменения поведения; ~560 crm-тестов = регресс-сеть; публичные import-поверхности сохраняются через package `__init__` re-export (все `from crm.services.quotes import X` продолжают работать).
- **PR-1:** `crm/services/quotes.py` (~1500) → пакет `crm/services/quotes/`: `pricing.py` (calculate_item_prices, recalculate_quote, economics), `lifecycle.py` (create/send/approve/freeze, public_quote_gate), `bulk.py` (bulk_update/bulk_create), `__init__.py` (re-export ВСЕГО текущего API). 
- **PR-2:** `crm/views/quotes.py` (~1200) → пакет `crm/views/quotes/` (`public.py`, `quotes.py`, `items.py`, `charges.py`, `__init__` re-export); `crm/serializers.py` (~1030) → пакет по доменам (quote/deal/billing/misc) с re-export.
Гейты: полный backend `--create-db` зелёный, `manage.py check`, schema-регенерация = пустой дифф (распил не меняет контракт), grep по проекту на прямые импорты внутренностей.

## 4. S4 — Гигиена контракта + coverage-гейт (1 backend PR)

- **Spectacular: 68 errors / 182 warnings → 0 errors, минимум warnings.** Главное — operationId-коллизии (`crm/quote-statuses/` и др.): точечные `@extend_schema(operation_id=…)`/serializer-аннотации, НИКАКИХ изменений поведения. Регенерация schema.json + `gen:api-types` — дифф ревьюится на «только идентификаторы/аннотации, не формы данных». Фронт-билд зелёный (schema.d.ts переименования типов — поправить импорты, если сгенерённые имена изменятся).
- **Coverage-гейт `--cov-fail-under` 30 → 70** (реальные ~78%, запас 8пп; защита от деградации; активируется когда оживёт CI).

## 5. S5 — Рефреш master-system-document (1 docs PR)

MSD v6.0 (апрель) врёт: Django 5.2, ретайрнутый context-switcher, ACCOUNT_MANAGER-роли. **Дизайн:** НЕ переписывать монстра — сократить до **v7.0 «карта системы»**: актуальная выжимка (стек, топология, домены, потоки) на ~200–300 строк со ссылками на живые каноны (ADR-0001…0006, CLAUDE.md, спеки); устаревший полный текст v6.0 → `Docs/old/`. Мировая практика: короткий living-doc + ADR вместо энциклопедии.

## 6. S6 — Мелочь-хвост из ревью (1 frontend PR, грид)

Мёртвая ветка `isStaleConflictError` в `handlePricingAssist`; `measureElement` и на detail-строку (scroll-drift при раскрытой детали в >50); убрать divide-y линию на spacer-строках виртуализации; (бонус, если тривиально) выравнивание chevron+error-маркера в узкой ячейке w-8.

## 7. S7 — ОПЦИОНАЛЬНО: два продуктовых пункта (нужно отдельное «да», иначе пропускаем)

- **S7a. Обязательное обоснование при отправке КП ниже margin-floor:** в confirm-диалоге отправки при `below_floor` — обязательное текстовое поле «обоснование» (пишется в ActivityLog событием `quote.sent_below_floor` с комментом). Backend-гейт в `send_to_client` (код `BELOW_FLOOR_JUSTIFICATION_REQUIRED`). Лёгкий guardrail-стандарт B2B (DealHub), НЕ блокирует (self-approve остаётся). 1 full-stack PR.
- **S7b. Локализация имён справочников (P3-хвост):** НЕ трогаем схему/БД — расширяем существующий frontend-паттерн `DEAL_STAGE_LABEL_KEY` (код→i18n-ключ) на остальные lookup-поверхности (QuoteStatus, KYC-статусы, роли и т.д., где RU-`name` течёт в EN-UI: бейджи, интерполяция таймлайна). Дешёвый стандартный путь; `name` остаётся fallback. 1 frontend PR.

---

## 8. Раскладка по волнам и агентам

| Волна | Лейн | Задачи | PR |
|---|---|---|---|
| **A** | A1 backend (main) | S3: распил services → затем views+serializers | 2 |
| **A** | A2 frontend (worktree) | S2 консолидация настроек (EconomicsRail/диалоги) | 1 |
| **A** | A3 frontend (worktree) | S6 мелочь-хвост (GridRow/GridTable/actions — файлы НЕ пересекаются с A2) | 1 |
| — | ревьюер волны A | | |
| **B** | B1 backend (main) | S1-backend: display_type/is_optional/position + PDF (на распиленных сервисах) | 1 |
| **B** | B2 frontend (worktree; после мержа A2/A3) | S1-frontend: секции/заметки/optional в билдере + ↑/↓ | 1 |
| — | ревьюер волны B | | |
| **C** | C1 backend (main) | S4 контракт-гигиена + coverage-гейт | 1 |
| **C** | C2 docs (worktree) | S5 MSD v7 | 1 |
| **C** | C3 (если S7 утверждён) | S7a + S7b | 1–2 |
| — | финальный ревьюер + handoff | | |

## 9. На утверждение владельцем

1. **S1-скоуп**: секции/заметки/optional через `display_type` (Odoo-паттерн), optional исключены из итогов, показаны блоком в PDF; перемещение строк кнопками ↑/↓ (не drag) — ОК? Интерактивный выбор опций покупателем — отложен.
2. **S2**: `valid_until` убирается из диалога создания КП (молчаливый дефолт +14 дней, правится в Настройках) — ОК?
3. **S4**: coverage-гейт 30→70 — ОК?
4. **S5**: MSD сокращается до карты-указателя v7, полный старый текст в архив — ОК?
5. **S7a/S7b** (продуктовые): делать оба / один / пропустить?
