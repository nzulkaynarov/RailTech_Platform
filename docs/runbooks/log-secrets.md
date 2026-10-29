# Runbook: секреты в логах ERP и CRM (FIX-66b)
Статус: действует · Владелец: лид · Обновлено: 2026-10-22

Повод: ревью #130 нашло, что токен Telegram-бота пишется в журнал CRM stdlib-логгером httpx
(`HTTP Request: GET https://api.telegram.org/bot<токен>/getMe`, проба раз в минуту). FIX-66b — аудит всех мест,
где URL, заголовок или тело с секретом может уйти в логгер или в Sentry, общая маска и тест на каждое место.
Токены, ключи и подписи в тестах — явно фейковые (префикс `fix66b`).

## 1. Что сделано

| Слой | ERP | CRM |
|---|---|---|
| Общая маска | `core/log_mask.py`: `mask_secrets`, `mask_value`, `SecretMaskFilter` | `app/security/log_mask.py`: то же + `structlog_processor` (зеркало, наборы правил одинаковые) |
| Подключение к журналу | `LOGGING["filters"]["mask_secrets"]` на обработчике `console` (`core/settings/ai.py`); сигналы Celery `after_setup_logger` / `after_setup_task_logger` (`core/celery.py`) вешают тот же фильтр на обработчики воркера и Beat | процессор в конце цепочки `ProcessorFormatter` и в начале `_shared_processors` (до `pii`) в `app/log.py`: покрывает и structlog, и stdlib (uvicorn, httpx, aiogram, procrastinate) |
| Шумные библиотеки → WARNING | `NOISY_LOGGERS` в `LOGGING["loggers"]` | `quiet_noisy_loggers()` при `configure_logging` |
| Sentry | `before_send=scrub_event` (PII + `mask_event`), `before_breadcrumb=mask_breadcrumb` | sentry-sdk в CRM не подключён; хуки `mask_sentry_event` / `mask_breadcrumb` готовы, сторож `test_sentry_init_in_crm_must_pass_both_hooks` падает, если `sentry_sdk.init` появится без них |

Что маскируется (все правила — в `log_mask.py`, пример → результат):

| Что | Пример | Результат |
|---|---|---|
| Токен Bot API в пути и без префикса | `/bot123456789:AAH…/getMe` | `/bot[REDACTED]/getMe` |
| S3 presigned URL | `X-Amz-Signature=…`, `X-Amz-Credential=…`, `X-Amz-Security-Token=…` | `X-Amz-Signature=[REDACTED]` |
| Заголовки | `Authorization: Bearer …`, `'Authorization': 'Basic …'`, `X-Api-Key`, `X-Signature`, `X-Telegram-Bot-Api-Secret-Token`; `Bearer …` вне заголовка (слово `Basic` вне заголовка Authorization не трогаем: «Basic configuration loaded») | значение → `[REDACTED]` |
| Ключи шлюза | `sk-…`, `sk-proj-…` | `sk-[REDACTED]` |
| JWT (SSO) | `eyJ….eyJ….sig` | `[REDACTED]` |
| Логин:пароль в адресе | `redis://:pass@host`, `https://u:pw@host` | `redis://[REDACTED]@host` |
| Секретные параметры запроса (только после `?`/`&`) | `?token=…`, `&code=…`, `?key=…`, `access_token`, `refresh_token`, `api_key`, `signature`, `secret`, `password` | значение → `[REDACTED]` |
| Тело JSON/repr | `"access_token": "…"`, `'password': '…'` | значение → `[REDACTED]` |

`code=` вне строки запроса (`channel_take_rejected code=NOT_FOUND`) — это код ошибки, его маска не трогает.
Путь `/auth/magic/<токен>` и публичные ссылки на документы ERP закрывает прежний `RedactPortalTokenFilter` (FIX-14/15/55).

## 2. Аудит: место → что утекало → как закрыто → тест

| № | Место | Что утекало | Как закрыто | Тест |
|---|---|---|---|---|
| 1 | httpx/httpcore, INFO (CRM: проба Telegram раз в минуту, ERP: шлюз ИИ, курсы ЦБ, ТН ВЭД, доставка вебхуков) | URL запроса целиком, в т.ч. `/bot<токен>/getMe` | оба — WARNING (ERP был уже; CRM — #130 + `quiet_noisy_loggers`); если уровень подняли (DEBUG), строка проходит через маску | ERP `test_httpx_request_log_never_shows_the_bot_token_even_if_level_is_raised`, `test_noisy_http_libraries_are_quiet_by_default`; CRM `test_noisy_http_libraries_are_quiet_after_configure`, `test_httpx_request_log_never_shows_the_bot_token_even_if_level_is_raised` |
| 2 | urllib3 / requests / botocore / boto3 / s3transfer / aiobotocore / openai / litellm, DEBUG | `urllib3.connectionpool`: путь с query (подпись S3); `botocore`: параметры и заголовки запроса, SigV4; `openai`: опции запроса | все — WARNING (`NOISY_LOGGERS`, оба приложения); при `DJANGO_LOG_LEVEL=DEBUG` / `LOG_LEVEL=DEBUG` уровни этих логгеров остаются WARNING | `test_noisy_http_libraries_are_quiet_by_default` (параметризован по списку) |
| 3 | Telegram Bot API в ERP | прямых вызовов нет: `git grep` по `api.telegram.org`, `sendMessage`, `send_text_via_bot` в `apps/erp` — только тест «ERP в Telegram не пишет» (после FIX-60a код акцепта идёт событием в бот CRM); `TELEGRAM_BOT_TOKEN` читает только проверка подписи `initData` портала | токен не логируется: `telegram_auth` пишет «signature mismatch» / «not configured» без значений | ERP `test_telegram_init_data_validation_does_not_log_the_bot_token` |
| 4 | Telegram в CRM: aiogram, `external_probes`, `bot/supervisor` (`exc_info=True`) | исключение с URL (`httpx.HTTPStatusError … for url '…/bot<токен>/getMe'`) в трассировке; текст трассировки `pii` считал «безопасным» ключом `exception` | процессор маски после `format_exc_info`; `exception` и `event` маскируются; служебные ключи structlog (`exc_info`, `stack_info`, `_record`, `_from_structlog`) маска не трогает, а кортежи сохраняют тип — иначе `exc_info=(type, exc, tb)` из stdlib превращался в list и трассировка пропадала | CRM `test_traceback_text_is_masked`, `test_stdlib_record_with_bot_token_is_masked`, `test_stdlib_exc_info_outside_except_keeps_traceback_and_masks_it`, `test_mask_value_keeps_the_container_type` |
| 5 | CRM: `pii.structlog_processor` | «123456789» из токена → `[number]`, а хвост токена (`:AAH…`) оставался; `event` не маскировался | секретная маска стоит ДО `pii` | CRM `test_structlog_kwargs_are_masked_before_pii` |
| 6 | LiteLLM из ERP (`ai/services/gateway.py`) | шлюз на 401 отвечает «Incorrect API key provided: sk-…» — `_log_outcome` пишет `error` (до 300 символов) в WARNING; ключ в заголовке `Authorization` не логируется (проверено) | маска `sk-…` и `Bearer …` | ERP `test_ai_gateway_error_log_hides_the_key_echoed_by_the_gateway` |
| 7 | LiteLLM из CRM (`agents/llm.py`, `litellm_*`) | логируют `type(exc).__name__` и статус, не тело; `openai` на DEBUG пишет опции запроса | `openai` → WARNING; общая маска на случай `exc_info` | `test_noisy_http_libraries_are_quiet_after_configure`, `test_traceback_text_is_masked` |
| 8 | LiteLLM-сервис (`infra/ai`) | подробные логи запросов не включены (`set_verbose`, `detailed_debug`, `log_raw_request_response` в конфиге нет) | без изменений; не включать на проде | — (проверено чтением `infra/ai/litellm.config.yaml`, `infra/compose/base.yml`) |
| 9 | События ERP → CRM по шине `rt_bus`, повторы доставки (`rt_bus_delivery.last_error`) | на неудачной попытке библиотека пишет `last_error = HTTP <код>: <тело ответа подписчика>` (усечённое) и текст исключения. Подпись и секрет в журнал не пишутся; код акцепта в outbox — маска `***` (FIX-60a), реальное значение в кэше | тело ответа подписчика с эхом заголовков (`Authorization: Bearer …`) маскируется в транспорте ДО усечения библиотекой (`integration/bus_http.py: SecretMaskingTransport`, секрет на границе обрезки) | ERP `test_bus_delivery_error_hides_secrets_from_the_subscribers_echo`, `test_bus_error_masks_secret_cut_by_the_truncation` |
| 10 | Воркер и Beat Celery | Celery при старте заменяет обработчики корневого логгера своими (`worker_hijack_root_logger`): фильтры Django `LOGGING` (в т.ч. `RedactPortalTokenFilter`) в воркере не действовали | сигналы `after_setup_logger` / `after_setup_task_logger` вешают `SecretMaskFilter` на обработчики Celery | ERP `test_celery_worker_loggers_get_the_mask_filter` |
| 11 | S3 presigned URL (ERP `PrivateStorage.url`, CRM `presigned_get`) | URL с `X-Amz-Signature` / `X-Amz-Credential` попадал бы в строки доступа и DEBUG-логи клиентов; ERP отдаёт файлы потоком и presigned в логах не печатает; CRM отдаёт ссылку клиенту в Telegram и инструменту MCP | маска `X-Amz-*` в любом месте строки; botocore/urllib3 → WARNING; `ClientError` botocore подписи не содержит | `test_secret_is_masked` (ветки `X-Amz-*`), `test_filter_masks_message_args_extra_and_traceback` |
| 12 | SSO и magic-link в access-логах | ERP: путь `/auth/magic/<токен>` — прежний фильтр; ссылка входа в письмах — во фрагменте `#token=` (на сервер не уходит); SSO-токен — в теле POST, не в URL; Daphne запущен с `-v 0`, строки доступа пишет `AccessLogMiddleware` (только путь). CRM: `uvicorn.access` печатает путь **с query** — `?token=`/`?code=` ушли бы в журнал | маска query-секретов и JWT в процессоре CRM; Caddy: директивы `log` в Caddyfile нет — access-лог выключен (проверено, не включать без `filter` на `uri`) | CRM `test_uvicorn_access_line_with_query_secrets_is_masked`; ERP `test_log_redaction_public_links.py` (прежний) |
| 13 | `django.request` и прочие Django-логгеры | путь запроса (без query) — токены в пути закрывает прежний фильтр; остальное — общая маска на `console` | `mask_secrets` в фильтрах обработчика `console` | `test_console_handler_carries_the_mask_filter`, `test_the_real_console_handler_masks_what_it_prints` |
| 13а | ERP `JSONFormatter` (прод, `DJANGO_LOG_FORMAT=json`) | форматировал исключение заново (`formatException`), мимо замаскированного фильтром `exc_text`: текст исключения с URL/токеном уходил в JSON как есть | форматтер берёт готовый `record.exc_text` | ERP `test_json_formatter_does_not_bypass_the_mask_for_tracebacks` |
| 14 | Sentry ERP | `before_send` маскировал только ПДн в `request.data`/`extra`/данных крошек; URL запроса, `query_string`, заголовки, текст исключений и переменные кадров, `logentry`, `message`, `message` крошек уходили как есть; `before_breadcrumb` не было (httpx/requests пишут URL в крошки) | `scrub_event` вызывает `mask_event` независимо от маски ПДн (сбой маски ПДн не оставляет секреты в событии); `before_breadcrumb=mask_breadcrumb` | ERP `test_sentry_event_after_hook_has_no_secrets`, `test_sentry_breadcrumb_hook_masks_url_message_and_data`, `test_sentry_hooks_are_wired_in_settings_when_dsn_is_set`, `test_secret_mask_runs_even_when_pii_scrub_fails` |
| 15 | Sentry CRM | не подключён (нет `sentry-sdk`, нет `sentry_sdk.init`) — утечки нет | хуки `mask_sentry_event`, `mask_breadcrumb` и сторож на будущий `init` | CRM `test_sentry_event_after_hook_has_no_secrets`, `test_sentry_init_in_crm_must_pass_both_hooks` |
| 16 | Procrastinate (CRM) | аргументы задач (событие ERP с телом) в журнал не попадают: `ExtraAdder` не подключён, `extra` записей не печатается; аргументы — в таблице очереди, не в логах | без изменений | — (по коду `app/log.py`) |
| 17 | Артефакты в репозитории | `git grep -nIE 'bot[0-9]{6,}:[A-Za-z0-9_-]{20,}'` по рабочему дереву, истории и веткам, HAR/trace/логи e2e в `docs/screens`, `docs/runbooks`: чисто (проверял лид, повторено) | — | `gitleaks` в `ci-local` |

## 3. Хвосты и правила для нового кода

- ERP `rt_bus_delivery.last_error` (БД, админка «rt_bus → Delivery») получает уже замаскированное тело ответа подписчика
  (`SecretMaskingTransport`, до усечения библиотекой). Таблица `IntegrationWebhookEvent` удалена (B3, данных прода не было).
- `django.db.backends` на DEBUG печатает SQL с параметрами — не включать DEBUG-журнал базы на проде.
- Новый клиент HTTP / SDK: логгер библиотеки добавить в `NOISY_LOGGERS` обоих `log_mask.py`.
- Новое правило маски — в оба `log_mask.py` и в параметризованный тест обоих приложений; регулярные выражения держать одинаковыми.
- Не писать в журнал URL, заголовки и тела запросов целиком; если нужно — только `type(exc).__name__`, статус и идентификаторы.
- Подключаете Sentry в CRM: `sentry_sdk.init(..., before_send=mask_sentry_event, before_breadcrumb=mask_breadcrumb,
  send_default_pii=False)`; сторож в тестах проверит оба хука.
