# New DRF Endpoint

Создай новый DRF ViewSet с Serializer и регистрацией в роутере.

## Аргументы

$ARGUMENTS — название модели. Примеры:
- `Quote` — создаст QuoteViewSet, QuoteSerializer
- `PurchaseOrder` — создаст PurchaseOrderViewSet, PurchaseOrderSerializer

## Инструкции

1. Определи приложение (app):
   - Для каталога: `catalog`
   - Для CRM: `crm`
   - Для закупок: `sourcing`
   - Для мастер-данных: `master_data`
   - Для уведомлений: `notifications`
   - Для аккаунтов: `accounts`

2. Проверь модель существует в `{app}/models.py`
   - Если нет — используй команду `new-model`

3. Создай Serializer в `{app}/serializers.py`:

```python
from rest_framework import serializers
from .models import <Model>

class <Model>Serializer(serializers.ModelSerializer):
    class Meta:
        model = <Model>
        fields = [
            'id',
            'created_at',
            'updated_at',
            # ... другие поля
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
```

4. Создай ViewSet в `{app}/viewsets.py`:

```python
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from .models import <Model>
from .serializers import <Model>Serializer

class <Model>ViewSet(viewsets.ModelViewSet):
    queryset = <Model>.objects.all()
    serializer_class = <Model>Serializer
    permission_classes = [IsAuthenticated]

    # Фильтрация по роли пользователя
    def get_queryset(self):
        user = self.request.user
        qs = <Model>.objects.all()

        # GUEST — доступ только к публичным данным
        if user.role == 'GUEST':
            return qs.filter(is_public=True)

        # CLIENT — только свои данные
        if user.role == 'CLIENT':
            return qs.filter(company=user.company)

        # SALES_MANAGER/ACCOUNT_MANAGER — все в рамках компании
        if user.role in ['SALES_MANAGER', 'ACCOUNT_MANAGER']:
            return qs.filter(company=user.company)

        # ADMIN — все
        return qs

    # Пагинация и фильтрация
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['status', 'created_at']
    search_fields = ['name', 'code']
    ordering_fields = ['created_at', 'name']
    ordering = ['-created_at']
```

5. Зарегистрируй в `core/urls.py`:

```python
from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from {app}.viewsets import <Model>ViewSet

router = DefaultRouter()
router.register(r'<models-lowercase>', <Model>ViewSet)

urlpatterns = [
    path('api/', include(router.urls)),
]
```

6. Создай тесты в `{app}/tests/test_viewsets.py`:

```python
from rest_framework.test import APITestCase
from rest_framework import status
from {app}.models import <Model>

class <Model>ViewSetTests(APITestCase):
    def setUp(self):
        self.user = create_test_user('CLIENT')
        self.client.force_authenticate(user=self.user)

    def test_list(self):
        response = self.client.get('/api/<models-lowercase>/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_create(self):
        data = {
            'name': 'Test',
            # ... другие поля
        }
        response = self.client.post('/api/<models-lowercase>/', data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_permissions(self):
        # Убедись, что GUEST не может создавать
        guest = create_test_user('GUEST')
        self.client.force_authenticate(user=guest)
        response = self.client.post('/api/<models-lowercase>/', {})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
```

## Роли и Permissions

**GUEST** — только чтение публичных данных
- `AllowAny` для list/retrieve публичных
- `403` для create/update/delete

**CLIENT** — работа со своей компанией
- `IsAuthenticated` + фильтр по company

**SALES_MANAGER** — работа с квотами и трейдами
- Полный доступ к данным своей компании
- `IsAuthenticated` + фильтр по company

**ACCOUNT_MANAGER** — работа с аккаунтами
- Полный доступ к данным своего аккаунта
- `IsAuthenticated` + фильтр по account

**ADMIN** — полный доступ
- `IsAdminUser`

## Пагинация и Фильтрация

```python
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter

class StandardResultsSetPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
```

## После создания

1. Запусти тесты:
   ```bash
   cd backend && python -m pytest {app}/tests/test_viewsets.py -v
   ```

2. Проверь API документацию:
   ```bash
   curl http://localhost:8000/api/schema/
   ```

3. Протестируй в Swagger UI:
   - Перейди на http://localhost:8000/api/
   - Найди новый endpoint
   - Протестируй GET, POST, PUT, DELETE

4. Сообщи путь к созданным файлам:
   - Serializer: `{app}/serializers.py`
   - ViewSet: `{app}/viewsets.py`
   - Tests: `{app}/tests/test_viewsets.py`
