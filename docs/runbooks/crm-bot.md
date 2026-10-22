# crm-bot — Telegram-бот отдельным процессом (S0-4)

Волна 10, этап 0; основание — ADR-0017 (надёжность), `arch-audit-current.md` §3.1 и §7.5. Бот больше не живёт в процессе `crm-api`.

## Кто что делает

| Процесс | Telegram |
|---|---|
| `crm-bot` (`python -m app bot`, образ `rt-crm-backend`, **одна реплика**) | **Всё входящее:** long polling (`getUpdates`) или приём `POST /telegram/webhook`; проверка заголовка `X-Telegram-Bot-Api-Secret-Token`; `setWebhook` по `CRM_DOMAIN` / `TELEGRAM_WEBHOOK_URL` (FIX-66); диалоговый агент, меню, ответы клиенту; публикация профиля бота при старте; статус и пульс в таблицу `bot_runtime` |
| `crm-api` | Бота не запускает, апдейтов не принимает (`/telegram/webhook` в нём нет — 404). **Исходящие**, которые он делает сам: «Проверить канал» (`sendMessage` в канал команды), публикация профиля бота при сохранении (`setMyName` и т. п.), проверка токена `getMe` перед сохранением. Сохраняет токен в БД и просит `crm-bot` перезапуститься |
| `crm-worker` | Только исходящие из очереди: карточки эскалаций и уведомления команде, сообщения лидам (`CurrentBotSender`, `Container.telegram_bot()` — токен читается из БД при каждом вызове, перезапуск не нужен) |
| «Центр внешних сервисов» (монитор в воркере) | Прямые `getMe` + `getWebhookInfo` к Telegram — правда о токене и вебхуке, от процессов не зависит |

Почему одна реплика: у одного токена может быть один потребитель `getUpdates`; второй получит `409 Conflict`. В режиме webhook вторая реплика
безвредна, но смысла не имеет.

## Связь через БД (таблица `bot_runtime`, одна строка)

* `crm-bot` пишет: `running`, `source` (`db`/`env`/`none`), `username`, `last_error`, итог публикации профиля, **пульс** `heartbeat_at`
  (при изменении статуса — сразу, иначе раз в `BOT_HEARTBEAT_S` = 10 с). При штатной остановке пульс сбрасывается.
* `crm-api` читает статус для «Подключений», «Состояния системы» и чек-листа настройки. Пульса нет дольше `BOT_STALE_AFTER_S` = 45 с
  (или процесс ни разу не отчитывался) — бот считается **не работающим**, причина — «Процесс бота (crm-bot) не отвечает».
* Смена токена в «Подключениях»: `getMe` → запись токена (зашифрованного) и `restart_requested_at` в одной транзакции → API ждёт до
  `BOT_RESTART_WAIT_S` = 10 с, пока `crm-bot` выполнит запрос, и отвечает. `crm-bot` опрашивает БД раз в `BOT_POLL_INTERVAL_S` = 2 с, при
  запросе (или при смене `integration_secrets.updated_at` токена другим путём) перезапускает бота **внутри процесса**: останавливает
  polling, снимает вебхук старого бота (webhook), стартует с новым токеном. Диспетчер и агент пересобираются не каждый раз.
* Не успел за 10 с (процесс лежит или занят) — токен всё равно сохранён; когда `crm-bot` поднимется, он прочитает действующий токен сам.
* Режим (`TELEGRAM_MODE`) — переменная окружения, в БД её нет и в «Подключениях» её не меняют: поправьте `.env` и `up -d crm-bot crm-api`.
* Недоступный Telegram при старте процесс не роняет: ошибка в `last_error`, повторная попытка каждые `BOT_RETRY_S` = 30 с. Упавший polling
  (отозванный токен, `409`) поднимается тем же путём.

## Диагностика

| Симптом | Что смотреть |
|---|---|
| «Процесс бота (crm-bot) не отвечает» | `docker compose ps crm-bot`, `docker compose logs crm-bot`; healthcheck — `GET :8001/health` (503, если упал внутренний цикл; недоступный Telegram не повод для перезапуска) |
| «Telegram не принимает токен» / `409` | токен в «Подключениях»; второй сервер/стенд с тем же токеном — остановить |
| Вебхук не доходит | `docker compose logs caddy` (маршрут `/telegram/webhook` → `crm-bot:8001`), «Центр внешних сервисов» → Telegram: url, `pending_update_count`, последняя ошибка; `python -m app telegram-webhook info` |
| Токен сменили, бот со старым | `docker compose logs crm-bot | grep bot_restart_requested`; в БД: `SELECT restart_requested_at, restart_applied_at, heartbeat_at FROM bot_runtime;` |

## Проверка на стенде без токена (заглушка Bot API)

`apps/crm/scripts/fake_bot_api.py` — заглушка на стандартной библиотеке. В `.env` стенда: `TELEGRAM_BOT_TOKEN=<число>:<любая строка>` (формат
токена, значение вымышленное), `TELEGRAM_API_BASE_URL=http://fake-bot-api:8081`. Заглушку запустить в сети проекта:

```
docker run -d --name <проект>-fake-bot-api --network <проект>_default --network-alias fake-bot-api -p 127.0.0.1:18999:8081 \
  -v "$PWD/apps/crm/scripts/fake_bot_api.py:/fake.py:ro" --entrypoint python <образ crm-api> /fake.py --port 8081
curl -s -X POST 127.0.0.1:18999/_inject -H 'Content-Type: application/json' -d '{"update_id":1,"message":{...}}'   # апдейт
curl -s 127.0.0.1:18999/_log                                                                                       # вызовы Bot API
```

Сценарии: апдейт доходит до обработчика и `sendMessage` уходит; остановка `crm-api` — бот отвечает; остановка `crm-bot` — API работает, статус «не
отвечает»; смена токена через `PUT /api/v1/integrations/telegram/token` — в журнале заглушки вызовы нового бота (`bot_id`); webhook: `setWebhook`
виден в журнале, `POST` через Caddy с верным заголовком — 200, с неверным или без — 404, прямой `POST` в `crm-api` — 404. После проверки — `down -v`
проекта и удаление контейнера заглушки.
