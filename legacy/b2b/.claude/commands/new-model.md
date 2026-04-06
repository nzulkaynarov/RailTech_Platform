# New Django Model

Создай новую Django модель с аудитом, индексами и admin регистрацией.

## Аргументы

$ARGUMENTS — название модели и приложение. Примеры:
- `Quote catalog` — создаст Quote в catalog
- `PurchaseOrder sourcing` — создаст PurchaseOrder в sourcing

## Инструкции

1. Определи поля модели:
   - Основные: CharField, IntegerField, DecimalField, ForeignKey, ManyToManyField
   - Статусы: используй choices (ChoiceField)
   - Даты: DateTimeField с auto_now_add, auto_now
   - Бизнес-логика: validators, properties

2. Создай модель в `{app}/models.py`:

```python
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinValueValidator
from accounts.models import CustomUser, Company

class <Model>(models.Model):
    # Основные поля
    name = models.CharField(max_length=255, db_index=True, verbose_name=_("Название"))
    code = models.CharField(max_length=50, unique=True, verbose_name=_("Код"))
    description = models.TextField(blank=True, default='', verbose_name=_("Описание"))

    # Внешние ключи
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name='+')

    # Статус — используй FK на lookup-таблицу (см. master_data.AbstractLookup)
    # или choices для простых случаев
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])

    # Даты (определяй явно — AuditMixin не существует в проекте)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['company', 'created_at']),
            models.Index(fields=['code']),
        ]
        constraints = [
            models.UniqueConstraint(fields=['company', 'code'], name='<model_lower>_unique_per_company'),
        ]
        verbose_name = '<Model>'
        verbose_name_plural = '<Models>'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.code})"
```

**Для справочных таблиц** (статусы, типы) наследуй `AbstractLookup` из `master_data.models`:
```python
from master_data.models import AbstractLookup

class <MyStatus>(AbstractLookup):
    """Наследует: code (unique), name, sort_order, is_active"""
    class Meta(AbstractLookup.Meta):
        verbose_name = '<MyStatus>'
```

3. Создай ModelSerializer в `{app}/serializers.py`:

```python
from rest_framework import serializers
from .models import <Model>

class <Model>Serializer(serializers.ModelSerializer):
    company_name = serializers.CharField(source='company.name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.full_name', read_only=True)

    class Meta:
        model = <Model>
        fields = [
            'id',
            'name',
            'code',
            'description',
            'company',
            'company_name',
            'created_by',
            'created_by_name',
            'status',
            'amount',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']
        extra_kwargs = {
            'code': {'required': True},
            'company': {'required': True},
        }

    def validate_code(self, value):
        """Валидация кода — должен быть уникален в компании"""
        instance = self.instance
        qs = <Model>.objects.filter(code=value, company=self.initial_data.get('company'))

        if instance:
            qs = qs.exclude(id=instance.id)

        if qs.exists():
            raise serializers.ValidationError("Code must be unique within company")
        return value
```

4. Зарегистрируй в admin в `{app}/admin.py`:

```python
from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import <Model>

@admin.register(<Model>)
class <Model>Admin(ModelAdmin):
    list_display = ['name', 'code', 'company', 'status', 'created_at']
    list_filter = ['status', 'company', 'created_at']
    search_fields = ['name', 'code']
    readonly_fields = ['id', 'created_at', 'updated_at', 'created_by']

    fieldsets = (
        ('Основное', {
            'fields': ('name', 'code', 'company', 'description')
        }),
        ('Статус', {
            'fields': ('status', 'amount')
        }),
        ('Аудит', {
            'fields': ('id', 'created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def save_model(self, request, obj, form, change):
        if not change:  # новый объект
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
```

5. Создай миграцию:

```bash
cd backend
python manage.py makemigrations {app}
```

6. Проверь сгенерированный SQL:

```bash
python manage.py sqlmigrate {app} 0001_initial
```

7. Примени миграцию:

```bash
python manage.py migrate {app}
```

8. Проверь статус:

```bash
python manage.py showmigrations {app}
```

## Базовые классы

- **Обычные модели** — определяй `created_at`/`updated_at` явно (нет AuditMixin в проекте)
- **Справочники (lookup)** — наследуй `master_data.models.AbstractLookup` (поля: code, name, sort_order, is_active)
- **Пользователь** — `accounts.models.CustomUser` (не `User`), email как USERNAME_FIELD
- **Компания** — `accounts.models.Company`

## Индексы и Constraints

**Индексы создавай для:**
- Часто используемые в фильтрах (status, company, created_at)
- Поля для сортировки
- Внешние ключи

**Constraints создавай для:**
- Уникальные поля или комбинации
- Бизнес-логика (например, уникальность в рамках компании)

## Типы полей

- **CharField** — `max_length` обязателен
- **DecimalField** — `max_digits` и `decimal_places` для денег (12, 2)
- **ForeignKey** — `on_delete=models.CASCADE` или `SET_NULL`
- **DateTimeField** — используй `auto_now_add=True` для создания, `auto_now=True` для обновления
- **JSONField** — для гибких структур данных

## После создания

1. Запусти миграции:
   ```bash
   cd backend && python manage.py migrate
   ```

2. Создай тесты в `{app}/tests/test_models.py`:
   ```python
   from django.test import TestCase
   from {app}.models import <Model>

   class <Model>Tests(TestCase):
       def test_model_creation(self):
           obj = <Model>.objects.create(
               name='Test',
               code='TEST-001',
               company=self.company,
           )
           self.assertEqual(obj.name, 'Test')
   ```

3. Запусти тесты:
   ```bash
   python -m pytest {app}/tests/test_models.py -v
   ```

4. Проверь в admin:
   - Перейди на http://localhost:8000/admin/
   - Убедись, что модель регистрирована
   - Создай тестовый объект

5. Сообщи путь к созданным файлам:
   - Model: `{app}/models.py`
   - Serializer: `{app}/serializers.py`
   - Admin: `{app}/admin.py`
   - Migration: `{app}/migrations/XXXX_*.py`
