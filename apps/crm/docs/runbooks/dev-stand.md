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
| `make ps` | все сервисы `healthy`, `migrate` — `exited (0)` |
| `curl -s localhost:8000/ready` | `{"status":"ok","checks":{"database":"ok","minio":"ok","litellm":"ok"}}` |
| `make logs s=api` | JSON-строки без `level: error`; при сбое `/ready` — событие `readiness_check_failed` с `check` и `error` |
| `make logs s=migrate` | `Running upgrade -> 0001_init` или пусто (уже применено) |
| `make logs s=worker` | `Starting worker on all queues` |

## Действие

1. **`/ready` → `database: fail`**: `make logs s=postgres`. Если пароль в `.env` менялся после первого запуска — Postgres хранит старый. ⚠️ Сброс данных: `docker compose -f infra/docker-compose.yml -f infra/docker-compose.dev.yml --env-file .env down -v` (удаляет все volumes), затем `make up`.
2. **`minio: fail`**: `make logs s=minio`. Ошибка pull образа — образ MinIO снят с Docker Hub (ADR-0009); проверьте `MINIO_IMAGE` в `.env` (пусто = значение по умолчанию из compose).
3. **`litellm: fail`**: `make logs s=litellm`. Частые причины: `LITELLM_MASTER_KEY` не начинается с `sk-`; синтаксическая ошибка в `infra/litellm.config.yaml`.
4. **`migrate` упал** → api/worker не стартуют: `make logs s=migrate`, исправьте причину, затем `make migrate` и `make up`.
5. **Порт 80 занят** (Caddy не стартует): задайте `HTTP_PORT=8080` в `.env`, `make up`, CRM — `http://localhost:8080`.
6. **Порт 5432/9000/4000/8000 занят** локальным сервисом: остановите его или уберите проброс порта в `infra/docker-compose.dev.yml` (локально, без коммита).

## Проверка

`make smoke-dev` → `Smoke OK`.

## Эскалация

Разработчику: вывод `make ps`, `make logs s=<сервис> | tail -200`, `curl -s localhost:8000/ready`, время сбоя (Asia/Tashkent), `X-Request-ID` из ответа.
