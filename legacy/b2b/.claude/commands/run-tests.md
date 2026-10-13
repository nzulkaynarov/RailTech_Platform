# Run Tests

Запусти полный набор тестов с coverage отчётом.

## Инструкции

### 1. Backend Tests (pytest + coverage)

```bash
cd backend

# Все тесты с покрытием
python -m pytest --cov=. --cov-report=html --cov-report=term-missing --tb=short

# Только специфичный app
python -m pytest catalog/ --cov=catalog --tb=short -v

# Только специфичный файл
python -m pytest accounts/tests/test_models.py -v

# С отладкой
python -m pytest --pdb --tb=long
```

### 2. Frontend Tests (npm)

```bash
cd frontend

# Все тесты
npm run test

# Watch mode (для разработки)
npm run test -- --watch

# С coverage
npm run test -- --coverage

# Специфичный файл
npm run test -- QuoteBuilder.test.tsx
```

### 3. Интеграционные тесты

```bash
cd backend

# Тесты viewsets (API endpoints)
python -m pytest accounts/tests/test_viewsets.py -v

# Тесты celery tasks
python -m pytest sourcing/tests/test_tasks.py -v
```

## Backend Coverage Targets

| Компонент | Target |
|-----------|--------|
| models.py | 90% |
| serializers.py | 85% |
| viewsets.py | 80% |
| tasks.py | 80% |
| signals.py | 90% |

## Проверка результатов

После запуска:

```bash
# Backend HTML report
open htmlcov/index.html

# Backend терминал output
# Ищи эту строку:
# TOTAL ... 85% ... 1500 ... 225
#         ^coverage% ^total lines ^missed lines
```

## Частые проблемы

### Database errors в тестах

```bash
# Тесты используют test database
# Если есть ошибки миграций:
python -m pytest --reuse-db  # Переиспользуй DB между запусками
python -m pytest --create-db  # Пересоздай DB
python -m pytest -p no:django  # Отключи Django plugin если проблемы
```

### Timeout ошибки (Celery)

```python
# В conftest.py или тестовом файле:
from celery import current_app

@pytest.fixture(autouse=True)
def celery_config():
    current_app.conf.task_always_eager = True  # Синхронное выполнение
    current_app.conf.task_eager_propagates = True
```

### Import errors

```bash
# Убедись, что виртуальное окружение активировано
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate  # Windows

# Переинсталлируй dependencies
pip install -e .
pip install -r requirements-dev.txt
```

## pytest.ini Configuration

```ini
[pytest]
DJANGO_SETTINGS_MODULE = core.settings
python_files = tests.py test_*.py *_tests.py
python_classes = Test*
python_functions = test_*
addopts =
    --strict-markers
    --tb=short
    --disable-warnings
    -ra
testpaths = .
```

## Markers для организации

```bash
# Помечай тесты
@pytest.mark.unit  # Быстрые unit тесты
@pytest.mark.integration  # Интеграционные
@pytest.mark.slow  # Медленные

# Запускай конкретные
python -m pytest -m unit -v
python -m pytest -m "not slow" -v
```

## CI/CD Integration

В GitHub Actions:

```yaml
name: Tests
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.9'

      - name: Install deps
        run: |
          pip install -r requirements-dev.txt

      - name: Run tests
        run: |
          python -m pytest --cov --tb=short

      - name: Upload coverage
        uses: codecov/codecov-action@v3
```

## Performance Optimization

```bash
# Параллельное выполнение (faster)
pip install pytest-xdist
python -m pytest -n auto  # auto = количество CPU cores

# Профилирование (find slow tests)
pip install pytest-profiling
python -m pytest --profile --profile-svg

# Только failed тесты
python -m pytest --lf  # last failed
python -m pytest --ff  # failed first
```

## После запуска тестов

1. Проверь покрытие:
   ```
   Coverage should be 80%+
   ```

2. Если есть failures:
   ```bash
   # Перепроверь конкретный тест
   python -m pytest path/to/test.py::TestClass::test_method -vv
   ```

3. Если всё зелено:
   ```
   ✓ Можешь пушить код
   ✓ Готово для PR review
   ```

## Сообщи результаты

- Total coverage %
- Passed tests count
- Failed tests count (если есть)
- Slow tests (>1s)
