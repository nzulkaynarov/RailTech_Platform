# New Django Model

Создай новую Django-модель по живым конвенциям проекта.

## Аргументы

$ARGUMENTS — название модели и приложение, например: `PurchaseOrder crm`.

## Главный принцип: повторяй за свежим соседом

1. Найди последнюю добавленную модель в целевом app и возьми её за образец:

   ```bash
   git log --oneline --diff-filter=A -10 -- backend/<app>/models/
   ls backend/<app>/models/
   ```

   В `crm`/`accounts`/`catalog` модели лежат **пакетами** `models/` (не плоским `models.py`) — новый домен = новый файл в пакете + экспорт в `__init__.py`.
2. Прочитай образец: поля, Meta, индексы, constraints, как оформлены FK.

## Обязательные инварианты

- **FK внутри app — строковыми ссылками** `"app.Model"` (пакеты models/ этого требуют).
- **Статусы/типы — FK на lookup** (`AbstractLookup` из master_data: code, name, sort_order, is_active), НЕ choices-строки. Логика сравнивает по `code`.
- **Rule 1 (seed = data migrations)**: коды lookup-строк сеются `migrations.RunPython` c `get_or_create` и reverse no-op — в той же ветке, что и модель. В горячем коде — только `Model.objects.get(code=...)`.
- **Деньги** — `DecimalField`, даты — `created_at`/`updated_at` явно (AuditMixin в проекте нет), индексы на поля фильтров.
- **Admin (Unfold)** — только регистрация для инженеров: списки, фильтры, readonly. НИКАКИХ `@admin.action` с бизнес-логикой (ADR-0001, Rule 8) — бизнес-операции = React Admin + DRF endpoint.

## Миграции — только через Docker

```bash
make makemigrations
make migrate
# Celery НЕ перечитывает код сам:
docker compose restart celery-worker celery-beat
```

Перед мержем сверь головы миграций с CLAUDE.md (секция Database) — параллельная ветка могла занять номер.

## После кода

1. Тесты моделей — в стиле соседних (`backend/<app>/tests/`), прогон: `docker compose exec backend pytest <app>/tests/ -v`.
2. Если модель попадает в сериализаторы — **регенерируй api-contract** (schema.json + `npm run gen:api-types`), иначе CI-гейт упадёт. Это касается даже правки `verbose_name`.
3. Сообщи: файл модели, номер миграции, какие lookup-коды посеяны.
