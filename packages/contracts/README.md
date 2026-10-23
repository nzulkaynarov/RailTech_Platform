# packages/contracts — контракт CRM ↔ ERP ↔ Cabinet

Источник истины шва ансамбля (ORCHESTRATOR §3.3: **контракт раньше кода**; события — только через шину `rt_bus`, §3.14). Объяснение — `docs/CONTRACTS.md` (шина — §9);
здесь — машиночитаемые файлы и генерация клиентов. Версия 0 (M0-INF-02).

| Файл | Что описывает | Кто реализует / потребляет |
|---|---|---|
| `openapi/erp-integration.yaml` | Integration API `/api/integration/v1/*` (CRM → ERP): handoff, контакты, сделки, документы, каталог, провижининг, здоровье, расходы ИИ | ERP `integration` (M3-ERP-01); CRM коннектор и `services/handoff` (M3-CRM-02/03) |
| `openapi/erp-portal.yaml` | Portal API `/api/portal/v1/*` (Cabinet → ERP): вход Telegram/magic-link, запросы, КП, договоры, счета, акты, поставки, документы, каталог, компания | ERP `portal` (M2-ERP-01…03); Cabinet (M2-CAB-01) |
| `openapi/erp-internal.yaml` | Internal API `/api/v1/*` — **генерируется** из drf-spectacular (срез `/api/v1/` схемы бэкенда, `make -C apps/erp openapi`), руками не правится; дрейф ловит `make -C apps/erp openapi-check` (FIX-40) | ERP SPA (типы строит из `apps/erp/backend/schema.json`, не отсюда); CRM — SSO-обмен (`/auth/sso/*`) |
| `openapi/crm.yaml` | API CRM `/api/v1/*` (SPA CRM, Платформа, Cabinet — форма лида) — **генерируется** из FastAPI (`make -C apps/crm openapi`), руками не правится; дрейф ловят `crm-lint` в CI и стадия `crm` в `ci_local.sh`. Линт — `redocly.crm.yaml` | CRM frontend (orval), Cabinet (`crm-form.d.ts`), BFF (`app/clients/crm_models.py`, `make -C apps/platform crm-models`) |
| `openapi-breaking-exceptions.yaml` | Исключения из проверки совместимости OpenAPI (файл, идентификатор проверки oasdiff, путь, причина, срок `until`); пуст по умолчанию — ломающее идёт новым мажором | `scripts/openapi_compat.py` (`docs/CONTRACTS.md` §7.1) |
| `events/envelope.v1.json` | Конверт событий шины `rt_bus`: CloudEvents 1.0 + `tenant`, `correlationid`, `traceparent` (`docs/CONTRACTS.md` §9.1) | `packages/rt-bus` (B1); все издатели и подписчики |
| `events/<домен>/<сущность>.<действие>.v<N>.json` | Схема `data` типа `uz.railtech.<домен>.<сущность>.<действие>.v<N>` (JSON Schema 2020-12); общие определения — `events/<домен>/_defs.v<N>.json`; домены v1: `erp` (22 типа), `crm` (клиент, контакт, лид), `identity` (сотрудник) | издатель — проверка строгая; подписчик — терпимая (§9.1) |
| `events/<домен>/examples/<сущность>.<действие>.v<N>.json` | Пример полного конверта на каждый тип (тест: проходит конверт и схему типа) | тесты сервисов |
| `events/asyncapi.yaml` | AsyncAPI 3.0: канал и сообщение на каждый тип, HTTP-доставка `/bus/v1/events`, заголовки `X-RT-*`, подпись, коды ответов | документация, проверка `@asyncapi/parser` |
| `bus/subscriptions.yaml` (+ `.schema.json`) | Подписки `rt_bus`: подписчик → адрес приёмника → маски типов (§9.5) | `rt-bus` у каждого сервиса (`RT_BUS_SUBSCRIPTIONS`) |
| `generated/python/` | Пакет `rt-contracts` (`import rt_contracts.events`): `Envelope`, модель `data` на тип, `TYPES` — **генерируется** (`scripts/gen_python.py`) | ERP, CRM, BFF (B3–B5) |
| `events.schema.json` + `examples/events/*.json` | **Устаревает** (L7): прежний вебхук ERP → CRM (§3). Не править; удаляют B3 (ERP, монтирование в `infra/deploy`) и B4 (копия CRM и сами файлы) | ERP (M3-ERP-02); CRM приёмник (M3-CRM-04) — до B3/B4 |
| `mcp-tools.json` | Инструменты `erp-mcp` для агента CRM с контекстом `X-Agent-Context`; схема — `mcp-tools.schema.json` (запрещает идентификаторы клиента в аргументах) | ERP (M3-ERP-03); бот CRM (M3-CRM-07) |
| `sso-token.md` | SSO-токен сотрудника: claims, передача, проверка, отзыв | ERP (M3-ERP-04); CRM (M3-CRM-06) |

## Команды

```
make contracts                        # из корня: lint + generate + typecheck + test + compat + openapi-compat (ниже)
make -C packages/contracts install    # pnpm install --frozen-lockfile; uv sync --locked (Python 3.12, pyproject.toml + uv.lock)
make -C packages/contracts lint       # redocly (OpenAPI), ajv (старая схема событий, erp-mcp, Платформа), @asyncapi/parser, ruff
make -C packages/contracts generate   # openapi-typescript → generated/*.d.ts; orval → generated/crm/; модели → generated/python/
make -C packages/contracts typecheck  # tsc по сгенерированному
make -C packages/contracts test       # pytest: схемы, примеры, AsyncAPI ↔ файлы, подписки, модели; правила совместимости
make -C packages/contracts compat     # совместимость events/** и bus/subscriptions.schema.json с CONTRACTS_BASE_REF (origin/main)
make -C packages/contracts openapi-compat  # oasdiff: ломающие изменения openapi/*.yaml против той же базы (нужен Docker или OASDIFF_BIN)
```

`openapi-compat` запускает закреплённый `oasdiff` (образ `tufin/oasdiff` с тегом и digest в `scripts/openapi_compat.py`) в
одноразовом контейнере; без Docker — свой бинарь той же версии в `OASDIFF_BIN`. Правила мажора, как читать красный результат и когда
допустимо исключение — `docs/CONTRACTS.md` §7.1. Тесты «ломающее → красный» — `tests/test_openapi_compat.py` (удалён путь, удалено
обязательное поле ответа, новое обязательное поле запроса, суженный enum, мажор, исключения) и `tests/test_events_compat.py`.

Python-инструменты (`datamodel-code-generator`, `jsonschema`, `PyYAML`, `pytest`, `ruff`) — uv-проект здесь же, версии
закреплены в `uv.lock`; вызываются через `uv run` из Makefile. Скрипты — `scripts/`, тесты — `tests/`.

### Новый тип события

1. Схема `events/<домен>/<сущность>.<действие>.v1.json` (`$id` = `https://railtech.uz/contracts/events/<домен>/<файл>`,
   `additionalProperties: false`, общие определения — `$ref` на `_defs.v1.json`).
2. Пример полного конверта `events/<домен>/examples/<сущность>.<действие>.v1.json`.
3. Канал, сообщение и операция в `events/asyncapi.yaml` (тест сверяет в обе стороны).
4. При необходимости — подписка в `bus/subscriptions.yaml`.
5. `make contracts` — пересобирает `generated/python`; закоммитить вместе со схемой.

Ломающее изменение типа (§9.6) — новый файл `…v2.json` рядом с `v1` (двойная публикация на переходе), правка `v1`
проверка совместимости не пропустит.

### rt-contracts в сервисе

```
uv add --editable ../../packages/contracts/generated/python   # CRM, BFF (uv); путь — от каталога сервиса
pip install -e packages/contracts/generated/python            # ERP (requirements) — или строкой в requirements.in
```

```python
from rt_contracts.events import TYPES, Envelope
env = Envelope.model_validate(body)
data = TYPES[env.type].model_validate(env.data)   # например, rt_contracts.events.erp.QuoteSentV1
```

`generated/` коммитится (типов `erp-internal` там нет: ERP SPA строит свои из `backend/schema.json`; `erp-portal.d.ts` и `erp-integration.d.ts` — для Cabinet и CRM; `python/` — пакет `rt-contracts`). CI (M0-INF-04) и `scripts/ci_local.sh contracts` запускают `make contracts` и падают, если `git diff` в `generated/` не пуст или там есть незакоммиченные новые файлы:
контракт и сгенерированное расходятся → PR не принимается. Сравнение совместимости требует базы: CI скачивает `origin/main`,
`ci_local.sh` делает `git fetch origin main`.

## Правила изменения

1. Меняется файл здесь → в том же PR пересобирается `generated/` и обновляются обе стороны (ERP и CRM/Cabinet) в одной вехе.
2. Несовместимое изменение API — до 1.0 (`info.version` 0.x): повышение минорной версии (0.2.4 → 0.3.0); с 1.0 — новый префикс версии (`v2`), мажор в `info.version` и период совместимости (ADR-0016; проверяет `oasdiff` в `make contracts`, `docs/CONTRACTS.md` §7.1); события шины — новый файл и тип `.v(N+1)` с двойной публикацией (`docs/CONTRACTS.md` §7, §9.6; проверяет `make contracts`).
3. Конфликт двух агентов на одном файле контракта решает оркестратор; контракт не правят вдвоём.
4. Потребители: Cabinet и ERP SPA — `openapi-typescript` по этим файлам (Cabinet — ещё `crm.yaml`, только форма лида); CRM frontend — orval по `crm.yaml` (`apps/crm/frontend/src/api/generated`); BFF — модели ответов CRM из `crm.yaml`; `generated/crm/` — клиент Integration API; CRM backend (Python) — клиент по `erp-integration.yaml` появится в `apps/crm` на M3-CRM-02.
