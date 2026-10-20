# dev-стенд ERP: запуск, порты и диагностика

## Когда применять

- Первичный запуск ансамбля или приложения ERP на машине разработчика.
- Ошибки 502 Bad Gateway или 503 Service Unavailable при обращении к `http://erp.localhost`.
- Проверка здоровья `http://erp.localhost/health/` возвращает HTTP 503 (`"database": "down"`) или не отвечает.
- Контейнеры группы `erp-*` переходят в статус `unhealthy`, `restarting` или аварийно завершаются (`exited 1`).
- Отсутствие ответа от SPA (белый экран, сбой загрузки скриптов Vite).

---

## Запуск

ERP функционирует в составе единого локального стенда ансамбля (`infra/compose`):

```bash
# 1. Генерация .env из .env.example (идемпотентно, случайные криптографические ключи)
make env

# 2. Сборка и запуск контейнеров ансамбля (crm, erp, cabinet, infra)
make up

# 3. Запуск с профилем observability (включает Langfuse на langfuse.localhost)
make up-obs

# 4. Проверка доступности доменов
make smoke
```

URL в браузере:
- **ERP SPA**: `http://erp.localhost` (при нестандартном порте: `http://erp.localhost:${HTTP_PORT}`)
- **ERP Health**: `http://erp.localhost/health/` (тот же ответ у `/api/v1/health/`; проверяет подключение к БД, результат кэшируется на 10 с). Отдельной проверки готовности (`ready`) у ERP нет: миграции, Redis и воркеры проверяются командами из таблицы ниже.

---

## Диагностика

| Команда | Ожидаемая норма | Признак проблемы |
|---|---|---|
| `make ps` | Сервисы `erp-backend`, `erp-web`, `erp-worker`, `erp-worker-ai`, `erp-beat` в статусе `Up (healthy)` | Статус `unhealthy`, `Restarting` или `Exit 1` |
| `curl -s http://erp.localhost/health/` | HTTP 200, `{"status":"healthy","database":"up"}` | HTTP 503 `{"status":"unhealthy","database":"down"}`, 502 Bad Gateway или Connection refused |
| `docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env exec erp-backend python manage.py migrate --check` | код возврата 0 (все миграции применены) | ненулевой код — есть ещё не применённые миграции |
| `docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env exec redis sh -c 'redis-cli -a "$REDIS_PASSWORD" --no-auth-warning ping'` | `PONG` | нет ответа / ошибка авторизации |
| `docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env exec erp-backend celery -A core inspect ping` | ответ `pong` от `celery@…` | нет ответа от воркеров |
| `make logs s=erp-backend` | Логи Daphne/ASGI, статус ответов 200/201/204 | Трейсбеки Django, `OperationalError`, `ImproperlyConfigured` |
| `make logs s=erp-worker` | `[celery@...] ready`, приём задач из очереди `celery` | Ошибки подключения к Redis, синтаксические ошибки задач |
| `make logs s=erp-worker-ai` | `[celery@...] ready`, ожидание очереди `ai` | Ошибки LiteLLM, сбои авторизации ключа шлюза |
| `make logs s=caddy` | Успешный прокси-трафик к upstream `erp-web:80` и `erp-backend:8000` | Сообщения `dial tcp ... connect: connection refused` |

---

## Действия по устранению неисправностей

### 1. `/health/` отвечает 503, `database: down` (БД недоступна)
1. Проверьте состояние Postgres: `make logs s=postgres`.
2. Убедитесь, что параметры подключения совпадают в `.env` (`POSTGRES_DB=erp`, `POSTGRES_USER`, `POSTGRES_PASSWORD`).
3. Если пароль в `.env` был изменён после первой инициализации базы, Postgres продолжает использовать старый том данных.
   ⚠️ **Сброс локальных данных БД (только dev):**
   ```bash
   docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env down -v
   make up
   ```

### 2. `migrate --check` завершается ненулевым кодом (не применены миграции)
1. Выполните накат миграций через контейнер бэкенда:
   ```bash
   make -C apps/erp migrate
   ```
2. Проверьте журнал миграций:
   ```bash
   docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env exec erp-backend python manage.py showmigrations
   ```

### 3. Redis не отвечает на `ping` (сбой очереди/кэша)
1. Проверьте контейнер Redis: `make logs s=redis`.
2. ERP использует отдельную БД под Celery (БД 1) и Channels (БД 2). Убедитесь, что `REDIS_URL=redis://redis:6379/1`.

### 4. Celery worker не отвечает на `inspect ping`
1. Проверьте активность основного воркера:
   ```bash
   docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env exec erp-backend celery -A core inspect ping
   ```
2. Перезапустите воркеры:
   ```bash
   docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env restart erp-worker erp-worker-ai erp-beat
   ```

### 5. Конфликт порта 80 на хосте (`port is already allocated`)
Если на рабочей станции занят порт 80 (другим сервером, Nginx, Apache):
1. Откройте файл `.env`.
2. Задайте свободный порт: `HTTP_PORT=8080`.
3. Перезапустите ансамбль: `make up`.
4. ERP будет доступен по адресу: `http://erp.localhost:8080`.

### 6. Белый экран или ошибка «Failed to resolve import» в браузере
В dev-режиме анонимные тома `node_modules` контейнера `erp-web` могут содержать устаревшие зависимости после обновления пакетов.
1. Запустите пересборку с обновлением анонимных томов:
   ```bash
   make up
   ```
2. Если зависимости менялись в `package.json`, выполните локальную установку:
   ```bash
   cd apps/erp/frontend && npm install
   ```

---

## Проверка восстановления

1. `make smoke` печатает `smoke: ok` — `/health` отвечает 200 на всех трёх доменах (`crm.localhost`, `erp.localhost`, `cabinet.localhost`).
2. `curl -s http://erp.localhost/health/` возвращает HTTP 200 и `"status": "healthy"`; `migrate --check` и `celery -A core inspect ping` (таблица «Диагностика») — без ошибок.
3. В браузере открывается экран входа ERP SPA без ошибок в консоли разработчика.

---

## Эскалация

При невозможности устранить сбой приложите к обращению:
1. Вывод команды `make ps`.
2. Свежие логи бэкенда: `make logs s=erp-backend | tail -n 200`.
3. Результат проверки здоровья: `curl -v http://erp.localhost/health/`.
4. Точное локальное время сбоя (Asia/Tashkent) и значение заголовка `X-Request-ID`.
