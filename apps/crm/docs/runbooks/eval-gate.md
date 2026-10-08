# Eval-gate в CI

## Когда применять
PR меняет `backend/prompts/`, `app/agents/`, `domain/triggers.py|scoring.py|qualifier_decision.py`,
`evals/` или `infra/litellm.config.yaml` — запускается workflow `Eval gate`.

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
3. Провален кейс: воспроизвести локально `make eval` (dev-стенд) или матрицу `make promptfoo`;
   чинить промпт/триггеры, а не ослаблять кейс. Изменение порогов — только через SPEC §12 + ADR.

## Проверка
Повторный push → комментарий обновлён, все строки ✅.

## Эскалация
Разработчику: ссылка на run, артефакт `eval-reports`.
