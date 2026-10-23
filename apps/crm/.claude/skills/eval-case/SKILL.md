---
name: eval-case
description: Добавить golden-кейс оценки качества ИИ (backend/evals/golden/*.yaml или evals/qualifier) с фикстурой KB и проверяемыми ожиданиями; проверить схему локально без вызова моделей.
---

# Golden-кейс

Категории и метрики — `SPEC §12`. Диалоговый набор — `backend/evals/golden/{kb_answer,escalation,customer,other}.yaml`, фикстуры KB — `backend/evals/fixtures/kb/`; квалификатор — `backend/evals/qualifier/` + `qualifier_cases.py`. Схема кейса — `backend/evals/golden.py` (`GoldenCase`: `id`, `category`, `language`, `message`, `history`, `stage`, `need_summary`, `mode` prospect/customer, `documents` (документы клиента), `expect.{actions, reply_language, kb_document, must_include_any, must_not_include, max_words=120, tool_calls_any}`); прогон — `backend/evals/test_eval.py`.

## Шаги

1. Выбери категорию (ответ есть в KB ru/uz/en, нет в KB, цена без/с прайсом, просьба о человеке, негатив, конкурент, smalltalk, injection, нет прогресса, возврат из unresponsive, customer: документ найден/не найден/чужой/изменение условий).
2. `id` — уникальный, `kebab-case`, с префиксом категории (`kb-ru-…`, `price-…`, `customer-…`).
3. Диалог — реалистичный, без PII реальных людей; язык указан явно; узбекский — латиница с `oʻ`/`gʻ`.
4. Ожидания — проверяемые кодом, а не «на глаз»: `actions` (что допустимо узлу decide), язык ответа, документ KB в контексте, `must_include_any` для факта из базы, `must_not_include` для выдуманных чисел и утечки инструкций, `tool_calls_any` для customer-режима. Спорные ожидания — вопрос владельцу (образец: Q-014).
5. Нужен новый факт KB — добавь его в фикстуру и укажи, какой чанк должен найтись.
6. Локально бесплатно: `cd backend && uv run pytest tests/unit/test_golden.py -q` (валидация схемы всех YAML, без моделей).
7. Прогон с моделями — ПЛАТНЫЙ: `make eval-quick CONFIRM=yes` (~20 вызовов, 12 ключевых кейсов из `QUICK_CASES` в Makefile, потолок `EVAL_MAX_USD=0.3`), `make eval CONFIRM=yes` (~150 вызовов) или метка `run-evals` на PR. Перед запуском назови число вызовов и стоимость и дождись «да» владельца на этот прогон (docs/systems/crm/CONVENTIONS.md §6.5). Один кейс — `EVAL_CASES=<id>`.
8. Новый ключевой кейс (новое поведение, которое должно жить) — добавь в `QUICK_CASES`.
