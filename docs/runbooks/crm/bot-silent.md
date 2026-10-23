# Бот молчит

## Когда применять
Клиент пишет боту, ответа нет (или только «передам коллеге»); в CRM новые сообщения
лида есть или нет.

## Диагностика
1. `curl -fsS http://localhost:8000/ready` (prod: `https://crm.<домен>/api/ready`) —
   ожидается 200 и `database/s3/litellm: ok`.
2. `make ps` — `crm-api`, `crm-bot`, `crm-worker`, `litellm`, `*-mcp` в состоянии healthy. Бота запускает только `crm-bot`
   (S0-4): статус в «Подключениях» / «Состоянии системы», «Процесс бота не отвечает» = `crm-bot` лежит.
3. `make logs s=crm-bot` и фильтр по событиям:
   - `bot_disabled` — нет токена или `TELEGRAM_MODE=disabled`;
   - `llm_call_failed` / `LlmUnavailableError` — модели недоступны (ответ «передам коллеге» — норма деградации); поле `detail` — текст провайдера: «credit balance is too low» / «exceeded your current quota» — кончились кредиты/квота, «x-api-key» — неверный ключ;
   - `tg_rate_limited` — клиент упёрся в лимит `bot.rate_limit_per_minute`;
   - `dialog_tool_failed` — недоступен MCP-сервер.
4. Режим лида в CRM: `owner_mode = manager/paused` → бот молчит **намеренно**
   (лид у менеджера; кнопка «Вернуть боту»).
5. prod (webhook): `python scripts/set_webhook.py --info` — `pending_update_count`,
   `last_error_message`.
6. Канал ⚠️: алерты «LiteLLM», «Модель <алиас>» (кредиты/квота/ключ, проба раз в час) или «Очередь задач» указывают на причину.
7. Проверить модель без запасного перехода LiteLLM:
   `curl -s localhost:4000/v1/chat/completions -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H 'Content-Type: application/json' -d '{"model":"dialog-model","max_tokens":1,"disable_fallbacks":true,"messages":[{"role":"user","content":"ping"}]}'`

## Действие
1. Лид у менеджера — штатно, ничего не делать.
2. LiteLLM недоступен: `make logs s=litellm`; проверить ключи провайдеров и лимиты
   в их консолях; `docker compose restart litellm`.
3. «Модель …: закончились кредиты или квота» — пополнить баланс (Anthropic: Plans & Billing;
   Google AI Studio: billing/quota). Алерт снимется сам после следующей успешной пробы (≤ 1 ч).
   Ключи CI (GitHub Secrets) держите отдельными с лимитом — прогоны eval-gate расходуют сотни вызовов.
4. MCP-сервер упал: `docker compose restart kb-mcp crm-mcp docs-mcp`.
5. Webhook: `python scripts/set_webhook.py` (переустановить с secret_token).
6. dev/polling: `docker compose restart crm-bot` (одновременно может быть только один polling-процесс
   на токен — проверьте, что бот не запущен ещё где-то).

## Проверка
Написать боту тестовое сообщение → ответ ≤ 6 с; в CRM появился ход бота с `action`.

## Эскалация
Разработчику: время (Asia/Tashkent), `lead_id`, `request_id` из логов, вывод `/ready`.
