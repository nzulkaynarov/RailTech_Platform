# Safe Database Migration

Безопасно создавай и применяй миграции с проверкой SQL.

## Инструкции

### 1. Проверь наличие неприменённых миграций

```bash
cd backend
python manage.py showmigrations

# Пример вывода:
# accounts
#  [X] 0001_initial
#  [X] 0002_user_role
#  [ ] 0003_user_email_verified  <- неприменённая
```

Если есть неприменённые — примени их первыми:
```bash
python manage.py migrate
```

### 2. Проверь наличие изменений в моделях

```bash
# Покажи, какие изменения ещё не в миграциях
python manage.py makemigrations --dry-run

# Вывод:
# Migrations for 'accounts':
#   accounts/migrations/0004_user_phone.py
#     - Add field phone to user
```

Если есть изменения без миграций:

```bash
# Создай миграции (ОБЯЗАТЕЛЬНО с описанием)
python manage.py makemigrations --name add_phone_to_user
```

### 3. Предварительная проверка SQL

**ОБЯЗАТЕЛЬНО** проверь, что SQL не сломает данные:

```bash
# Смотри SQL миграции
python manage.py sqlmigrate accounts 0004

# Пример вывода:
BEGIN;
--
-- Add field phone to user
--
ALTER TABLE "accounts_user" ADD COLUMN "phone" varchar(20) NULL;
CREATE INDEX "accounts_user_phone_idx" ON "accounts_user" ("phone");
COMMIT;
```

**Проверь:**
- `ALTER TABLE ... ADD COLUMN ... NULL` — безопасно
- `DROP COLUMN` — может потерять данные! Проверь дважды
- `CREATE INDEX` — можно в production, но медленно
- `UNIQUE` constraint без default — может сломать existing records!

### 4. Примени миграцию

```bash
# Apply latest migrations
python manage.py migrate

# Apply конкретное приложение
python manage.py migrate accounts

# Apply конкретную миграцию
python manage.py migrate accounts 0004

# Rollback на N шагов назад
python manage.py migrate accounts 0003
```

### 5. Проверь результат

```bash
# Покажи статус всех миграций
python manage.py showmigrations --list

# Пример вывода (все [X] = применены):
# accounts
#  [X] 0001_initial
#  [X] 0002_user_role
#  [X] 0003_user_email_verified
#  [X] 0004_user_phone
```

### 6. Валидация моделей

```bash
# Проверь, что моделями всё OK
python manage.py check

# С deploy режимом (строже)
python manage.py check --deploy
```

## Типичный Workflow

```bash
# 1. Созданы новые модели или изменены поля
vim accounts/models.py

# 2. Создай миграцию
python manage.py makemigrations --name describe_change

# 3. Предпросмотр SQL
python manage.py sqlmigrate accounts 0004
# ОБЯЗАТЕЛЬНО проверь — безопасно ли?

# 4. Примени
python manage.py migrate

# 5. Проверь статус
python manage.py showmigrations --list

# 6. Валидация
python manage.py check
```

## Проблемные сценарии

### Миграция падает с ошибкой

```bash
# Смотри детали ошибки
python manage.py migrate --verbosity=3

# Если stuck в partial state:
# 1. Проверь текущее состояние БД
python manage.py showmigrations

# 2. Откати вручную (если миграция сломана)
python manage.py migrate accounts 0003  # назад на одну

# 3. Исправь миграцию
vim accounts/migrations/0004_*.py

# 4. Пересоздай (удали сломанную)
rm accounts/migrations/0004_*.py
python manage.py makemigrations --name fixed_version

# 5. Примени заново
python manage.py migrate
```

### Не могу откатить миграцию

```bash
# Зависимость от других миграций
# Сначала откати зависимые:

# Пример: 0005 зависит от 0004
python manage.py migrate sourcing 0003  # откати sourcing
python manage.py migrate accounts 0003   # потом откати accounts

# Потом примени в правильном порядке:
python manage.py migrate accounts 0004
python manage.py migrate sourcing 0005
```

### `makemigrations` не видит изменения

```bash
# 1. Проверь, что файл сохранён
# 2. Проверь, что модель в INSTALLED_APPS
vim core/settings.py

# 3. Попробуй явно указать app
python manage.py makemigrations accounts

# 4. Если всё равно не видит:
python manage.py makemigrations --empty accounts --name manual_migration
# Отредактируй миграцию вручную
```

## Production Considerations

**Перед deploy в production:**

```bash
# 1. Бэкап БД
pg_dump railtech_db > backup_$(date +%Y%m%d).sql

# 2. Тест миграции на копии БД
# (используй backup)

# 3. Примени в staging сначала
# (staging = копия production)

# 4. Проверь production читаемость
# (старый код может запуститься во время миграции)

# 5. Примени в production
python manage.py migrate

# 6. Проверь логи
tail -f /var/log/django.log
```

## Migration Best Practices

```python
# ✓ ХОРОШО — с default значением
python manage.py makemigrations
# Вернёт: Добавляем new_field с default=''

# ✗ ПЛОХО — без default (может сломать существующие записи)
# ALTER TABLE ... ADD COLUMN ... NOT NULL
# (existing records не имеют значения!)

# ✓ ХОРОШО — разделённые миграции
# 1. Добавь column с NULL
# 2. Заполни данные через data migration
# 3. Измени на NOT NULL

# ✓ ХОРОШО — именованные миграции
python manage.py makemigrations --name add_email_verification

# ✗ ПЛОХО — автогенерированные имена
python manage.py makemigrations
# Создаст 0015_auto_20240325_1234.py (неинформативно)
```

## Data Migrations (если нужно)

```bash
# Создай пустую миграцию для обработки данных
python manage.py makemigrations accounts --empty --name populate_phone

# Отредактируй:
```

```python
# accounts/migrations/0005_populate_phone.py
from django.db import migrations

def populate_phone(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    for user in User.objects.all():
        if not user.phone:
            user.phone = '+1234567890'
            user.save()

def reverse_populate_phone(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    User.objects.all().update(phone='')

class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0004_user_phone'),
    ]

    operations = [
        migrations.RunPython(populate_phone, reverse_populate_phone),
    ]
```

## После успешной миграции

```
✓ Все миграции применены (showmigrations все [X])
✓ python manage.py check проходит без ошибок
✓ Django запускается без ошибок
✓ API endpoints работают
✓ Тесты проходят
```

## Сообщи результаты

- Migration name: `accounts/migrations/00XX_name`
- SQL checked: yes/no
- Current status: all applied/pending migrations
- Test results: passed/failed
