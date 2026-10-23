---
name: prompt-change
description: Изменить промпт агента (backend/prompts/*.md) — golden-кейс до/после, тест рендера, версия по хэшу в трейсах Langfuse, платный eval только с согласия владельца.
---

# Изменение промпта

Промпты только в `backend/prompts/` (`dialog_prospect.md`, `dialog_customer.md`, `qualifier.md`, `judge_faithfulness.md`); загрузка и подстановка — `app/agents/prompts.py` (`string.Template`, все плейсхолдеры обязательны; пользовательский текст и фрагменты KB — `xml_escape`/`xml_items` в отдельных XML-блоках). Решения (стадия, эскалация, цена, доступ) в промпт не переносятся: модель извлекает факты, код решает (`SPEC §1.3`, ADR-0016). Тексты, которые видит клиент (приветствие, fallback «нет в материалах», согласие), — не в промпте, а в `settings.texts` (скилл `settings-key`).

## Шаги

1. Сформулируй, какое поведение меняется и какой golden-кейс это покажет. Нет кейса — сначала добавь (`eval-case`); спорное ожидание — вопрос владельцу в `docs/QUESTIONS.md` (образец Q-014).
2. Правь файл промпта; новый плейсхолдер — добавь в `render(...)` вызова и в unit-тест рендера (`tests/unit/`): все плейсхолдеры подставлены, XML-блоки экранированы.
3. Golden: обнови/добавь кейсы (`backend/evals/golden/*.yaml`, квалификатор — `evals/qualifier/`); `uv run pytest tests/unit/test_golden.py -q` — схема валидна.
4. Версия промпта — `prompts.version(name)` (12 символов sha256 содержимого), уходит в трейсы Langfuse как `prompt_version`; Prompt Management Langfuse не используется, в UI ничего не правь. Откат — runbook `prompt-rollback.md`.
5. `make check`.
6. Прогон — ПЛАТНЫЙ (docs/systems/crm/CONVENTIONS.md §6.5): назови число вызовов и стоимость (`make eval-quick CONFIRM=yes` ~20 вызовов ≤ $0.3; один кейс `EVAL_CASES=<id>`; полный `make eval` ~150) и дождись «да» владельца на этот прогон. Нет кредитов/согласия — так и напиши в PR, прогон остаётся в чек-листе владельца. В CI — метка `run-evals` на PR (один раз перед мержем).
7. В PR: какие метрики `SPEC §12` затронуты, до/после (если прогон был); раздел «Проверить на dev» с 2–3 диалогами (ru/uz/en) и ожидаемыми ответами.
