# dev-стенд: запуск и диагностика

## Когда применять

- Первый запуск на новой машине.
- `make smoke-dev` или `curl http://localhost:8000/ready` не возвращают 200.
- Контейнер в статусе `unhealthy` / `restarting` / `exited`.

## Запуск

```bash
scripts/bootstrap_dev.sh            # .env, сборка, запуск, ожидание /ready
scripts/bootstrap_dev.sh --observability   # + Langfuse (http://localhost:3000)
make smoke-dev
```

Повторный запуск безопасен: `.env` не перезаписывается, данные в volumes сохраняются.

## Диагностика

| Команда | Норма |
|---|---|
| `make ps` | все сервисы `healthy`, `migrate` и `s3-init` — `exited (0)` |
| `curl -s localhost:8000/ready` | `{"status":"ok","checks":{"database":"ok","s3":"ok","litellm":"ok"}}` |
| `make logs s=api` | JSON-строки без `level: error`; при сбое `/ready` — событие `readiness_check_failed` с `check` и `error` |
| `make logs s=s3-init` | `bucket ready: langfuse` |
| `make logs s=migrate` | `Running upgrade -> 0001_init` или пусто (уже применено) |
| `make logs s=worker` | `Starting worker on all queues` |
| `make logs s=api \| grep bot_` | `bot_started` с `mode: polling` (или `bot_disabled`, если токен пуст) |
| `make ps kb-mcp crm-mcp` | оба `healthy` |

## Действие

1. **`/ready` → `database: fail`**: `make logs s=postgres`. Если пароль в `.env` менялся после первого запуска — Postgres хранит старый. ⚠️ Сброс данных: `docker compose -f infra/docker-compose.yml -f infra/docker-compose.dev.yml --env-file .env down -v` (удаляет все volumes), затем `make up`.
2. **`s3: fail`**: `make logs s=rustfs` и `make logs s=s3-init`. Если `s3-init` упал с `curl: (22) … 400/403` — неверная пара `S3_ACCESS_KEY`/`S3_SECRET_KEY` (сверьте `.env`, затем `make up`). Если `rustfs` не стартует — смотрите в логе ошибку тома `/data`.
3. **`litellm: fail`**: `make logs s=litellm`. Частые причины: `LITELLM_MASTER_KEY` не начинается с `sk-`; синтаксическая ошибка в `infra/litellm.config.yaml`.
4. **`migrate` упал** → api/worker не стартуют: `make logs s=migrate`, исправьте причину, затем `make migrate` и `make up`.
5. **Порт 80 занят** (Caddy не стартует): задайте `HTTP_PORT=8080` в `.env`, `make up`, CRM — `http://localhost:8080`.
7. **Бот молчит**: `make logs s=api`. `bot_disabled` — пуст `TELEGRAM_BOT_TOKEN`; `TelegramUnauthorizedError` — неверный токен; `TelegramConflictError` — тот же токен уже опрашивает другой процесс (второй стенд, старый webhook); `dialog_agent_failed` / `service_unavailable` в ответе — недоступны `kb-mcp`/`crm-mcp` или LiteLLM (`make ps`, `make logs s=crm-mcp`). Бот не отвечает на вопросы до нажатия «Согласен» — это норма.
9. **Карточки не приходят в канал**: `make settings key=notifications` — задан ли `channel_id`; бот должен быть администратором канала; `make logs s=worker | grep -E "channel_not_configured|sync_escalation_post"`.
10. **«Привяжите Telegram в профиле CRM» на кнопке «Забрать»**: у пользователя не заполнен Telegram ID (раздел «Пользователи»).
11. **Не войти: «Слишком много попыток»**: блокировка на 15 минут после 10 ошибок; админ может сбросить пароль в «Пользователи» (сбрасывает и блокировку). Потерян пароль последнего админа: `make create-admin email=<его email>`.
8. **Ответ «уточню у коллег» на вопрос по KB**: пробел KB (запись в `kb_gaps`) — проверьте `make kb-demo` и порог `kb.min_score` в настройках.
6. **Порт 5432/9000/9001/4000/8000/3000 занят** (`port is already allocated`) другим проектом или локальным сервисом: задайте свободный порт в `.env` — `DEV_POSTGRES_PORT`, `DEV_S3_PORT`, `DEV_S3_CONSOLE_PORT`, `DEV_LITELLM_PORT`, `DEV_API_PORT`, `DEV_LANGFUSE_PORT` (например, `DEV_API_PORT=8001`), затем `make up`. `bootstrap_dev.sh` и `make smoke-dev` читают порты из `.env`; в командах этого runbook подставляйте свой порт вместо 8000.

## Проверка

`make smoke-dev` → `Smoke OK`.

## Эскалация

Разработчику: вывод `make ps`, `make logs s=<сервис> | tail -200`, `curl -s localhost:8000/ready`, время сбоя (Asia/Tashkent), `X-Request-ID` из ответа.
