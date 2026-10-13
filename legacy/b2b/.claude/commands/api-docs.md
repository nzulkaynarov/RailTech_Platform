# Generate API Documentation

Генерируй и обновляй API документацию с Swagger/OpenAPI.

## Инструкции

### 1. Проверь, что drf-spectacular установлен

```bash
cd backend

# Должен быть в requirements.txt
grep drf-spectacular requirements.txt

# Если нет — установи
pip install drf-spectacular

# Проверь, что в INSTALLED_APPS
grep 'drf_spectacular' core/settings.py
```

### 2. Конфигурация в settings.py

```python
# core/settings.py

INSTALLED_APPS = [
    # ...
    'drf_spectacular',
    'rest_framework',
    # ...
]

REST_FRAMEWORK = {
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'RailTech API',
    'DESCRIPTION': 'B2B Railway Commerce Platform',
    'VERSION': '1.0.0',
    'CONTACT': {'email': 'api@railtech.com'},
    'LICENSE': {'name': 'MIT'},
    'SERVERS': [
        {'url': 'http://localhost:8000', 'description': 'Development'},
        {'url': 'https://api.railtech.com', 'description': 'Production'},
    ],
    'SCHEMA_PATH_PREFIX': '/api/v[0-9]/',
    'PREPROCESSING_HOOKS': [
        'core.utils.preprocessing_filter_hook',
    ],
}
```

### 3. Зарегистрируй endpoints в urls.py

```python
# core/urls.py

from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularReDocView

urlpatterns = [
    # API schema endpoints
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/schema/swagger/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/schema/redoc/', SpectacularReDocView.as_view(url_name='schema'), name='redoc'),

    # API routes
    path('api/', include(router.urls)),
]
```

### 4. Добавь descriptions к ViewSets

**ОБЯЗАТЕЛЬНО** документируй каждый ViewSet и метод:

```python
# accounts/viewsets.py

from rest_framework import viewsets
from .serializers import UserSerializer
from .models import User

class UserViewSet(viewsets.ModelViewSet):
    """
    API endpoint для управления пользователями.

    list: Получить список всех пользователей (с фильтрацией).
    create: Создать нового пользователя.
    retrieve: Получить деталь пользователя по ID.
    update: Обновить пользователя полностью (PUT).
    partial_update: Обновить часть данных пользователя (PATCH).
    destroy: Удалить пользователя.
    """

    queryset = User.objects.all()
    serializer_class = UserSerializer

    def create(self, request, *args, **kwargs):
        """
        Создать нового пользователя.

        Request body:
        {
            "email": "user@example.com",
            "first_name": "John",
            "last_name": "Doe",
            "role": "CLIENT",
            "company": 1
        }

        Response 201:
        {
            "id": 1,
            "email": "user@example.com",
            "first_name": "John",
            "last_name": "Doe",
            "role": "CLIENT",
            "company": 1,
            "created_at": "2024-03-25T10:00:00Z"
        }
        """
        return super().create(request, *args, **kwargs)
```

### 5. Добавь descriptions к Serializers

```python
# accounts/serializers.py

from rest_framework import serializers
from .models import User

class UserSerializer(serializers.ModelSerializer):
    """
    Serializer для User модели.

    Fields:
    - id (int): уникальный ID пользователя (read-only)
    - email (str): email пользователя (unique, required)
    - first_name (str): имя пользователя
    - last_name (str): фамилия пользователя
    - role (str): роль пользователя (GUEST, CLIENT, SALES_MANAGER, ACCOUNT_MANAGER, ADMIN)
    - company (int): ID компании (required)
    - created_at (datetime): дата создания (read-only)
    - updated_at (datetime): дата обновления (read-only)
    """

    class Meta:
        model = User
        fields = [
            'id',
            'email',
            'first_name',
            'last_name',
            'role',
            'company',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
```

### 6. Генерируй OpenAPI schema

```bash
# Вариант 1: Download JSON schema
curl http://localhost:8000/api/schema/ > openapi-schema.json

# Вариант 2: Через management command
python manage.py spectacular --file schema.yaml

# Вариант 3: Через Django command
python manage.py spectacular --format openapi-json > api.json
```

### 7. Посмотри документацию

```bash
# Swagger UI (интерактивный)
open http://localhost:8000/api/schema/swagger/

# ReDoc (красивый и читаемый)
open http://localhost:8000/api/schema/redoc/

# Raw JSON
open http://localhost:8000/api/schema/
```

## Список всех endpoints

```bash
# Получи полный список зарегистрированных endpoints
python manage.py spectacular --list

# Пример вывода:
# GET    /api/accounts/
# POST   /api/accounts/
# GET    /api/accounts/{id}/
# PUT    /api/accounts/{id}/
# PATCH  /api/accounts/{id}/
# DELETE /api/accounts/{id}/
# GET    /api/quotes/
# POST   /api/quotes/
# ...
```

## Проверка coverage

```bash
# Убедись, что ВСЕ endpoints документированы
python manage.py spectacular --check

# Должно быть 0 ошибок
# Если есть:
# - Добавь docstrings к ViewSets
# - Добавь descriptions к Serializers
# - Проверь фильтры и действия
```

## API Documentation Best Practices

```python
# ✓ ХОРОШО — подробная документация
class QuoteViewSet(viewsets.ModelViewSet):
    """
    Управление коммерческими предложениями (quotes).

    list: Получить все quotes (с фильтром по статусу и компании)
    create: Создать новый quote (требует CLIENT или выше роль)
    retrieve: Получить деталь quote по ID
    update: Обновить quote (только если статус DRAFT)
    partial_update: Обновить часть quote
    destroy: Удалить quote (только если статус DRAFT)

    Query parameters:
    - status: фильтр по статусу (DRAFT, SENT, APPROVED, REJECTED)
    - company: фильтр по компании
    - created_from: фильтр по дате создания (от)
    - created_to: фильтр по дате создания (до)
    - ordering: сортировка (created_at, amount, status)

    Permissions:
    - GUEST: только список публичных quotes
    - CLIENT: только свои quotes
    - SALES_MANAGER: quotes своей компании
    - ADMIN: все quotes
    """

# ✗ ПЛОХО — нет документации
class QuoteViewSet(viewsets.ModelViewSet):
    pass
```

## Примеры в OpenAPI

```python
# Добавь примеры для requests/responses
from drf_spectacular.utils import extend_schema, OpenApiExample

@extend_schema(
    examples=[
        OpenApiExample(
            'Valid example',
            value={
                'name': 'Q-2024-001',
                'status': 'DRAFT',
                'amount': '1500.00',
                'company': 1,
            },
        ),
    ],
)
def create(self, request, *args, **kwargs):
    """Создание нового quote"""
    return super().create(request, *args, **kwargs)
```

## Версионирование API

```python
# core/urls.py

# Если используешь versioning
from rest_framework.routers import DefaultRouter

router_v1 = DefaultRouter()
router_v1.register(r'accounts', AccountViewSet)
router_v1.register(r'quotes', QuoteViewSet)

urlpatterns = [
    path('api/v1/', include(router_v1.urls)),
]

# Обнови SPECTACULAR_SETTINGS
SPECTACULAR_SETTINGS = {
    'VERSION': '1.0.0',
    'SCHEMA_PATH_PREFIX': '/api/v[0-9]+',
}
```

## Export Formats

```bash
# YAML
python manage.py spectacular --file schema.yaml

# JSON
python manage.py spectacular --format openapi-json > schema.json

# YAML с разбором по файлам
python manage.py spectacular --target-file schema.yaml --format yaml
```

## Интеграция с внешними сервисами

```bash
# Swagger Editor (онлайн)
# https://editor.swagger.io/
# Copy-paste содержимое openapi-schema.json

# Postman (импорт OpenAPI)
# 1. File > Import > Paste raw text
# 2. Вставь содержимое openapi-schema.json

# Insomnia (импорт OpenAPI)
# 1. Create > Import from URL
# 2. Вставь URL: http://localhost:8000/api/schema/
```

## CI/CD: Автоматическая генерация

```bash
# .github/workflows/api-docs.yml
name: Generate API Docs

on: [push]

jobs:
  docs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.9'

      - run: pip install -r requirements.txt
      - run: python manage.py spectacular --file docs/schema.json
      - run: git add docs/schema.json && git commit -m "docs: update API schema"
      - run: git push
```

## После генерации

1. Проверь Swagger UI:
   ```bash
   http://localhost:8000/api/schema/swagger/
   ```

2. Попробуй API в Swagger:
   - Click на endpoint
   - Нажми Try it out
   - Заполни параметры
   - Нажми Execute

3. Проверь описания:
   - Все endpoints задокументированы
   - Все fields описаны
   - Примеры есть (если нужно)

4. Сохрани schema для production:
   ```bash
   python manage.py spectacular --file docs/schema.json
   git add docs/schema.json
   git commit -m "docs: update API schema"
   ```

## Сообщи результаты

- Schema generated: JSON/YAML
- Swagger UI available: yes/no
- ReDoc available: yes/no
- All endpoints documented: XX/XX
- Test coverage in Swagger: passed/failed
