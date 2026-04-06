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

4. Создай ViewSet в `{app}/views.py`:

```python
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from core.permissions import IsManagerOrAdmin, IsOwnerOrManagerOrAdmin
from .models import <Model>
from .serializers import <Model>Serializer

class <Model>ViewSet(viewsets.ModelViewSet):
    queryset = <Model>.objects.all()
    serializer_class = <Model>Serializer
    permission_classes = [IsAuthenticated]

    # B2B Multi-tenancy: фильтрация по компании пользователя
    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()

        # Staff (is_staff_level) видят всё
        if user.role and user.role.is_staff_level:
            return qs

        # Остальные — только данные своих компаний
        company_ids = user.memberships.filter(
            is_active=True
        ).values_list('company_id', flat=True)
        return qs.filter(company_id__in=company_ids)

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['created_at']
    search_fields = ['name']
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

## Permissions (из core/permissions.py)

- **IsAuthenticated** — базовый, по умолчанию для всех endpoints
- **IsManagerOrAdmin** — проверяет `user.role.is_staff_level` (SystemRole с флагом staff)
- **IsAdminUser** — проверяет `user.role.code == 'ADMIN'`
- **IsAdminOrReadOnly** — safe methods всем, write только админам
- **IsOwnerOrManagerOrAdmin** — object-level, проверяет через CompanyMember memberships

**Multi-tenancy:** Фильтруй queryset по `user.memberships` (CompanyMember join table), не по `user.company` напрямую.

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
   - ViewSet: `{app}/views.py`
   - Tests: `{app}/tests/test_viewsets.py`
