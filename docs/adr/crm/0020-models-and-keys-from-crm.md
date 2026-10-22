# 0020 — Модели и ключи ролей меняет админ в CRM через БД LiteLLM

- Статус: accepted (2026-10-12, владелец: «делай все», ADR-0018 следующий шаг)
- Связано: ADR-0004 (модели), ADR-0014 (лимиты), ADR-0018 (подключения и секреты), аудит
  `docs/audit/2026-10-12-admin-console-scope.md` §3 п. 3; SPEC §2, §11; CLAUDE.md §2.3.

## Контекст

Смена провайдера, модели или ключа роли (диалог, квалификатор, резерв, поиск, проверка качества)
требовала правки `infra/litellm.config.yaml`/`.env` и перезапуска контейнера. Владелец хочет делать это
из «Модели ИИ» без файлов и рестартов, штатными средствами LiteLLM, без обходных решений.

## Проверка на установленной версии (LiteLLM v1.104.2, 2026-10-12)

Одноразовые контейнеры `rt-litellm-spike-*` (pgvector 0.8.7-pg16 + `ghcr.io/berriai/litellm:v1.104.2`
с `DATABASE_URL`, `STORE_MODEL_IN_DB=True`, `LITELLM_SALT_KEY`, `LITELLM_MASTER_KEY`) и подставной
провайдер (локальный HTTP-сервер вместо `api.anthropic.com` через `api_base`), ключи — фиктивные,
платных вызовов не было; контейнеры удалены.

1. Эндпоинты (исходник `litellm/proxy/management_endpoints/model_management_endpoints.py`):
   `POST /model/new`, `POST /model/update` (PUT-семантика, «old endpoint»), `PATCH /model/{model_id}/update`,
   `POST /model/delete` (`{"id": …}`), `GET /model/info`.
2. `/model/new` с тем же `model_name`, что у модели из конфига, **не заменяет** её: `/model/info` показывает
   две deployment одного алиаса (`db_model: false` и `true`) — это группа балансировки.
3. Модель из конфига нельзя изменить или удалить через API: `/model/update` → «Model in config. Store model
   in db via `/model/new`. to edit», `/model/delete` → «not found in db».
4. Ключи и модель в `LiteLLM_ProxyModelTable.litellm_params` хранятся зашифрованными (`LITELLM_SALT_KEY`);
   `/model/info` не возвращает `api_key` (возвращает `model`, `api_base`). Ответ `/model/new` содержит
   шифртекст параметров.
5. Изменения применяются **без перезапуска**: сразу после `/model/update` с новым ключом подставной провайдер
   получил новый `x-api-key`; после `/model/new` алиас сразу виден и обслуживается.
6. Ссылка `os.environ/ANTHROPIC_API_KEY` в `api_key` модели из БД разрешается прокси из своего env
   (провайдер получил ключ из env контейнера).
7. `/model/update` без `api_key` сохраняет прежний ключ; `model_info` при этом не меняется (флаги
   и цены старой модели остались бы у новой).
8. После перезапуска прокси модели из БД загружаются; конфиг **без `model_list`** стартует штатно,
   `router_settings.fallbacks` работают для моделей из БД (сбойная deployment `qualifier-model` →
   `fallback-model`).
9. Повторный `/model/new` с существующим `model_info.id` → 500 (id уникален).

Команды (сокращённо): `docker run … -e STORE_MODEL_IN_DB=True -e LITELLM_SALT_KEY=… litellm:v1.104.2`;
`curl -H "Authorization: Bearer $MASTER" $U/model/new -d '{"model_name":"dialog-model","litellm_params":{…},"model_info":{"id":"rt-dialog-model"}}'`;
`curl … $U/model/info`; `curl … $U/model/update -d '{…,"model_info":{"id":…}}'`;
`curl … $U/model/delete -d '{"id":…}'`; `psql … 'select … from "LiteLLM_ProxyModelTable"'`.

## Решение

1. **Модели ролей живут в БД LiteLLM** (`STORE_MODEL_IN_DB=True`, отдельная база `litellm` в том же
   Postgres, создаёт `litellm-db-init` так же, как `langfuse-db-init`). `infra/litellm.config.yaml` хранит
   только `router_settings`/`litellm_settings`/`general_settings` и **не содержит `model_list`** (п. 2–3).
2. **Значения по умолчанию** — `infra/litellm.models.yaml` в штатном формате `model_list` (ключи —
   `os.environ/…`, п. 6). Одноразовый сервис `litellm-seed` (`python -m app litellm-seed`) перед api/worker
   создаёт через `/model/new` только **отсутствующие** алиасы; изменённые из CRM не трогает.
3. **Смена роли** (`PUT /api/v1/models/{alias}`, право `models:write`, повторный пароль): создать новую
   deployment алиаса (`/model/new`, id `rt-<alias>-<hex>`), затем удалить старые (`/model/delete`).
   Не `/model/update`: он не меняет `model_info` (п. 7). Кратко алиас обслуживают две deployment — допустимо.
   `model_info` берётся из значения по умолчанию с той же моделью (флаги Claude 5.5, цены), иначе пусто —
   действует карта моделей LiteLLM. Общие параметры роли (`timeout`, `stream_timeout`, `reasoning_effort`)
   переносятся из значения по умолчанию.
4. **Ключ** уходит только в LiteLLM (шифр `LITELLM_SALT_KEY`). В нашей БД, аудите (`model.update`,
   `model.reset`) и логах — только `…last4` или `env`. Ключ не введён → ссылка `os.environ/<ПРОВАЙДЕР>_API_KEY`
   из значений по умолчанию; для провайдера без ключа в env — 422 `model_key_required`. Ошибка прокси
   возвращается без ключа (маскируется).
5. **Сброс** (`POST /api/v1/models/{alias}/reset`) — та же замена на запись из `litellm.models.yaml`.
6. Провайдеры в CRM: `anthropic`, `gemini`, `openai` (префиксы LiteLLM); расширяется списком в схеме.
7. Предупреждения в ответе: `reindex_required` (смена модели поиска — индекс KB несовместим),
   `quality_check_recommended` (диалог — платная проверка качества только по согласию владельца, сама
   не запускается). Кэш каталога `ModelCatalog` сбрасывается сразу.
8. Если алиас всё ещё задан в конфиге (стенд не мигрирован) — 409 `model_in_config`.

## Альтернативы

- Оставить `model_list` в конфиге и «переопределять» в БД — не поддерживается (п. 2–3): получилась бы
  балансировка между старой и новой моделью.
- Хранить ключи в нашем `secrets_store` и писать `.env`/конфиг — требует рестарта прокси, обход штатного
  механизма LiteLLM.
- `PATCH /model/{id}/update` — сложная семантика слияния `model_info`; замена create+delete проще и проверена.

## Последствия

- Хорошо: смена модели/ключа без файлов и рестартов; ключи зашифрованы штатно; аудит без ключей.
- Плохо: новый секрет `LITELLM_SALT_KEY` — **нельзя менять** после первого запуска (ключи из CRM станут
  нечитаемыми; модели по умолчанию с `os.environ/…` продолжат работать). Хранить с бэкапом `.env`.
- Плохо: база `litellm` не входит в текущий `pg_dump` бэкапа (дампится `POSTGRES_DB`) — при потере
  `litellm-seed` вернёт значения по умолчанию, ключи из CRM нужно ввести заново.
- Меняется: CLAUDE.md §2.3, SPEC §2/§11, `.env.example`, compose, runbooks `deploy.md`, `key-rotation.md`.

## Как проверяем

Unit (respx вместо LiteLLM): параметры, ключ только в запросе к LiteLLM, порядок create→delete, отказ
при алиасе в конфиге, маскирование ключа в ошибке, сброс, засев только отсутствующих. Приёмка на стенде —
чек-лист PR «Проверить на dev».
