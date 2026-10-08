---
name: api-endpoint
description: Добавить REST-эндпоинт /api/v1 — роутер, Pydantic-схемы, RBAC-зависимость Casbin, аудит мутаций, тест матрицы ролей, экспорт OpenAPI и регенерация клиента.
---

# REST-эндпоинт

Слои: `api` → `services` → `repositories` (CLAUDE.md §4). Ошибки домена — классы из `app/domain/errors.py`, маппинг в HTTP — один handler.

## Шаги

1. Найди эндпоинт в `PLAN.md` текущей фазы и `SPEC §10`; права — в `infra/casbin/policy.seed.csv`.
2. Схемы запроса/ответа — `app/schemas/` (Pydantic v2, mypy strict). Не возвращай ORM-объекты.
3. Роутер `app/api/v1/<resource>.py`: зависимость `require(action, resource)` (`SPEC §11`); объектные проверки (владелец лида) — в сервисе.
4. Мутация → запись через `security/audit.py` (before/after). Без исключений, включая callback-кнопку.
5. Сервис и репозиторий; доменная логика — чистые функции с тестами.
6. Тесты:
   - unit сервиса/домена (параметризованные);
   - integration: матрица роль × действие (admin/manager/viewer/аноним) с ожидаемыми 2xx/401/403/404/409;
   - аудит-запись появилась.
7. `make openapi` → закоммить `docs/api/openapi.json` (CI проверяет актуальность); с Фазы 4 — регенерация клиента orval во `frontend/src/api/`.
8. `make check`; в PR — curl-пример в «Проверить на dev».
