# ТЗ — локализация таймлайна (structured events) + границы ввода КП (2026-07-12)

**База:** main @ #306. Источник: eyes-on прогон полной цепочки заявка→КП→контракт (deal #25) в реальном браузере.
**Исполнение:** мультиагентный workflow (opus), ветка `fix/timeline-i18n-input-caps`.

## Контекст — подтверждённые находки

| # | Находка | Факт (проверено по коду) | Приоритет |
|---|---------|--------------------------|-----------|
| E1 | Таймлайн «История» показывает **сырые i18n-ключи** (`quote.approval_approve`, `quote.approval_complete`, `quote.submit_for_review`) и **русский хардкод** при EN-UI | `approvals.py:234,245` пишет ключ в `ActivityLog.action`; остальные 20+ сайтов пишут русскую прозу; `DealTimeline.tsx:54` рендерит `{entry.action}` без перевода. Модель (`crm/models/deals.py:348`) не имеет структурных полей события | **P1** — виден каждому покупателю на главном экране wedge-петли; для ВЭД-контрагентов таймлайн нечитаем |
| E2 | **Нет верхних границ** на количество/цену строки КП — UI и API приняли qty=1 500 000 без возражений | `QuoteItem.quantity` = `PositiveIntegerField(validators=[MinValueValidator(1)])`, макс-валидатора НЕТ; `frozen_base_price` `max_digits=14` (до 10¹²) без бизнес-капа; в `crm/serializers.py` нет `validate_quantity`. Прецедент: команда УЖЕ капит проценты (`margin_percent ≤ 500`, скидка ≤ 100 — `quotes.py:491,501`) | **P1** — fat-finger/вставка в чужое поле создаёт абсурдную сделку; экономика и лимиты кредитов считаются от мусора |
| E3 | Qty-инпут билдера имеет неверный `aria-label` | `QuoteBuilderGrid.tsx:681` — `aria-label={t('catalog.table.unit')}` (это «Ед. изм.», не «Количество») | P3 — тривиально, чинится попутно |

Вне области (зафиксировано отдельно): обязательное обоснование при отправке КП ниже margin-floor — продуктовое решение владельца; PDF-EN (Ф5) — owner-gated.

---

## E1 — Локализация таймлайна: structured events (мировая практика)

**Подход (как GitHub/Stripe timeline):** события пишутся МАШИННЫМ кодом + параметрами; человекочитаемый текст собирается на клиенте по локали зрителя. Backend НЕ переводит (иначе локаль зрителя неизвестна в момент записи).

### 1. Модель (`crm/models/deals.py`, миграция `crm/0058`)
Добавить в `ActivityLog`:
- `event_code = models.CharField(max_length=64, blank=True, default="", db_index=True)` — машинный код события, namespace через точку (`deal.created`, `quote.sent`, `contract.signed_client`, `payment.recorded`, …)
- `event_params = models.JSONField(default=dict, blank=True)` — параметры интерполяции (`{"deal_id": 25, "number": "КП-2026-00002"}`)

Старые строки НЕ мигрируются (fallback-рендер по `action`). Обратная миграция — RemoveField (безопасно).

### 2. Продьюсеры (22 сайта `ActivityLog.objects.create` + `_log` в approvals.py)
Файлы: `crm/services/{approvals,rfq,assignment,contracts,billing,quotes,deals}.py`, `crm/tasks.py`, `crm/views/leads.py`, `notifications/emails.py`, `core/audit.py`, `accounts/services/subscriptions.py`.

Для КАЖДОГО сайта: добавить `event_code=` + `event_params=` (минимальный дифф). Существующие RU `action`/`detail` СОХРАНИТЬ как есть — они остаются fallback'ом для legacy-строк и Unfold-админки (никакой регрессии). Особый случай approvals.py: `_log` сейчас кладёт сырой код в `action` — расширить `_log` так, чтобы код шёл в `event_code`, а в `action` — человекочитаемый RU (по образцу остальных сервисов).

Маркеры `[MANUAL_MODE]`/`[FORCE_ADMIN]` в action — сохранить; в event-модели выразить отдельным bool-параметром (`{"manual": true}`) и суффиксом кода при необходимости (напр. `contract.signed_client` + params.manual).

### 3. API (`crm/serializers.py` → `ActivityLogSerializer`)
Добавить `event_code`, `event_params` в fields. ⚠ Меняется OpenAPI → регенерация `schema.json` + `schema.d.ts` (api-contract гейт).

### 4. Frontend (`frontend/src/components/CRM/DealTimeline.tsx` + все места рендера ActivityLog, включая таймлайн контрагента)
Правило рендера:
```ts
const title = entry.event_code && i18n.exists('activity.' + entry.event_code + '.title')
  ? t('activity.' + entry.event_code + '.title', entry.event_params)
  : entry.action;            // legacy fallback
const detail = entry.event_code && i18n.exists('activity.' + entry.event_code + '.detail')
  ? t('activity.' + entry.event_code + '.detail', entry.event_params)
  : entry.detail;
```
(точную реализацию exists/fallback выбрать по конвенциям проекта; ключевое — старые строки без кода рендерятся как раньше).

### 5. i18n (`ru.json` + `en.json`)
Секция `activity.*`: для каждого кода `title` (+ `detail` там, где есть параметры). RU-текст = текущие человекочитаемые строки продьюсеров (1:1, чтобы RU-пользователь не заметил изменения), EN — профессиональный перевод. Плейсхолдеры i18next `{{param}}`.

### 6. Каталог кодов
Составляется инвентарным агентом по факту кода (каждый сайт → код/параметры/RU/EN), НЕ выдумывается заранее. Ориентировочно ~25 кодов: `deal.created`, `deal.stage_changed`, `deal.routed`, `deal.claimed`, `deal.item_added`, `deal.submitted`, `quote.submitted_for_review`, `quote.approval_step_approved`, `quote.approval_complete`, `quote.sent`, `quote.accepted`, `quote.rejected`, `contract.created`, `contract.signed_client`, `contract.signed_manager`, `contract.cancelled_force`, `invoice.issued`, `payment.recorded`, `act.signed`, `subscription.paid`, `email.sent`, `lead.converted`, `admin.audit`, …

### Критерии приёмки E1
- [ ] Ни один продьюсер не пишет сырой i18n-ключ в `action`.
- [ ] Таймлайн deal #25 (и новых сделок) на EN-UI — полностью английский; на RU-UI — русский; legacy-строки рендерятся как раньше.
- [ ] `check_i18n_symmetry` зелёный; ключи `activity.*` в ОБОИХ локалях.
- [ ] api-contract: schema.json + schema.d.ts регенерированы в том же PR.
- [ ] Тесты: backend — каждый затронутый сервис пишет корректный event_code+params (расширить существующие тесты сервисов или добавить точечные); frontend — компонентный тест DealTimeline: (a) event_code → перевод с параметрами, (b) legacy без кода → fallback на action/detail.

---

## E2 — Границы ввода строк КП

### Backend
1. **Константы через settings (Rule 2):** в `core/settings.py`:
   - `QUOTE_ITEM_MAX_QUANTITY = int(os.getenv("QUOTE_ITEM_MAX_QUANTITY", "1000000"))` (1 млн единиц — санитарный потолок, не бизнес-лимит)
   - `QUOTE_ITEM_MAX_UNIT_PRICE = Decimal(os.getenv("QUOTE_ITEM_MAX_UNIT_PRICE", "10000000000"))` (10 млрд за единицу в валюте строки — санитарный потолок)
2. **Валидация в сериализаторе** QuoteItem (`crm/serializers.py`): `validate_quantity` / `validate_frozen_base_price` (и `final_price_excl_vat`, если он write-able) против settings-капов. Форма ошибки — по прецеденту существующих валидаций КП (KP-04 отрицательная цена): посмотреть, как та ошибка доезжает до фронта, и сделать идентично; код ошибки — идентификатором (`QUOTE_ITEM_QTY_TOO_LARGE`, `QUOTE_ITEM_PRICE_TOO_LARGE`), сравнение по значению.
3. Проверить соседние write-able поля строк (`logistics_cost`, `customs_duty`) — тот же санитарный потолок цены.

### Frontend (`QuoteBuilderGrid.tsx`)
- `min`/`max` атрибуты на qty/price инпутах + клиентская отбивка (существующий паттерн ошибок грида/тостов), i18n-ключи для сообщений в ru+en (добавляет i18n-агент E1, ключи: `quote.validation.qtyTooLarge`, `quote.validation.priceTooLarge` — с параметром `{{max}}`).
- E3 попутно: `aria-label` qty-инпута → `t('quote.quantity')` (ключ уже существует, строка 605).

### Критерии приёмки E2
- [ ] API отклоняет qty=1 500 000 и цену выше капа с кодом ошибки; значения в пределах капов проходят.
- [ ] UI не даёт ввести/сохранить сверх-кап (отбивка с локализованным сообщением), существующий флоу с нормальными значениями не изменился.
- [ ] Тесты: сериализатор (границы: кап, кап+1, отрицательное), существующий сьют КП зелёный.
- [ ] api-contract регенерирован (валидаторы попадают в OpenAPI).

---

## Гейты (обязательные, локально — CI лежит)
Полный `pytest --create-db` · `npm run build` · vitest · eslint изменённых файлов · `check_i18n_symmetry` · api-contract (spectacular + gen:api-types, нулевой дифф после коммита) · adversarial-verify диффа. Затем eyes-on: таймлайн deal #25 на EN и RU.
