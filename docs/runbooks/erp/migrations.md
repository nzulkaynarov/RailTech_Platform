# Миграции базы данных и начальные справочники ERP

## Когда применять

- Изменение моделей данных (`models/`) в приложениях `core`, `parties`, `accounts`, `catalog`, `sales`, `finance`, `documents`, `ai`, `sourcing`.
- Ошибка CI: `makemigrations --check` обнаружил расхождение между кодом моделей и файлами миграций.
- Развёртывание новой версии стенда или прода: применение изменений схемы (`python manage.py migrate`).
- Инициализация чистой базы данных: первичное засевание системных справочников, ролей и курсов валют.
- Необходимость безопасного отката миграции в случае выявления дефектов.

---

## Архитектурные правила и инварианты

1. **Словари сеются миграциями** (docs/systems/erp/CONVENTIONS.md §5):
   Каждая миграция, создающая справочную таблицу, содержит вызов `migrations.RunPython(seed_func, reverse_code=migrations.RunPython.noop)` с методом `get_or_create`.
   После выполнения `python manage.py migrate` на абсолютно пустой базе каждый код (стадии, статусы, базисы поставки, валюты, системные роли) уже существует в БД.
2. **Линейность и отсутствие циклов**:
   Миграции не должны содержать циклических зависимостей между приложениями. Порядок связей строго фиксируется списком `dependencies`.
3. **Безопасность для работающего прода**:
   Не допускается удаление или переименование полей без предварительного переходного периода (nullable/deprecated).

---

## Диагностика

| Команда | Ожидаемая норма | Признак проблемы |
|---|---|---|
| `python manage.py showmigrations` | Все миграции помечены флагом `[X]` | Есть непомеченные строки `[ ]` (неприменённые миграции) |
| `python manage.py makemigrations --check --dry-run` | `No changes detected` (код возврата 0) | Сообщение `Migrations for '...':` и ненулевой код возврата |
| `python manage.py sqlmigrate <app> <name>` | Корректный DDL SQL без блокирующих операций `DROP TABLE` | Ошибки синтаксиса или недопустимые блокировки |

---

## Порядок действий

### 1. Создание новой миграции при изменении моделей
1. Перейдите в каталог бэкенда:
   ```bash
   cd apps/erp/backend
   ```
2. Сгенерируйте файл миграции с осмысленным именем:
   ```bash
   python manage.py makemigrations <app_name> --name <descriptive_slug>
   ```
3. Если модель требует предустановленных записей, откройте созданный файл и добавьте функцию засевания:
   ```python
   def seed_defaults(apps, schema_editor):
       Model = apps.get_model('<app_name>', '<ModelName>')
       Model.objects.get_or_create(code='CODE', defaults={'name': 'Name', 'is_active': True})

   class Migration(migrations.Migration):
       ...
       operations = [
           ...,
           migrations.RunPython(seed_defaults, reverse_code=migrations.RunPython.noop),
       ]
   ```
4. Убедитесь в отсутствии пропущенных изменений:
   ```bash
   python manage.py makemigrations --check --dry-run
   ```

### 2. Применение миграций на локальном стенде
1. Из корня репозитория выполните команду через контейнер бэкенда:
   ```bash
   make -C apps/erp migrate
   ```
   Или напрямую через docker compose:
   ```bash
   docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env exec erp-backend python manage.py migrate --noinput
   ```

### 3. Начальное засевание данных и ролей бэк-офиса
На чистом стенде базовые роли и справочники поднимаются автоматически миграциями. Для гарантированной синхронизации системных ролей и компании-владельца выполните:
```bash
docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env exec erp-backend python manage.py shell -c "
from accounts.models import ensure_default_company_roles
from core.tenant import own_company
comp = own_company()
if comp:
    ensure_default_company_roles(comp)
print('Roles synced successfully')
"
```

### 4. ⚠️ Откат миграции назад
Если свежая миграция вызвала дефект:
1. Выясните имя стабильной предшествующей миграции через `python manage.py showmigrations <app_name>`.
2. Выполните откат схемы к предыдущему номеру:
   ```bash
   docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env exec erp-backend python manage.py migrate <app_name> <previous_migration_name>
   ```
3. Удалите проблемный файл миграции из рабочей копии.

---

## Проверка восстановления

1. `python manage.py showmigrations` показывает `[X]` для всех активных миграций.
2. `docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env exec erp-backend python manage.py migrate --check` завершается с кодом 0, а `curl http://erp.localhost/health/` отвечает 200 (`"database": "up"`).
3. Тесты бэкенда проходят без ошибок:
   ```bash
   make -C apps/erp test
   ```

---

## Эскалация

При падении команды `migrate` с ошибками целостности схемы (`InconsistentMigrationHistory`, `NodeNotFoundError`, `IntegrityError`):
1. Снимите снимок журнала: `python manage.py showmigrations`.
2. Получите полный трейсбек ошибки применения миграции.
3. Обратитесь к ведущему бэкенд-разработчику для ручной правки графа зависимостей миграций.
