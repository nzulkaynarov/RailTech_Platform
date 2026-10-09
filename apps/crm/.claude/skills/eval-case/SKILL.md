---
name: eval-case
description: Добавить golden-кейс оценки качества ИИ (backend/evals/golden/*.yaml) с фикстурой KB и проверяемыми ожиданиями, проверить схему локально.
---

# Golden-кейс

Категории и метрики — `SPEC §12`. Набор живёт в `backend/evals/golden/`, фикстуры KB — `backend/evals/fixtures/kb/`. Схема кейса — `backend/evals/golden.py` (`GoldenCase`: `id`, `category`, `language`, `message`, `history`, `stage`, `need_summary`, `expect.{actions, reply_language, kb_document, must_include_any, must_not_include, max_words}`); прогон — `backend/evals/test_eval.py`.

## Шаги

1. Выбери категорию (ответ есть в KB ru/uz/en, нет в KB, просьба о человеке, негатив, конкурент, smalltalk, injection, нет прогресса, возврат из unresponsive, customer: документ найден/не найден/чужой).
2. `id` — уникальный, `kebab-case`, с префиксом категории.
3. Диалог — реалистичный, без PII реальных людей; язык указан явно.
4. Ожидания — проверяемые кодом, а не «на глаз»: язык ответа, ожидаемая эскалация и коды триггеров, стадия, ожидаемый документ KB в контексте, запрет чисел вне KB, отсутствие утечки инструкций.
5. Если нужен новый факт KB — добавь его в фикстуру и укажи, какой чанк должен найтись.
6. Локально: `cd backend && uv run pytest tests/unit -k golden` (валидация схемы всех YAML, без вызова моделей).
7. Прогон с моделями — `make eval` (CI / человек с ключами).
