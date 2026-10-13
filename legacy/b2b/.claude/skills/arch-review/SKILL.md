---
name: arch-review
description: "Архитектурное ревью бэкенда против инвариантов ИМЕННО этого проекта: Rule 8 (логика в services), multi-tenancy scoping, entitlement/KYC-гейты, error shape, N+1, FSM, AI через Celery. Использовать перед мержем бэкенд-изменений, при проектировании новой фичи («в какой слой это положить?») и когда владелец просит проверить архитектуру."
---

# /arch-review — ревью против инвариантов RailTech

Два режима: **ревью диффа** (по умолчанию) и **проектирование** (аргумент — описание будущей фичи).

## Режим 1: Ревью

### Шаг 1. Скриптовые проверки (0 токенов на поиск)

```bash
bash .claude/skills/arch-review/scripts/check.sh
```

Скрипт выдаёт кандидатов с `FILE:LINE`. Каждого кандидата ВЕРИФИЦИРОВАТЬ чтением контекста — допустимые исключения существуют (например, `.save()` внутри самих services — норма; `except Exception` в scripts-утилитах — терпимо). Вердикт по каждому: нарушение / допустимо + почему.

### Шаг 2. Смысловые проверки (грепом не ловятся — читать дифф)

Скоуп: `git diff HEAD --stat` → изменённые backend-файлы.

1. **Rule 8 глубоко**: view/admin = authorize → validate → ОДИН вызов сервиса → return. Ветвления бизнес-логики, side effects, email, Celery-dispatch во view — нарушение, даже без ORM-записи.
2. **Multi-tenancy**: каждый новый queryset по Deal/Quote/Contract/Invoice/Act/Fulfillment scoped? Продавец — только через `seller_visible_deal_ids`; компания — через `CompanyMember` memberships. Вопрос-триггер: «что увидит конкурент-продавец по чужой сделке?»
3. **Гейты в сервисах, не во views**: KYC floor (`SELLER_KYC_REQUIRED` ДО `SUBSCRIPTION_REQUIRED`), entitlement (`has_entitlement`/`quote_send_entitled`), capability (`can_buy`/`can_sell`), `is_platform_admin_viewer` → `ADMIN_VIEWER_CANNOT_ACT`.
4. **Стороны считает сервер**: новые "кто может нажать" — через `DealSideResolver` / `viewer_can_*` в ответе API, НЕ через `activeStatus` на фронте.
5. **FSM**: смена стадии сделки только через `change_stage`-сервис и `ALLOWED_STAGE_TRANSITIONS` — прямых `deal.stage = ...` быть не должно.
6. **N+1**: новые list-эндпоинты имеют `select_related`/`prefetch_related`; статистика — одним `aggregate()`, не `.count()` в цикле.
7. **AI**: новые AI-фичи ТОЛЬКО через `enqueue_ai_job(feature, payload, user)` + handler в `sourcing/tasks_ai.py` FEATURE_HANDLERS. Никаких LLM-вызовов в HTTP-хендлере.
8. **Транзакции**: многомодельные записи в `transaction.atomic`; отправка писем/Celery-задач — через `transaction.on_commit` (иначе гонка: воркер стартует раньше коммита).
9. **Уплоады**: новый путь загрузки вызывает валидаторы `core/validators.py`, включая `assert_content_matches_extension`.
10. **api-contract**: менялись модели/сериализаторы/verbose_name? → перегенерированы `backend/schema.json` (spectacular) + `frontend/src/api/schema.d.ts` (`gen:api-types`) в том же изменении, иначе CI-гейт упадёт.
11. **Миграции**: новые lookup-коды сеются `RunPython` с reverse no-op (Rule 1); деструктивные операции (drop/rename колонки) — вспомнить deploy-hazard: миграция применяется ДО подъёма нового кода.

### Шаг 3. Отчёт

```
## Arch Review

Вердикт: ✅ / ⚠️ замечания / ❌ блокирующие нарушения

### Блокирующее (нарушение IRON RULES / инвариантов)
1. file:line — что нарушено, каким правилом, как чинить

### Замечания
### Скриптовые кандидаты, признанные допустимыми (с обоснованием)
```

## Режим 2: Проектирование («куда положить фичу»)

Перед кодом новой фичи выдать таблицу:

| Вопрос | Ответ |
|---|---|
| Слой-владелец (ADR-0002/0004) | Platform Operator / seller / buyer / engineer |
| Куда код | `<app>/services/<x>.py` + thin view в `<app>/views/<y>.py` |
| Гейты | какие из: KYC, entitlement, capability, admin-viewer |
| Tenancy | как scoped queryset |
| Новые коды ошибок | `{"detail": "<CODE>"}` — перечислить |
| Асинхронщина | Celery-очередь (default/pdf/imports/ai), on_commit? |
| Контракт | нужна ли регенерация schema.json + schema.d.ts |
| Эталон | как это решает Odoo/SAP/Salesforce (PRODUCT RULE 1 — если фича продуктовая, сначала /benchmark) |

Только после утверждения таблицы — код.
