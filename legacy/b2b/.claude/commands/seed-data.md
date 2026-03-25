# Load Seed Data

Загрузи development seed-данные и создай тестовых пользователей.

## Инструкции

### 1. Проверь наличие данных в БД

```bash
cd backend

# Проверь, пустая ли БД
python manage.py shell

# В shell:
from accounts.models import User, Company
from catalog.models import Product
from crm.models import Quote

print(f"Users: {User.objects.count()}")
print(f"Companies: {Company.objects.count()}")
print(f"Products: {Product.objects.count()}")
print(f"Quotes: {Quote.objects.count()}")

# Если all = 0, значит пустая БД
exit()
```

### 2. Загрузи seed-данные из JSON

```bash
# Если есть seed файл
python manage.py loaddata core/data/seed_data.json

# Или для конкретного приложения
python manage.py loaddata accounts/fixtures/users.json
python manage.py loaddata catalog/fixtures/products.json

# Проверь результат
python manage.py shell
from accounts.models import User
print(f"Users after seed: {User.objects.count()}")
exit()
```

### 3. Создай тестовых пользователей для каждой роли

```bash
cd backend && python manage.py shell
```

```python
from accounts.models import User, Company
from django.utils import timezone

# Убедись, что нет существующих тестовых пользователей
User.objects.filter(email__startswith='test_').delete()
Company.objects.filter(name='Test Company').delete()

# 1. Создай тестовую компанию
company = Company.objects.create(
    name='Test Company',
    code='TEST',
    email='company@test.railtech.com',
    phone='+1-234-567-8900',
    country='US',
    industry='RAIL',
)

# 2. Создай пользователей для каждой роли
test_users = {
    'GUEST': ('guest@test.railtech.com', 'Test', 'Guest'),
    'CLIENT': ('client@test.railtech.com', 'Test', 'Client'),
    'SALES_MANAGER': ('sales@test.railtech.com', 'Test', 'SalesManager'),
    'ACCOUNT_MANAGER': ('account@test.railtech.com', 'Test', 'AccountManager'),
    'ADMIN': ('admin@test.railtech.com', 'Test', 'Admin'),
}

test_password = 'TestPassword123!'

for role, (email, first_name, last_name) in test_users.items():
    user = User.objects.create_user(
        email=email,
        password=test_password,
        first_name=first_name,
        last_name=last_name,
        phone='+1-234-567-8901',
        company=company,
        role=role,
        is_active=True,
    )
    if role == 'ADMIN':
        user.is_staff = True
        user.is_superuser = True
        user.save()

    print(f"✓ Created {role} user: {email}")

# 3. Выведи учётные данные
print("\n=== TEST USERS ===")
for email, first_name, last_name in test_users.values():
    print(f"{email} / {test_password}")

exit()
```

### 4. Создай sample продуктов (если используешь catalog)

```bash
python manage.py shell
```

```python
from catalog.models import Product, Category
from django.utils import timezone

# Очисти существующие
Product.objects.all().delete()
Category.objects.all().delete()

# Создай категории
categories = {
    'RAIL': Category.objects.create(
        name='Rail Components',
        code='RAIL',
        is_active=True,
    ),
    'WHEELS': Category.objects.create(
        name='Wheels',
        code='WHEELS',
        is_active=True,
    ),
    'BEARINGS': Category.objects.create(
        name='Bearings',
        code='BEARINGS',
        is_active=True,
    ),
}

# Создай продукты
products_data = [
    ('Standard Rail 60kg/m', 'RAIL-60', 'RAIL', 150.00),
    ('Standard Rail 80kg/m', 'RAIL-80', 'RAIL', 200.00),
    ('Heavy Rail 100kg/m', 'RAIL-100', 'RAIL', 250.00),
    ('Wheel 860mm', 'WHEEL-860', 'WHEELS', 500.00),
    ('Wheel 920mm', 'WHEEL-920', 'WHEELS', 550.00),
    ('Bearing SKF 6206', 'BEARING-6206', 'BEARINGS', 45.00),
    ('Bearing FAG 6307', 'BEARING-6307', 'BEARINGS', 60.00),
]

for name, code, category_code, price in products_data:
    Product.objects.create(
        name=name,
        code=code,
        category=categories[category_code],
        price=price,
        unit='PIECE',
        is_active=True,
    )
    print(f"✓ Created product: {code}")

exit()
```

### 5. Создай sample quotes (CRM)

```bash
python manage.py shell
```

```python
from crm.models import Quote, QuoteLineItem
from catalog.models import Product
from accounts.models import User, Company
from django.utils import timezone

# Очисти существующие
Quote.objects.all().delete()

# Получи test компанию и пользователя
company = Company.objects.get(code='TEST')
sales_user = User.objects.get(email='sales@test.railtech.com')

# Создай quotes
for i in range(5):
    quote = Quote.objects.create(
        number=f'Q-2024-{1000+i}',
        company=company,
        created_by=sales_user,
        status='DRAFT' if i < 3 else 'SENT',
        total_amount=1000.00 + (i * 500),
        expiry_date=timezone.now() + timezone.timedelta(days=30),
    )

    # Добавь line items
    products = Product.objects.all()[:2]
    for j, product in enumerate(products):
        QuoteLineItem.objects.create(
            quote=quote,
            product=product,
            quantity=10 + (i * 2),
            unit_price=product.price,
            total_price=product.price * (10 + (i * 2)),
        )

    print(f"✓ Created quote: {quote.number}")

exit()
```

## Seed Data Structure

```
core/data/
├── seed_data.json (если есть общий dump)
└── seed_data.sql (если используешь SQL)

accounts/fixtures/
├── users.json
└── companies.json

catalog/fixtures/
├── products.json
└── categories.json

crm/fixtures/
├── quotes.json
└── quote_items.json
```

## Пример seed_data.json

```json
{
  "companies": [
    {
      "model": "accounts.company",
      "pk": 1,
      "fields": {
        "name": "Test Company",
        "code": "TEST",
        "email": "company@test.railtech.com",
        "phone": "+1-234-567-8900",
        "country": "US"
      }
    }
  ],
  "users": [
    {
      "model": "accounts.user",
      "pk": 1,
      "fields": {
        "email": "admin@test.railtech.com",
        "password": "pbkdf2_sha256$...",
        "first_name": "Admin",
        "last_name": "User",
        "role": "ADMIN",
        "company": 1,
        "is_active": true,
        "is_staff": true,
        "is_superuser": true
      }
    }
  ]
}
```

## Сохранение seed data

```bash
# Дамп всех данных
python manage.py dumpdata > core/data/seed_data.json

# Дамп конкретного app
python manage.py dumpdata accounts > accounts/fixtures/users.json

# Дамп конкретной модели
python manage.py dumpdata accounts.user > fixtures/users.json

# Без индентации для production
python manage.py dumpdata --indent=0 > seed_data.json
```

## Утилиты для seed data

```python
# core/management/commands/create_test_data.py

from django.core.management.base import BaseCommand
from accounts.models import User, Company
from django.utils import timezone

class Command(BaseCommand):
    help = 'Load test/seed data for development'

    def handle(self, *args, **options):
        self.stdout.write('Loading seed data...')

        # Удали существующие тестовые данные
        User.objects.filter(email__startswith='test_').delete()
        Company.objects.filter(name='Test').delete()

        # Создай company
        company = Company.objects.create(
            name='Test Company',
            code='TEST',
        )
        self.stdout.write(f'✓ Created company: {company.name}')

        # Создай users
        for role in ['GUEST', 'CLIENT', 'SALES_MANAGER', 'ACCOUNT_MANAGER', 'ADMIN']:
            user = User.objects.create_user(
                email=f'{role.lower()}@test.railtech.com',
                password='TestPassword123!',
                role=role,
                company=company,
            )
            self.stdout.write(f'✓ Created user: {user.email} ({role})')

        self.stdout.write(self.style.SUCCESS('Seed data loaded successfully'))
```

Использование:

```bash
python manage.py create_test_data
```

## Проверка load

```bash
# После загрузки проверь
python manage.py shell

from accounts.models import User, Company
print(f"Companies: {Company.objects.count()}")
print(f"Users: {User.objects.count()}")

# Проверь конкретного пользователя
user = User.objects.get(email='admin@test.railtech.com')
print(f"User: {user.email}, Role: {user.role}")

# Проверь пароль
user.check_password('TestPassword123!')  # True

exit()
```

## Seed Data для разных окружений

```python
# core/settings.py

if DEBUG:
    # Dev seed data
    SEED_DATA_FILE = 'core/data/seed_dev.json'
    TEST_USERS = {
        'admin': 'admin@test.railtech.com',
        'client': 'client@test.railtech.com',
    }
else:
    # Production (не используй автоматически!)
    SEED_DATA_FILE = None
    TEST_USERS = {}
```

## После загрузки seed data

1. Проверь пользователей:
   ```bash
   python manage.py shell
   from accounts.models import User
   for u in User.objects.all():
       print(f"{u.email} ({u.role})")
   exit()
   ```

2. Логинься в admin:
   ```bash
   # http://localhost:8000/admin/
   # admin@test.railtech.com / TestPassword123!
   ```

3. Проверь API:
   ```bash
   curl http://localhost:8000/api/products/
   curl http://localhost:8000/api/quotes/
   ```

4. Тестируй в Swagger:
   ```bash
   http://localhost:8000/api/schema/swagger/
   # Авторизуйся и попробуй endpoints
   ```

## Сообщи результаты

```
✓ Seed data loaded
✓ Test users created:
  - admin@test.railtech.com (ADMIN)
  - sales@test.railtech.com (SALES_MANAGER)
  - client@test.railtech.com (CLIENT)
  - guest@test.railtech.com (GUEST)
  - account@test.railtech.com (ACCOUNT_MANAGER)

✓ Sample data:
  - X companies
  - X users
  - X products
  - X quotes

Ready for testing!
```
