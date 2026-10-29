# Eval-gate в CI
Статус: действует · Владелец: лид · Обновлено: 2026-10-22

## Когда применять
PR меняет `backend/prompts/`, `app/agents/`, `domain/triggers.py|scoring.py|qualifier_decision.py`,
`evals/` или `infra/litellm.config.yaml`. **Evals платные** (~150 вызовов моделей на полный
прогон): на пуш workflow `Eval gate` только напоминает, прогон — вручную меткой `run-evals`
на PR (снимается после прогона) или кнопкой Run workflow. Потолок расходов — `EVAL_MAX_USD`
(CI: $2, локально `make eval`: $1, `make eval-quick`: $0.3); дошли до потолка — остальные
кейсы пропускаются, итог красный «прогон неполный».

## Диагностика
- Комментарий `## Eval-gate` в PR: метрики против порогов SPEC §12 и список проваленных кейсов.
- Job завершился с warning «секреты не заданы» — нет `ANTHROPIC_API_KEY`/`GEMINI_API_KEY`
  в GitHub Secrets (форки секретов не получают).
- Артефакт `eval-reports` — JSON отчёты; Langfuse (если заданы `LANGFUSE_*` секреты) —
  dataset `golden-dialog`, run `git-<sha>`, оценки `faithfulness`, `golden_pass`.

## Действие
1. Настройка (один раз, человек): Settings → Secrets and variables → Actions:
   `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` — **отдельные dev-ключи с лимитом бюджета** у провайдера;
   опционально `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`.
2. Сделать job обязательным: Settings → Branches → правило для `main` → required check `Eval gate (golden)`.
3. Провален кейс: сначала `make eval-quick CONFIRM=yes` или один кейс
   `EVAL_CASES=<id> make eval CONFIRM=yes`; полный `make eval CONFIRM=yes` — перед мержем, один раз;
   чинить промпт/триггеры, а не ослаблять кейс. Изменение порогов — только через SPEC §12 + ADR.

## Проверка
Поставить метку `run-evals` → комментарий обновлён, все строки ✅. Не ставьте метку на каждый
пуш: один прогон перед мержем.

## Эскалация
Разработчику: ссылка на run, артефакт `eval-reports`.
