# New Celery Task

Создай новую Celery задачу с retry логикой и прогресс-репортингом.

## Аргументы

$ARGUMENTS — название задачи. Примеры:
- `GeneratePDF` — создаст generate_pdf task
- `ProcessImports` — создаст process_imports task
- `SendNotifications` — создаст send_notifications task

## Инструкции

1. Создай файл в `{app}/tasks.py`:

```python
from celery import shared_task
from celery.utils.log import get_task_logger
from django.utils import timezone
from core.models import ActivityLog

logger = get_task_logger(__name__)

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    queue='default',  # или 'pdf', 'imports' для специализированных очередей
)
def <task_name>(self, **kwargs):
    """
    Описание: что делает задача
    Retry: да, 3 раза с экспоненциальной задержкой
    """
    try:
        logger.info(f"<task_name> started with kwargs: {kwargs}")

        # Инициализация
        total_items = 100  # или получи из базы
        processed = 0

        # Основная логика
        for item in get_items():
            try:
                # Обработай item
                process_item(item)
                processed += 1

                # Отправляй прогресс каждые 10 %
                progress = (processed / total_items) * 100
                self.update_state(
                    state='PROGRESS',
                    meta={'current': processed, 'total': total_items, 'percent': progress}
                )

            except Exception as e:
                logger.error(f"Error processing item {item}: {e}")
                # Логируй ошибку, но продолжай
                ActivityLog.objects.create(
                    action='ERROR',
                    description=f"<task_name> error: {str(e)}",
                    error=str(e),
                )

        # Финальное логирование
        logger.info(f"<task_name> completed: {processed}/{total_items} items")
        ActivityLog.objects.create(
            action='COMPLETED',
            description=f"<task_name> completed successfully",
            metadata={'processed': processed, 'total': total_items},
        )

        return {
            'status': 'success',
            'processed': processed,
            'total': total_items,
        }

    except Exception as exc:
        logger.error(f"<task_name> failed: {exc}", exc_info=True)

        # Логируй в ActivityLog
        ActivityLog.objects.create(
            action='FAILED',
            description=f"<task_name> failed after retries",
            error=str(exc),
        )

        # Retry с экспоненциальной задержкой
        try:
            raise self.retry(exc=exc, countdown=60)
        except self.MaxRetriesExceededError:
            logger.critical(f"<task_name> max retries exceeded")
            return {
                'status': 'failed',
                'error': str(exc),
            }
```

2. Определи очередь в `core/celery.py`:

```python
from celery import Celery
import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

app = Celery('RailTech')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

# Очереди
app.conf.task_queues = {
    'default': {'exchange': 'default', 'routing_key': 'default'},
    'pdf': {'exchange': 'pdf', 'routing_key': 'pdf.#'},
    'imports': {'exchange': 'imports', 'routing_key': 'imports.#'},
}

# Роутинг
app.conf.task_routes = {
    'crm.tasks.generate_pdf': {'queue': 'pdf'},
    'sourcing.tasks.process_imports': {'queue': 'imports'},
}
```

3. Вызови задачу из ViewSet/Signal:

```python
from .tasks import <task_name>

# Асинхронный вызов
<task_name>.delay(param1='value1')

# Отложенный вызов (через 5 минут)
<task_name>.apply_async(
    args=(param1, param2),
    countdown=300,
)

# С приоритетом
<task_name>.apply_async(
    args=(param1,),
    priority=10,
)
```

4. Создай тесты в `{app}/tests/test_tasks.py`:

```python
from django.test import TestCase
from celery import current_app
from {app}.tasks import <task_name>
from core.models import ActivityLog

class <Task>TaskTests(TestCase):
    def setUp(self):
        current_app.conf.task_always_eager = True
        current_app.conf.task_eager_propagates = True

    def test_task_success(self):
        result = <task_name>.delay()
        self.assertEqual(result.status, 'SUCCESS')

        # Проверь ActivityLog
        log = ActivityLog.objects.filter(action='COMPLETED').latest('created_at')
        self.assertEqual(log.action, 'COMPLETED')

    def test_task_failure(self):
        # Mock error condition
        with self.assertRaises(Exception):
            <task_name>.delay(invalid_param=True)

    def test_task_progress(self):
        result = <task_name>.apply()
        # Проверь, что был прогресс
        self.assertIn('percent', str(result))
```

5. Создай celery worker сервис (в production):

```bash
# docker-compose.yml
celery:
  build: ./backend
  command: celery -A core worker -Q default,pdf,imports -l info
  environment:
    - DJANGO_SETTINGS_MODULE=core.settings
  depends_on:
    - redis
    - postgres

celery_beat:
  build: ./backend
  command: celery -A core beat -l info
  environment:
    - DJANGO_SETTINGS_MODULE=core.settings
  depends_on:
    - redis
    - postgres
```

## Параметры Celery Task

| Параметр | Описание | Пример |
|----------|---------|--------|
| `max_retries` | Макс. попыток | 3 |
| `default_retry_delay` | Задержка в сек | 60 |
| `autoretry_for` | Auto-retry на эти исключения | (Exception,) |
| `retry_backoff` | Экспоненциальная задержка | True |
| `retry_backoff_max` | Max задержка между retry | 600 (10 мин) |
| `retry_jitter` | Случайный сдвиг для задержки | True |
| `queue` | Очередь | 'default' \| 'pdf' \| 'imports' |
| `time_limit` | Timeout в сек | 3600 |
| `soft_time_limit` | Soft timeout | 3400 |

## Очереди по типам задач

- **default** — общие задачи (отправка уведомлений, обновления)
- **pdf** — генерация PDF (WeasyPrint)
- **imports** — загрузка данных (CSV, Excel)

## ActivityLog для трекинга

```python
ActivityLog.objects.create(
    action='STARTED' | 'PROGRESS' | 'COMPLETED' | 'FAILED' | 'ERROR',
    description='Human-readable description',
    metadata={
        'task_id': self.request.id,
        'progress': 45,
        'total': 100,
    },
    error='Exception message если есть ошибка',
)
```

## Progress Reporting (Frontend taskStore)

Frontend может отслеживать прогресс через WebSocket или polling:

```javascript
// Frontend (Vue/Pinia)
const taskStore = useTaskStore();
taskStore.trackTask(taskId);  // слушает PROGRESS updates
```

## После создания

1. Запусти Celery worker в dev:
   ```bash
   cd backend && celery -A core worker -l info --queues=default,pdf,imports
   ```

2. Запусти Celery beat для периодических задач:
   ```bash
   cd backend && celery -A core beat -l info
   ```

3. Запусти тесты:
   ```bash
   python -m pytest {app}/tests/test_tasks.py -v
   ```

4. Проверь Redis:
   ```bash
   redis-cli LLEN celery
   ```

5. Проверь Flower (мониторинг):
   ```bash
   celery -A core events --broker=redis://localhost:6379
   # или
   pip install flower
   celery -A core flower
   # http://localhost:5555
   ```

6. Сообщи:
   - Task file: `{app}/tasks.py`
   - Tests: `{app}/tests/test_tasks.py`
   - Queue: default | pdf | imports
