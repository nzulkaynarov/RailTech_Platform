# Бот молчит

## Когда применять
Клиент пишет боту, ответа нет (или только «передам коллеге»); в CRM новые сообщения
лида есть или нет.

## Диагностика
1. `curl -fsS http://localhost:8000/ready` (prod: `https://crm.<домен>/api/ready`) —
   ожидается 200 и `database/s3/litellm: ok`.
2. `make ps` — `api`, `worker`, `litellm`, `*-mcp` в состоянии healthy.
3. `make logs` и фильтр по событиям:
   - `bot_disabled` — нет токена или `TELEGRAM_MODE=disabled`;
   - `llm_call_failed` / `LlmUnavailableError` — модели недоступны (ответ «передам коллеге» — норма деградации);
   - `tg_rate_limited` — клиент упёрся в лимит `bot.rate_limit_per_minute`;
   - `dialog_tool_failed` — недоступен MCP-сервер.
4. Режим лида в CRM: `owner_mode = manager/paused` → бот молчит **намеренно**
   (лид у менеджера; кнопка «Вернуть боту»).
5. prod (webhook): `python scripts/set_webhook.py --info` — `pending_update_count`,
   `last_error_message`.
6. Канал ⚠️: алерты «LiteLLM» или «Очередь задач» указывают на причину.

## Действие
1. Лид у менеджера — штатно, ничего не делать.
2. LiteLLM недоступен: `make logs s=litellm`; проверить ключи провайдеров и лимиты
   в их консолях; `docker compose restart litellm`.
3. MCP-сервер упал: `docker compose restart kb-mcp crm-mcp docs-mcp`.
4. Webhook: `python scripts/set_webhook.py` (переустановить с secret_token).
5. dev/polling: `docker compose restart api` (одновременно может быть только один polling-процесс
   на токен — проверьте, что бот не запущен ещё где-то).

## Проверка
Написать боту тестовое сообщение → ответ ≤ 6 с; в CRM появился ход бота с `action`.

## Эскалация
Разработчику: время (Asia/Tashkent), `lead_id`, `request_id` из логов, вывод `/ready`.
