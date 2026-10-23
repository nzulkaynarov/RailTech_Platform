# Celery worker, worker-ai и Celery Beat в ERP

## Когда применять

- Фоновые задачи зависают в очереди или не берутся в работу (генерация PDF-документов, импорт каталогов из Excel, отправка email-уведомлений).
- Асинхронные ИИ-задачи (`AIJob`: авторазбор заявок, сопоставление позиций, обогащение карточек товара) бесконечно находятся в статусе `pending`/`processing`.
- Периодические задачи не запускаются: курсы валют ЦБ РУз не обновляются на текущую дату, суточные счетчики не сбрасываются.
- Внесение изменений в код задач (`tasks.py`), модели или сервисы (воркеры в dev-окружении не перезагружаются автоматически при изменении файлов).

---

## Архитектура воркеров и очередей

ERP разделяет обработку фоновых задач на два независимых пула воркеров и один планировщик:

| Сервис | Очередь | Назначение и специфика |
|---|---|---|
| `erp-worker` | `celery` (default) | Рендеринг PDF (WeasyPrint), отправка транзакционных писем, импорт таблиц, синхронизация документов. Задачи поддерживают повторные попытки (retry с backoff). |
| `erp-worker-ai` | `ai` | Вызовы моделей через шлюз LiteLLM (`intake-model`, `match-model`, `draft-model`, `enrich-model`). Задачи выполняются **без повторных попыток** (платные вызовы). Строгий контроль суточного бюджета `AI_DAILY_BUDGET_USD`. |
| `erp-beat` | — | Планировщик периодических задач (`refresh_exchange_rates` из ЦБ РУз, очистка временных файлов и устаревших сессий). |

Транспорт очередей — **`redis-broker`, БД 1** (`redis://redis-broker:6379/1`): `appendonly yes`, `noeviction`, очередь переживает рестарт Redis (S0-2).

---

## Диагностика

| Команда | Ожидаемая норма | Признак проблемы |
|---|---|---|
| `docker compose ... exec erp-backend celery -A core inspect ping` | `pong` от всех запущенных воркеров | Отсутствие ответа, таймаут, `Error: No nodes replied within time constraint` |
| `docker compose ... exec erp-backend celery -A core inspect active` | Список выполняемых задач или пустой словарь `{}` | Список задач с аномально долгим временем выполнения |
| `make logs s=erp-worker` | Завершение задач: `Task ... succeeded in ...s` | `Task ... raised unexpected: ...`, MemoryError, ошибки WeasyPrint |
| `make logs s=erp-worker-ai` | Успешные вызовы шлюза: `call_json completed` | Ошибки `AI_BUDGET_EXCEEDED`, 429 от LiteLLM, `Task ... soft time limit exceeded` |
| `make logs s=erp-beat` | Регулярные строки: `Scheduler: Sending due task ...` | Beat аварийно завершился, ошибки блокировки расписания |

Проверка длины очередей в Redis:
```bash
docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env exec redis-broker redis-cli -n 1 LLEN default
docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env exec redis-broker redis-cli -n 1 LLEN ai
```
*Норма — 0 или небольшие значения при пиковой нагрузке.*

---

## Порядок действий

### 1. Перезапуск воркеров после правок кода (обязательно)
Поскольку код монтируется в контейнеры, но воркеры держат модули Python в памяти:
```bash
docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env restart erp-worker erp-worker-ai erp-beat
```

### 2. Принудительное снятие зависшей задачи
Если конкретная задача (например, тяжёлый рендеринг PDF или парсинг повреждённого Excel-файла) заблокировала процесс:
1. Выясните ID задачи:
   ```bash
   docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env exec erp-backend celery -A core inspect active
   ```
2. Отзовите задачу с немедленным прерыванием процесса:
   ```bash
   docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env exec erp-backend celery -A core control revoke <task_id> --terminate
   ```

### 3. Очистка переполненной очереди при аварии
⚠️ **Внимание: действие удаляет все стоящие в очереди, но ещё не начатые задачи!**
```bash
docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env exec erp-backend celery -A core purge -f
```

### 4. Ручной принудительный запуск обновления курсов ЦБ РУз
Если Celery Beat пропустил запуск или курсы валют на сегодня отсутствуют:
```bash
docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env exec erp-backend python manage.py shell -c "
from finance.services.fx import resolve_rate
from master_data.tasks import refresh_exchange_rates
res = refresh_exchange_rates()
print('Rates refreshed:', res)
usd = resolve_rate('USD')
print('Current USD rate:', usd)
"
```

### 5. Превышение суточного бюджета ИИ (`AI_BUDGET_EXCEEDED`)
1. Проверьте текущий расход и лимиты:
   ```bash
   make -C apps/erp ai-status
   ```
2. Если владелец платформы одобрил расширение бюджета, увеличьте `ERP_AI_DAILY_BUDGET_USD` в `.env`.
3. Синхронизируйте ключ в LiteLLM:
   ```bash
   make -C apps/erp ai-gateway-sync
   ```

---

## Проверка восстановления

1. `docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env exec erp-backend celery -A core inspect ping` отвечает `pong` от воркеров.
2. Тестовое создание черновика КП или генерация PDF завершается за ожидаемое время (≤ 5 с).
3. `make -C apps/erp ai-status` подтверждает корректный статус шлюза LiteLLM и положительный остаток бюджета.

---

## Эскалация

При систематическом зависании воркеров или падении очередей предоставьте:
1. Вывод команды `celery -A core inspect active`.
2. Логи проблемного контейнера: `make logs s=erp-worker | tail -n 100`.
3. Запись ошибки из журнала аудита `core.AuditLog` или `ai.AICall`.
