# Runbook: найти запрос по X-Request-ID в журналах Caddy, CRM и ERP (S0-6, ADR-0017)

## Когда применять
Клиент или сотрудник сообщает о сбое («Проверить связь» не прошла, передача клиента в ERP не дошла, 502 на домене), и нужно
пройти один запрос через все слои: вход (Caddy) → CRM → ERP. Один запрос несёт один идентификатор `X-Request-ID`.

## Как идентификатор попадает в журналы
1. **Caddy** (все домены, `infra/caddy/Caddyfile.prod` и `Caddyfile.dev`, сниппеты `access_log` и `request_id`):
   - пришёл заголовок `X-Request-ID` от клиента — пропускается как есть; нет (или пустой) — Caddy ставит UUID запроса;
   - заголовок уходит во все апстримы и возвращается клиенту в ответе (ровно одно значение);
   - журнал доступа — JSON в stdout, по строке на запрос; идентификатор — в поле `request_id`.
2. **CRM** (`asgi-correlation-id`): берёт идентификатор из заголовка и пишет его в поле `request_id` каждой строки журнала запроса.
   Каждый вызов CRM → ERP по HTTP (`app/integrations/erp_transport.py`) несёт тот же `X-Request-ID` и оставляет строку
   `erp_http_call` (метод, путь, статус, длительность, `request_id`). Вне запроса (воркер очереди: передача клиента, провижининг
   сотрудников) CRM создаёт **новый UUID на вызов** и пишет его в ту же строку `erp_http_call` — по ней находят вызов в ERP.
3. **ERP** (`core.logging.RequestIDMiddleware`): принимает входящий `X-Request-ID`, кладёт в контекст журнала и возвращает в ответе;
   поле `request_id` — в каждой строке JSON-журнала (`DJANGO_LOG_FORMAT=json`, на проде включено).

Проброс идентификатора через очереди и события (Procrastinate, Celery, вебхуки ERP → CRM) здесь **не** сделан: это поле
`correlationid` конверта события (волна 11).

## Диагностика
Пусть идентификатор известен (из ответа клиенту — заголовок `X-Request-ID`, или из журнала). Команды — на VPS1 из каталога
проекта; `$RID` — идентификатор.

```bash
RID=3d97dc6c-5a9e-490b-8a33-413904685ba9
C="docker compose -f infra/compose/base.yml -f infra/compose/prod.yml --env-file .env.prod"   # dev: base.yml + dev.yml, --env-file .env

# 1) Caddy: строка доступа (статус, длительность, домен, путь)
$C logs --no-log-prefix caddy | grep "\"request_id\":\"$RID\"" | jq '{ts, host: .request.host, method: .request.method, uri: .request.uri, status, duration}'

# 2) CRM: строки запроса и исходящие вызовы к ERP
$C logs --no-log-prefix crm-api | grep "$RID" | jq '{timestamp, event, method, path, status, error, duration_ms}'

# 3) ERP: строки запроса
$C logs --no-log-prefix erp-backend | grep "$RID"
```

Если запрос шёл из воркера CRM (идентификатора клиента нет), найдите строку `erp_http_call` в журнале воркера
(`$C logs crm-worker | grep erp_http_call`), возьмите из неё `request_id` и повторите шаг 3.

Что искать:
| Где | Что видно |
|---|---|
| Caddy: `status` 502/504, `duration` большая | апстрим (CRM/ERP) не ответил; смотреть его журнал на то же время |
| CRM: `erp_http_call` с `error` (`ReadTimeout`, `ConnectError`) и без `status` | ERP не ответила или недоступна; в ERP строки с этим `request_id` нет |
| CRM: `erp_http_call` со `status` 401/403/429 | токен CRM → ERP, лимит частоты (`Retry-After`); в ERP есть строка с тем же `request_id` |
| ERP: строки есть, а в CRM ответ ошибочный | ошибка на стороне ERP; идти по её строкам |

## Что в журнале Caddy скрыто
Фильтр-кодировщик удаляет заголовки `Authorization`, `Proxy-Authorization`, `Cookie`, `X-Telegram-Bot-Api-Secret-Token`,
`X-Signature`, `X-Agent-Context`, `X-Crm-Context`, `X-Pairing-Proof`, `X-Portal-Session`, `X-Api-Key`, `X-Csrftoken` и `Set-Cookie`
ответа; в `uri` и `Referer` значения `/auth/magic/…`, `/public/(quotes|documents|doc-links)/…` и параметры `token`, `key`,
`signature`, `code`, `secret` и т. п. заменены на `REDACTED`. `log_credentials` не включён. Новый заголовок с секретом — добавить
в сниппет `access_log` обоих Caddyfile (логика dev и prod одна) и в таблицу выше.

## Проверка
Два запроса через Caddy (dev: `curl --resolve crm.localhost:$HTTP_PORT:127.0.0.1 http://crm.localhost:$HTTP_PORT/...`): без заголовка
(в ответе появился `X-Request-ID`) и с `X-Request-ID: test-1` (вернулся `test-1`); в журнале Caddy — поле `request_id` с теми же
значениями; в журнале CRM и ERP — строки с ними (для вызова, который идёт в ERP, например `POST /api/v1/integrations/erp/check`).

## Эскалация
Идентификатор не доехал до ERP (в CRM `erp_http_call` есть, в ERP нет строки): проверьте, что ERP той версии с
`RequestIDMiddleware` и что вызов не идёт мимо `erp_transport` (`grep -rn "httpx.AsyncClient" apps/crm/backend/app/integrations`).
Идентификатор не появился в журнале Caddy: контейнер Caddy запущен со старым Caddyfile (после правки файла —
`docker compose … up -d --force-recreate --no-deps caddy`, bind-mount файла не видит его замену git'ом).
