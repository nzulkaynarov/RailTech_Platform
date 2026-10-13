# New DRF Endpoint

Создай новый DRF endpoint по живым конвенциям проекта.

## Аргумент

$ARGUMENTS — что за endpoint (модель/действие), например: `Quote reject`, `PurchaseOrder CRUD`.

## Главный принцип: шаблонов нет — есть свежий сосед

Кодовая база движется быстро, застывшие шаблоны в этом файле протухали и порождали нарушения Rule 8. Поэтому:

1. **Найди самый свежий похожий endpoint** в целевом app и возьми его за образец:

   ```bash
   git log --oneline -15 -- backend/<app>/views/ backend/<app>/services/
   ls -t backend/<app>/views/ backend/<app>/services/
   ```

2. **Прочитай образец целиком**: view + его service + serializer + регистрацию URL + его тест-файл. Структура нового кода = структура образца.

## Обязательные инварианты (проверь, что образец им следует, и следуй сам)

- **Rule 8**: ViewSet/@action — тонкая обёртка: authorize → validate → ОДИН вызов функции из `<app>/services/` → return. Вся логика (переходы, side effects, письма, Celery) — в сервисе.
- **Ошибки**: только `{"detail": "<CODE>"}` (константа-код, фронт сравнивает по значению). Никогда `{"error": ...}`.
- **Tenancy**: queryset scoped — продавец через `seller_visible_deal_ids`, компания через `CompanyMember` memberships. НЕ `user.company`.
- **Гейты в сервисе**: KYC floor, entitlement (`accounts/services/entitlements.py`), capability `can_buy`/`can_sell`, `is_platform_admin_viewer` → `ADMIN_VIEWER_CANNOT_ACT`.
- **Списки**: `select_related`/`prefetch_related`, пагинация, фильтры — как у соседа.
- **AI**: если endpoint дергает LLM — ТОЛЬКО `enqueue_ai_job(...)` + 202 `{task_id}`, хендлер в `sourcing/tasks_ai.py`.

## После кода

1. Тесты — рядом с тестами образца, в его стиле:

   ```bash
   docker compose exec backend pytest <app>/tests/<файл> -v
   ```

2. **api-contract (CI-гейт!)**: изменились сериализаторы/модели → перегенерируй контракт:

   ```bash
   docker compose exec backend python manage.py spectacular --file schema.json
   cd frontend && npm run gen:api-types
   ```

3. Прогони `/arch-review` по диффу.
4. Сообщи пути созданных файлов и коды новых ошибок.
