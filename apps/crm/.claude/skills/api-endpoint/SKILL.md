---
name: api-endpoint
description: Добавить REST-эндпоинт /api/v1 — роутер, Pydantic-схемы, RBAC-зависимость Casbin, единый формат ошибок (ADR-0017), аудит мутаций, тест матрицы ролей, экспорт OpenAPI и регенерация клиента orval.
---

# REST-эндпоинт

Слои: `api` → `services` → `repositories` (CLAUDE.md §4). Ошибки домена — классы из `app/domain/errors.py`, маппинг в HTTP — один handler (`app/api/errors.py`). Формат ошибки — ADR-0017: `{code, message, details{reason, field, errors[]}}`; `details.reason` — значение `Reason` (StrEnum), фронт показывает текст из `t.apiReasons[reason]`.

## Шаги

1. Найди эндпоинт в `PLAN.md` текущей фазы и `SPEC §10`; права — `infra/casbin/policy.seed.csv` (seed добавляет только недостающие правила; на стенде политика живёт в БД — новая строка применится при рестарте api). Каталог ресурсов/действий — `app/security/rbac.py CATALOG`.
2. Схемы запроса/ответа — `app/schemas/` (Pydantic v2, mypy strict). Не возвращай ORM-объекты. Докстрока функции роутера попадает в OpenAPI — пиши её для потребителя API.
3. Роутер `app/api/v1/<resource>.py`: зависимость `require(resource, action)` — именно в этом порядке, например `require("leads", "read")` (готовые алиасы `Reader`/`Writer`/`Worker` в начале модуля); объектные проверки (владелец лида, `domain/lead_access.py`) — в сервисе.
4. Ошибки: бросай доменные исключения с `reason=Reason.<...>`; новое значение `Reason` → добавь текст в `frontend/src/i18n/ru/core.ts apiReasons` (тест `useApiErrorToast.test.tsx` ловит пропуски). Значения `Reason` не переименовывать — контракт.
5. Мутация → запись через `security/audit.py` (before/after). Без исключений, включая callback-кнопку. Изменился лид/передача → `events.publish` (SSE обновит CRM без перезагрузки).
6. Сервис и репозиторий; доменная логика — чистые функции с параметризованными тестами.
7. Тесты:
   - unit сервиса/домена;
   - integration (`tests/integration/`): матрица роль × действие (admin/manager/viewer/аноним) с ожидаемыми 2xx/401/403/404/409 и `details.reason`;
   - аудит-запись появилась.
   Локально integration — только на одноразовых контейнерах: скилл `stand-verify`.
8. `make openapi` → закоммить `packages/contracts/openapi/crm.yaml` (ломающее изменение — только новым мажором `/v2`, см. `docs/CONTRACTS.md` §7; `make contracts` из корня) и `frontend/src/api/generated/` (CI падает при любом расхождении, в том числе из-за докстроки). Клиент — orval, хуки TanStack Query — `frontend/src/api/queries.ts` / `adminQueries.ts`.
9. `make check`; в PR — curl-пример и шаг для каждой роли в «Проверить на dev».
