# Runbook: прод на двух VPS — установка, деплой, откат, бэкапы (M5-INF-01)

Раскладка и лимиты памяти — `docs/runbooks/servers.md`. Файлы: `infra/compose/prod.yml` (VPS 1, поверх `base.yml`),
`infra/compose/db.yml` (VPS 2), `infra/caddy/Caddyfile.prod`, `infra/deploy/*`, `infra/db/*`, `infra/.env.prod.example`,
`.github/workflows/deploy.yml`. Статус: **установлено на VPS 2026-10-21** (архитектор, резерв Opus): первый успешный деплой
`main @ 735256f7` (run 39565753265) — три домена по HTTPS (Let's Encrypt), `/health` 200, `/ready` CRM — база, S3, LiteLLM `ok`,
`/mcp` снаружи 404. Ошибки первого запуска — §6.

## Как устроено

- **Образы** собирает `deploy.yml` (после зелёного CI на push в `main` или вручную, п. 2) параллельно, по job'у на образ, и кладёт в GHCR с тегом = полный git sha:
  `rt-crm-backend`, `rt-crm-frontend`, `rt-erp-backend`, `rt-erp-frontend`, `rt-cabinet`, `rt-platform-bff`, `rt-platform-web`, `rt-eds` (сервис документооборота, волна 12), `rt-litellm` (свой образ LiteLLM на Debian, `infra/ai/litellm/`; официальный на прод-CPU не стартует). Деплоится только код, уже входящий в `main`.
- **Релиз** на VPS 1 — каталог `/opt/rt/releases/<sha>/` (`infra/`, `apps/crm/infra/casbin`, `packages/contracts/mcp-tools.json`), `/opt/rt/current` — ссылка на текущий.
  Состояние — `/opt/rt/state/{current_tag,previous_tag}`; хранятся пять последних релизов.
- **Секреты приложений** лежат только на серверах: `/opt/rt/.env.prod` (VPS 1) и `/opt/rt-db/.env.db` (VPS 2), оба `chmod 600`.
  В GitHub environment `production` — лишь доступ к серверу (SSH-ключ, known_hosts) и несекретные имена. Решение принято
  здесь, чтобы десятки секретов приложений не жили в GitHub; владелец вправе передумать (тогда `deploy.yml` дописывается).
- **Redis — два экземпляра с разными паролями** (S0-2, ADR-0013 п. 5): `redis-broker` (брокер и результаты Celery, Channels; AOF, `noeviction`, том `redis_broker_data`) и
  `redis-cache` (кэш и троттлинг ERP, одноразовые `jti`, сессии Платформы, Langfuse; `volatile-lru`). Подробно, с отказами — раздел «Redis: брокер и кэш раздельно» ниже.
- **База** — на VPS 2: PostgreSQL 17 + pgvector, 5 баз, по роли на базу (`crm_app`, `erp_app`, `eds_app`, `litellm_app`, `langfuse_app`),
  `pg_hba` — только TLS и только внутренний IP VPS 1.
- **Порядок деплоя** (`infra/deploy/deploy.sh <sha>`): проверка env → `pull` → **проверка базы CPU образов** (`cpu-baseline-check.sh`: в каждом образе запускается import numpy / litellm.proxy / версия бинаря; образ, которому нужен x86-64-v2, останавливает деплой до дампа и миграций, см. servers.md «CPU прод-VPS»); ту же таблицу команд раньше, в PR, прогоняет CI под эмуляцией CPU `qemu64` (задание `cpu-image`, `make deploy-check`, `scripts/qemu_cpu_check.sh`; servers.md, «Проверка под эмуляцией qemu64») → **pg_dump-гейт** `crm`, `erp` и `eds`
  (`predeploy-dump.sh`; нет читаемого дампа — миграций нет) → миграции CRM, ERP и EDS явно (`AUTO_MIGRATE=false` у ERP, `eds-migrate` = `alembic upgrade head`) → автоматические секреты (`make-env-prod.sh ensure-secrets` до проверки env: сейчас `REDIS_PROBE_PASSWORD` — пароль пользователя Redis `crm-probe` для «Состояния системы» (права `PING`/`INFO`, ключей не видит), создаётся случайным и не меняется; руками не вписывается) → **`s3-init`** (`run --rm`: бакеты, ключи и политики доступа RustFS приводятся к `infra/s3/init.sh` на каждом деплое, а не только при первой инициализации; W15-H8b) → `up -d` → smoke → здоровье `eds-api` (у EDS нет домена, smoke его не видит).
- Правило FIX-03: `/mcp` снаружи — 404 на всех доменах, включая Платформу (Caddy); smoke это проверяет.

## 1. Первая установка

Предварительно у владельца: внутренние IP обоих VPS, DNS A-записи `crm.`, `erp.`, `cabinet.railtech.uz` → публичный IP VPS 1,
SSH-доступ (`root` на время установки), ключ деплоя.

### 1.1. Оба сервера: Docker, пользователь, файрвол

```bash
# от root
apt-get update && apt-get install -y ca-certificates curl ufw openssl
curl -fsSL https://get.docker.com | sh          # Docker Engine + compose plugin
adduser --disabled-password --gecos "" deploy && usermod -aG docker deploy
install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
# публичный ключ деплоя (парный приватный — секрет DEPLOY_SSH_KEY в GitHub):
echo "<публичный ключ>" >> /home/deploy/.ssh/authorized_keys && chown deploy:deploy /home/deploy/.ssh/authorized_keys
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/; s/^#\?PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
systemctl reload ssh
# рабочие каталоги, владелец deploy (скрипты и deploy.yml пишут в них без sudo):
install -d -o deploy -g deploy /opt/rt /opt/rt/releases /opt/rt/state          # VPS 1
install -d -o deploy -g deploy /opt/rt-db /var/backups/rt                      # VPS 2
```
Команды для VPS 1 и VPS 2 выполняйте на своём сервере (две последние строки — каждая на своём). У `deploy` нет `sudo`:
всё, что требует root (`db-up.sh`), выполняется отдельным заходом `ssh root@<VPS 2>`.

Файрвол (`ufw`), подставьте внутренние IP:

```bash
# VPS 1 (app): наружу только 80/443 и SSH; S3 RustFS (9000) — только с VPS 2 для выгрузки бэкапов
ufw default deny incoming && ufw default allow outgoing
ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp && ufw allow 443/udp
ufw allow from <внутренний IP VPS 2> to any port 9000 proto tcp
ufw enable

# VPS 2 (db): наружу только SSH; 5432 — только с внутреннего IP VPS 1
ufw default deny incoming && ufw default allow outgoing
ufw allow 22/tcp
ufw allow from <внутренний IP VPS 1> to any port 5432 proto tcp
ufw enable
```

Docker публикует порты в обход `ufw`: compose поэтому связывает `5432` (db.yml) и `9000` (prod.yml) с внутренними IP,
а не с `0.0.0.0` — после установки проверьте снаружи (`nmap -p 5432,9000 <публичный IP>` — закрыто).

### 1.2. Файл переменных

На VPS 1, от `deploy`, из клона/копии репозитория (достаточно каталога `infra/`):

```bash
infra/deploy/make-env-prod.sh init            # создаёт /opt/rt/.env.prod, секреты — случайные
nano /opt/rt/.env.prod                         # впишите вручную: APP_INTERNAL_IP, DB_INTERNAL_IP, ACME_EMAIL,
                                               # домены, TELEGRAM_*, ANTHROPIC_API_KEY/GEMINI_API_KEY, SMTP_*, BACKUP_EXT_*
(umask 077; infra/deploy/make-env-prod.sh extract-db > /tmp/env.db)    # часть для VPS 2 (файл с секретами — только для владельца)
scp /tmp/env.db deploy@<VPS 2>:/opt/rt-db/.env.db && shred -u /tmp/env.db
infra/deploy/make-env-prod.sh drop-db-only    # убрать с VPS 1 то, что нужно только VPS 2 (суперпользователь, ключи бэкапа)
```

`init` даёт обоим Redis разные случайные пароли (`REDIS_BROKER_PASSWORD`, `REDIS_CACHE_PASSWORD`). В `.env.prod`, созданном до S0-2, старая `REDIS_PASSWORD` больше
не читается: повторный `init` допишет две новые переменные (потом `drop-db-only`, как ниже), строку `REDIS_PASSWORD` можно удалить.

Сохраните офлайн копию обоих файлов и отдельно `BACKUP_ENC_PASSPHRASE`, `WAL_ENC_KEY` и `LITELLM_SALT_KEY` (потеря первой — потеря внешних копий
бэкапа; второй — потеря WAL-архива: восстановления на момент времени не будет; третьей — расшифровки ключей провайдеров в БД LiteLLM). После `drop-db-only` повторный `init` вернёт удалённые
переменные — на VPS 1 его запускать только для добавления новых и снова выполнять `drop-db-only`.

### 1.3. VPS 2: база

```bash
# каталог infra скопирован от deploy в /opt/rt-db/infra, /opt/rt-db/.env.db на месте (п. 1.2)
ssh root@<VPS 2> /opt/rt-db/infra/deploy/db-up.sh      # только от root: chown сертификата на uid 999
```

Скрипт создаёт сертификат TLS (самоподписанный, `sslmode=require`; проверка `verify-ca` — после пилота), `pg_hba.conf` с IP VPS 1,
собирает образ `postgres` со встроенным WAL-G (и проверяет, что `wal-g` стартует на CPU сервера), поднимает `postgres`, `walg` и `backup`, создаёт роли и базы (`crm`, `erp`, `litellm`, `langfuse`, `pgvector` в `crm`). Повторный запуск
безопасен и применяет смену паролей из `.env.db`. Проверка с VPS 1:
`docker run --rm -e PGPASSWORD=… -e PGSSLMODE=require pgvector/pgvector:0.8.7-pg17 psql -h <DB_INTERNAL_IP> -U crm_app -d crm -c 'select 1'`.

### 1.4. GitHub environment `production`

Settings → Environments → `production` (включить Required reviewers — владелец; с автозапуском деплоя после CI (п. 2) это единственный барьер между слиянием и продом, без него выкладка пойдёт без одобрения):

| Тип | Имя | Значение |
|---|---|---|
| Secret | `DEPLOY_SSH_KEY` | приватный ключ деплоя (пользователь `deploy` на VPS 1) |
| Secret | `DEPLOY_KNOWN_HOSTS` | вывод `ssh-keyscan -t ed25519 <публичный IP VPS 1>`, отпечаток сверен с консолью хостера |
| Variable | `DEPLOY_HOST` | публичный IP или имя VPS 1 |
| Variable | `DEPLOY_USER` | `deploy` |
| Variable | `CRM_DOMAIN`, `ERP_DOMAIN`, `CABINET_DOMAIN` | три домена |
| Variable | `PLATFORM_DOMAIN` | домен Платформы для smoke с раннера; необязательна — по умолчанию `platform.railtech.uz`. Сам домен для Caddy и `deploy.sh` берётся из `/opt/rt/.env.prod` на сервере |
| Variable | `TELEGRAM_BOT_USERNAME` | имя бота без `@` (не секрет; зашивается в образ Cabinet) |

## 2. Первый деплой и обычный деплой

### Как запускается деплой (W14-S4)

**Автоматически.** Workflow **Deploy** стартует сам, когда workflow **CI** завершился успешно на **push в `main`** (слитый PR). Ночной
прогон CI (`schedule`), ручной запуск CI и красный CI деплой не запускают. Дальше по шагам:

1. **`prepare`** (без секретов): `sha` = коммит, на котором прошёл CI; проверка, что он входит в `main`; проверка, что на нём **зелёная
   «CI ok»** (check-run; нет проверки или она не `success` — ошибка «деплой не идёт», образы не собираются).
2. **`build`**: восемь образов параллельно (по job'у на образ, кэш `type=gha,scope=<образ>`), push в GHCR с тегом = полный git sha.
   Без environment и без секретов — только `GITHUB_TOKEN`.
3. **`deploy`** — **ждёт одобрения владельца** (Required reviewers в environment `production`): собирает `rt-cabinet` (его build-args —
   variables `TELEGRAM_BOT_USERNAME` и `CRM_DOMAIN` из `production`, в job `build` их нет), загружает релиз на VPS 1, `deploy.sh`, smoke.
   Без одобрения ничего на сервер не попадает; отклонённый запуск — просто отменённый деплой.

Очередь: группа `deploy-production`, идущий запуск не отменяется. GitHub держит в группе один идущий и один ожидающий запуск: если пришёл
третий, ожидающий (старый) отменяется, остаётся самый новый. Запуски, которые ничего не деплоят (красный CI, schedule, режим `build`),
в эту группу не попадают и ожидающий деплой не вытесняют. Несколько слияний подряд: устаревший запуск, который уже ждёт одобрения,
не нужен — нажмите **Reject**, иначе следующий будет ждать его решения.

**Двойной запуск на один sha.** Два `workflow_run` подряд на один коммит (например, повторный прогон CI) встают в ту же очередь и выполняются по
очереди; второй не выкладывает то же самое повторно: шаг «Проверка - этот sha уже выложен?» читает `/opt/rt/state/current_tag` на VPS 1 и, если
там уже этот sha, пропускает сборку `rt-cabinet`, загрузку, `deploy.sh` и smoke (job зелёный, в журнале «повторная выкладка пропущена»). Пропуск
действует только для автозапуска: ручной `deploy` (`workflow_dispatch`) выкладывает всегда, так повторяют выкладку, у которой упал smoke
(`current_tag` выставляется до smoke). Нет связи по SSH — выкладка не пропускается.

**Автодеплой не выкладывает коммит старше выложенного.** Инцидент 2026-10-28: два слияния подряд (#278 → `22f10ec1`, затем #280 →
`536f4e65`) дали два автодеплоя; CI старшего коммита закончился позже, его деплой шёл вторым и выложил более старый релиз поверх нового.
Теперь тот же шаг проверки перед выкладкой (job `deploy`, checkout с полной историей) читает `current_tag` на VPS 1 и спрашивает
`infra/deploy/should-deploy.sh <sha> <current_tag>`: `deploy` (sha — потомок выложенного) выкладывает; `skip-same`
(тот же sha) и `skip-older` (sha — предок выложенного: «sha X старше или равен выложенному Y - пропуск») пропускают сборку `rt-cabinet`,
загрузку, `deploy.sh` и smoke, job зелёный; `skip-diverged` (sha и выложенный не в отношении предок/потомок или `current_tag` не разобрать)
пропускает с предупреждением `::warning::` — такое выкладывается только ручным запуском. Очередь `deploy-production` выстраивает запуски
целиком (prepare, build, deploy), поэтому второй запуск проверяет уже новый `current_tag` первого. Нет связи по SSH или `current_tag` пуст
(первая выкладка) — выкладка не пропускается. **Откат на более старый релиз и повтор выкладки — только ручным запуском** (`workflow_dispatch`,
`action = deploy` с нужным ref, либо `action = rollback`): ручной `deploy` решение скрипта лишь пишет в журнал (`::notice::`) и выкладывает
всегда. Одобрение `production` запрашивается и для запуска, который потом пропустится: устаревший запуск проще нажать **Reject**. Тест
логики: `infra/deploy/tests/should-deploy-test.sh` (на временном git-репозитории; входит в `make deploy-check`).

**Повторы при сбое сети к GHCR.** Обращения к `ghcr.io` на VPS 1 (`docker login` из `deploy.yml`, `compose pull` в `deploy.sh`, `rollback.sh`,
`reset-prod.sh`) идут через `retry` из `infra/deploy/lib.sh`: до 5 попыток с паузами 5, 10, 20, 40 с при любом коде выхода ≠ 0 (типичный сбой -
«net/http: TLS handshake timeout»). В журнале - метка и номер попытки, без аргументов команды и токена. После пятой неудачи поведение прежнее:
деплой падает (в `rollback.sh` pull по-прежнему необязателен - используются локальные образы). Тест: `infra/deploy/tests/retry-test.sh`
(входит в `make deploy-check`).

`workflow_run` читает `deploy.yml` из ветки по умолчанию, поэтому автозапуск работает только с версией файла в `main`.

**Вручную.** Actions → **Deploy** → Run workflow:

| `action` | `ref` | Что делает |
|---|---|---|
| `deploy` | `main` или sha, входящий в `main` | те же `prepare` (включая «CI ok» на sha), `build`, `deploy` с одобрением, что и автозапуск |
| `rollback` | не используется | откат на предыдущий тег (п. 3) |
| `build` | любой ref (ветка задачи) | только сборка всех девяти образов параллельно: **без push в GHCR**, без `production`, SSH и секретов; CI не проверяется. Нужен, чтобы замерить время сборки и убедиться, что образы собираются; прод не затрагивается |

Режим `build` не кладёт образы в реестр сознательно: тег — это sha коммита ветки, которого нет в `main`, а деплоится только слитый код;
кэш сборки при этом пишется (в область кэша ветки — на `main` он не влияет, ветка читает кэш `main`).

Порядок и сбои деплоя:

1. Сборка и push образов в GHCR (восемь в `build`, `rt-cabinet` в `deploy`); загрузка релиза на VPS 1.
2. `deploy.sh` на сервере. Если упал **pg_dump-гейт** — миграции не запускались, сервисы не тронуты; чините доступ к базе и запускайте снова.
3. Smoke с сервера и с раннера: `/health` CRM, ERP, Cabinet — 200, `/api/v1/health` Платформы — 200 и `status: ok`, `erp…/mcp/erp/`, `erp…/api/integration/v1/health`, `erp…/admin/` и `<платформа>/mcp/x` — 404.

На первом запуске Caddy получает сертификаты Let's Encrypt — DNS должен уже указывать на VPS 1, порты 80/443 открыты. После деплоя:

- свою компанию ERP создаёт мастер первого запуска (п. «Первый вход», FIX-65); `OWN_COMPANY_ID` вписывать не нужно — только если
  в базе окажется несколько компаний-продавцов с участниками;
- Telegram принимает отдельный сервис `crm-bot` (S0-4; `python -m app bot`, тот же образ `rt-crm-backend`, одна реплика, порт 8001 только
  внутри сети): Caddy отдаёт `/telegram/webhook` ему, а не `crm-api`; секретный заголовок проверяет он же. `crm-api` бота не запускает —
  его перезапуск бота не останавливает, и наоборот. Смена токена в «Подключениях» доходит до `crm-bot` через БД (до пары секунд), руками
  его перезапускать не нужно; режим (`TELEGRAM_MODE`) — только `.env.prod` и `up -d crm-bot`. При выкладке старый `crm-api` с ботом и новый `crm-bot` могут недолго работать вместе — кратковременный `409` от Telegram ожидаем. Подробности — `docs/runbooks/crm-bot.md`;
- Telegram-вебхук ставит `crm-bot` сам при `TELEGRAM_MODE=webhook`; адрес берётся из `CRM_DOMAIN` (`https://<CRM_DOMAIN>/telegram/webhook`,
  `prod.yml`), вписывать `TELEGRAM_WEBHOOK_URL` вручную не нужно — задавайте её, только если вебхук должен идти на другой https-адрес
  (явное значение переопределяет). Режим `webhook` с пустым или не-https адресом бота не запускает и вебхук не трогает: в журнале CRM
  `bot_webhook_not_configured`, в «Центре внешних сервисов» → Telegram — сбой «Вебхук Telegram не настроен» с подсказкой; там же
  фактический адрес вебхука и последняя ошибка доставки из `getWebhookInfo`. Если на VPS адрес был вписан вручную — после выкладки
  с этим изменением строку можно убрать из `.env.prod` (значение по умолчанию совпадёт);
- Ссылки в письмах сотрудникам (приглашение, сброс пароля; W15-H8a): «Вход: `<адрес Платформы>/login`». Адрес CRM берёт из `PLATFORM_PUBLIC_URL`
  (в `prod.yml` по умолчанию `https://${PLATFORM_DOMAIN}`, в dev — `http://platform.localhost:${HTTP_PORT}`), так что на проде отдельно ничего
  вписывать не нужно — `PLATFORM_DOMAIN` уже обязателен. `PLATFORM_PUBLIC_URL` в `.env.prod` — только переопределение (другая схема или
  порт). Там же `CRM_PUBLIC_URL` (`https://${CRM_DOMAIN}`) — значение по умолчанию «Настройки» → «Компания» → адрес CRM вместо `http://localhost`;
  адрес, заданный админом, не перетирается. Нет адреса Платформы — приглашение и сброс по почте отвечают 409, пароль не меняется. Адрес с `localhost`
  на проде (или не заданный) виден предупреждением в «Состоянии системы» → «Адреса для ссылок»;
- Langfuse (`RT_PROFILES=observability` в `.env.prod`) открывается SSH-туннелем: `ssh -L 3000:127.0.0.1:3000 deploy@<VPS 1>`;
  docling на проде **не используется** (M5-CRM-02): `DOCLING_URL` в `prod.yml` пуст. База знаний принимает только Markdown по
  `docs/kb/FORMAT.md` (готовит человек или ИИ-агент по `docs/kb/PROMPT.md`) и индексирует его встроенным конвертером CRM; docling
  в базе знаний не участвует вовсе. Остался только для текста документов клиентов (при пустом `DOCLING_URL` он помечается `failed`);
  профиль `kb-ingest` — опция для этого (вернуть `DOCLING_URL=http://docling:5001` и `DOCLING_API_KEY`), вместе с Langfuse не включать (8 ГБ).

**Бот в сервисном режиме требует `erp-mcp` (M3-CRM-07).** `erp-mcp` (инструменты ERP для агента CRM) лежит под профилем `mcp`; бот
берёт из него данные клиента («где мой счёт», «когда поставка», цена клиенту) и без него на такие вопросы честно отвечает «не могу
проверить» и заводит запрос менеджеру. Поэтому на проде профиль включён: в `infra/.env.prod.example` стоит `RT_PROFILES=mcp`, а в
уже созданном `/opt/rt/.env.prod` его добавляют вручную (`RT_PROFILES=mcp`, через запятую с остальными, например
`mcp,observability`; вместе с `observability` и `kb-ingest` 8 ГБ хватает не на все три — `erp-mcp` занимает ≈ 200 МБ). Затем обычный
деплой; снаружи `/mcp` остаётся 404 (smoke). Ключ `ERP_MCP_CONTEXT_KEY` один на CRM и ERP: им CRM подписывает контекст каждого
вызова, `erp-mcp` его проверяет (значение уже в `.env.prod`). Файл контракта едет в релизе: `/opt/rt/releases/<sha>/packages/contracts/
mcp-tools.json` монтируется в контейнер по пути `../../packages/contracts/mcp-tools.json` от `prod.yml` (без файла сервис не стартует).
Проверить после деплоя: `docker compose ps erp-mcp` — `healthy`; в логе CRM нет `erp_mcp_call_failed` с `kind=context_rejected` (это
расхождение ключей между CRM и ERP) и нет `kind=unavailable` (сервис не запущен — профиля нет в `RT_PROFILES`). Выключить ходы бота к ERP,
не останавливая `erp-mcp`: `ERP_MCP_ENABLED=false` в `.env.prod`.

**Схемы событий и подписки шины (B3, L14; раньше M5-INF-01c).** Каталог контрактов `packages/contracts/events` и
`packages/contracts/bus` вшит в образ ERP (`/opt/rt/contracts`, `RT_BUS_CONTRACTS_DIR`, `RT_BUS_SUBSCRIPTIONS`): образ собирают
`deploy.yml` и compose с именованными контекстами `rtbus` и `contracts`, монтирований схемы из релиза и проверки файла в
`deploy.sh` больше нет (`events.schema.json` снят). Тело каждого события шина проверяет строго до записи в outbox — несоответствие
это ошибка операции, а не строка в логе. Проверить после деплоя: `docker compose exec erp-backend ls /opt/rt/contracts/events/erp`
(22 схемы), `docker compose exec erp-backend python manage.py bus_retry --metrics`; порядок эксплуатации — `rt-bus-erp.md`.

Вручную с сервера (без Actions): `/opt/rt/releases/<sha>/infra/deploy/deploy.sh <sha>`; без миграций и дампа — `make up-prod RT_IMAGE_TAG=<sha>`.

### Django admin ERP и машинный API ERP — без внешнего маршрута (S0-5)

Caddy (`no_erp_internal` в `Caddyfile.prod`/`Caddyfile.dev`) отвечает 404 на `/api/integration`, `/api/integration/*`, `/admin`, `/admin/*`
домена ERP; через домены Cabinet и Платформы эти пути до `erp-backend` тоже не доходят (маршруты только `/api/portal/*`, `/media/*` и SPA/BFF).
`/api/v1/admin/...` (API шаблонов писем и т. п.) — это API ERP, оно работает как раньше. Smoke деплоя (`infra/deploy/smoke.sh`) и
`make deploy-check` (`infra/deploy/tests/caddy-edge-test.sh`) проверяют это.

* **Кто ходит в `/api/integration`.** Только CRM и коннекторы — по внутренней сети compose, `http://erp-backend:8000` (адрес подставляет
  «Подключить ERP»; `crm-erp-pairing.md`). Внешний адрес ERP в «Подключениях» для этого не годится — он даст 404. Сопряжение CRM с ERP
  на **другом сервере** требует внутренней связи между серверами (частная сеть/VPN, адрес ERP — частный IP или имя без точки; ADR-0009 это
  допускает, внешний `https://erp…` для `/api/integration` — нет).
* **Попасть в Django admin (Unfold).** SSH-туннель к контейнеру `erp-backend` (порт наружу не публикуется), на VPS 1 из каталога релиза:
  ```bash
  # 1) адрес контейнера erp-backend в сети compose
  docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$(docker compose … ps -q erp-backend)"
  # 2) на своей машине (подставьте адрес из п. 1)
  ssh -L 8000:<адрес контейнера>:8000 deploy@<VPS 1>
  ```
  Откройте `http://localhost:8000/admin/` (`localhost` разрешён в `ALLOWED_HOSTS` и `CSRF_TRUSTED_ORIGINS` ERP). Cookie сессии на проде
  помечены `Secure`: Chrome и Firefox принимают их на `http://localhost`, Safari может не принять (используйте другой браузер или команду ниже).
  Закончив, закройте туннель.
* **Команды без браузера:** `docker compose … exec erp-backend python manage.py <команда>` (`shell`, `pairing_code`, `pairing_close_bootstrap`).
* **Повтор `dead`-доставок шины** — `manage.py bus_retry --all-dead --subscriber crm` либо действие админки (rt_bus → Delivery) через туннель:
  `docs/runbooks/rt-bus-erp.md`.
* **Откат на релиз до S0-5:** его Caddy ещё отдаёт `/admin/` и `/api/integration` наружу, поэтому smoke отката (404 на этих путях) будет красным,
  хотя откат выполнен; это ожидаемо, повторный деплой текущего релиза закрывает пути.

## 3. Откат

- **Код:** Actions → Deploy → Run workflow → `action` = `rollback` (откат тоже идёт через `production` и требует одобрения;
  CI и сборка не нужны) или на VPS 1: `/opt/rt/current/infra/deploy/rollback.sh [sha]`. Поднимает
  предыдущий тег (`state/previous_tag`) с конфигурацией того релиза. **Миграции не откатываются**: откат безопасен, пока
  миграции отменяемого релиза обратно совместимы со старым кодом. Если нет — восстановление данных (п. 4) решает владелец.
- **Перед откатом отклоните (Reject) ожидающие одобрения деплои.** Rollback делит группу `deploy-production` с автодеплоями: пока
  в группе идёт или ждёт одобрения деплой, rollback встанет в очередь, а ожидающий rollback может быть вытеснен следующим автозапуском
  (из ожидающих GitHub оставляет только самый новый). Откатываем — значит, ждущие выкладки не нужны.
- Предмиграционные дампы последних пяти деплоев — `/opt/rt/state/predeploy/<sha>-<время>/{crm,erp,eds}.dump`.

## 4. Бэкапы и восстановление

- **WAL-архив и восстановление на момент времени (S0-3, ADR-0017):** `postgres` на VPS 2 непрерывно шлёт журнал транзакций (`archive_timeout` 60 с → RPO ≤ 5 мин)
  в бакет `wal` RustFS на VPS 1, сервис `walg` ежедневно делает базовую копию (21:00 UTC), хранит 14 дней, при заданном `BACKUP_EXT_*` копирует архив во внешнее S3
  и раз в месяц проверяет восстановление; сбой виден как `unhealthy` у контейнера `walg`. Восстановление на любой момент последних 14 суток в отдельный контейнер —
  `infra/db/restore-pitr.sh --target-time "YYYY-MM-DD HH:MM:SS+00"`. Подробно (включение, где лежат копии, переключение, ключ `WAL_ENC_KEY`, ротация,
  заполнение бакета) — `docs/runbooks/backup-pitr.md`. Ежедневный `pg_dump` ниже остаётся вторым рубежом.
- **Расписание:** контейнер `backup` на VPS 2 ежедневно в 22:00 UTC (03:00 Ташкент) делает `pg_dump` каждой базы, проверяет читаемость
  (`pg_restore -l`), хранит `BACKUP_KEEP_DAYS` (14) дней в `/var/backups/rt/<UTC-штамп>/`, выгружает в бакет `backups` RustFS
  на VPS 1 (ежедневно) и **зашифрованную** (AES-256, `BACKUP_ENC_PASSPHRASE`) копию во внешнее S3-хранилище (раз в неделю,
  `BACKUP_EXT_DAY`). Адрес и ключи внешнего хранилища — переменные `BACKUP_EXT_*`; провайдера выбирает владелец.
- **Сейчас:** `infra/deploy/backup-now.sh [--ext]` на VPS 2.
- **Статус в CRM:** «Внешние сервисы» → «Хранилище резервных копий» читает бакет `backups` RustFS (M5-CRM-01); нет копии за 26 ч — инцидент и оповещение. Подробно — `docs/runbooks/crm/backup-restore.md`.
- **Проверка восстановления** (раз в неделю и после любых изменений бэкапа): `infra/db/restore-check.sh [каталог]` на VPS 2 — разворачивает
  каждый дамп во временную базу, считает таблицы, проверяет `vector` в `crm`, удаляет базу. Боевые базы не затрагиваются.
- **Восстановление боевой базы** (остановка записи обязательна):
  ```bash
  # VPS 1: остановить приложения, ходящие в базу
  docker compose -f … stop crm-api crm-bot crm-worker crm-mcp-kb crm-mcp-crm crm-mcp-docs erp-backend erp-mcp erp-worker erp-worker-ai erp-beat
  # VPS 2: пересоздать базу и залить дамп (пример для erp)
  docker exec -u postgres rt-db-postgres-1 psql -U postgres -c 'DROP DATABASE erp' -c 'CREATE DATABASE erp OWNER erp_app'
  docker exec -i -u postgres rt-db-postgres-1 pg_restore -U postgres -d erp --no-owner --role=erp_app < /var/backups/rt/<штамп>/erp.dump
  # VPS 1: запустить приложения (deploy.sh <текущий sha> или rollback.sh), smoke
  ```
  Для `crm` после восстановления проверьте, что расширение `vector` на месте (`restore-check.sh` это делает). Внешнюю копию сначала
  расшифровать: `openssl enc -d -aes-256-cbc -pbkdf2 -in crm.dump.enc -out crm.dump -pass env:BACKUP_ENC_PASSPHRASE`.
- Файлы клиентов (RustFS на VPS 1, том `s3_data`) этим бэкапом **не** покрыты — только базы. Копирование бакетов вне VPS 1 — хвост (стратегия A2,
  внешнее хранилище даёт владелец).
- **Файлы ERP — в бакетах RustFS** (S0-1): PDF КП, договоров, счетов, актов, сканы и загрузки портала — `erp-private`; картинки каталога,
  логотипы, аватары — `erp-public`; временные — `erp-temp`. Тома `erp_media` и папки `/app/media` с файлами в контейнерах ERP нет: потеря
  тома `s3_data` = потеря файлов ERP, поэтому бакеты `erp-*` входят в будущую копию вне VPS 1 наравне с `backups`. Порт RustFS наружу не открыт
  (только внутренний IP для VPS 2), браузер в него не ходит: приватные файлы ERP отдаёт потоком (после проверки доступа), публичные
  картинки — Django по `/media/*` доменов ERP и Cabinet. Запуск ERP без `MINIO_ENDPOINT`/`MINIO_ACCESS_KEY`/`MINIO_SECRET_KEY` вне
  `DJANGO_DEBUG=true` останавливается с `ImproperlyConfigured` (молча писать на диск контейнера нельзя). Ключ у ERP свой — `S3_ERP_*`, только бакеты
  `erp-*` (раздел «Ключи S3 на сервис» ниже). Проверка: `docker compose … exec erp-backend sh -c 'ls /app/media | wc -l'` — 0; листинг бакета —
  `infra/deploy/tests/s3-keys-live-test.sh` (там же проверка, что чужие бакеты закрыты).
- **Что публично в `/media`, что нет** (S0-9): `/media/*` доменов ERP и Cabinet отдаёт только белый список ключей `erp-public` — аватары (`users/<id>/avatar`),
  логотипы компаний (`companies/<id>/logo`) и профиля документов (`companies/<id>/doc-profile/logo`: печатается в КП и договорах, показывается в кабинете),
  логотипы производителей, фото товаров, иконки категорий. Всё остальное, включая **документы товаров** (`products/<id>/docs/*`, бакет `erp-private`), через
  `/media` не открывается (404): сотрудник скачивает документ товара через `GET /api/v1/catalog/products/{id}/download-document/{doc_id}/` (вход + видимость карточки).
- **Отдача файлов потоком** (S0-9): файл из RustFS читается порциями по 256 КиБ и сразу уходит клиенту — ни в память процесса, ни на диск он целиком не попадает
  (раньше скачивание 40 МБ занимало ≈ 3× размера в памяти Daphne). Заголовки `Content-Length` и `Content-Disposition` прежние. Про остаток — «Хвосты» в PR S0-9.

### Ключи S3 на сервис (S0-9, ADR-0013 п. 6)

Раньше ERP, CRM, Langfuse, WAL-G и бэкап ходили в RustFS одним ключом. Теперь у каждого свой пользователь и политика, корневой ключ знают только `rustfs` и `s3-init`:

| Сервис | Переменные `.env.prod` | Доступ |
|---|---|---|
| корень | `S3_ROOT_ACCESS_KEY`, `S3_ROOT_SECRET_KEY` | только RustFS и `s3-init` (создание бакетов, пользователей, правил) |
| ERP | `S3_ERP_*` (в контейнерах — `MINIO_ACCESS_KEY/SECRET_KEY`) | запись `erp-private`, `erp-public`, `erp-temp` |
| CRM | `S3_CRM_*` (в контейнерах — `S3_ACCESS_KEY/SECRET_KEY`) | запись `kb-sources`, `client-documents`, `tg-attachments`; **чтение** `backups` (статус бэкапа) |
| EDS | `S3_EDS_*` (в контейнерах — `S3_ACCESS_KEY/SECRET_KEY`) | запись `eds-private` (документы EDS; файлы появятся с доменом, E3) |
| Langfuse | `S3_LANGFUSE_*` | запись `langfuse` |
| WAL-G (VPS 2) | `S3_WAL_*` → копия `WAL_S3_ACCESS_KEY/SECRET_KEY` | запись `wal` |
| бэкап дампов (VPS 2) | `S3_BACKUP_*` → копия `BACKUP_RUSTFS_ACCESS_KEY/SECRET_KEY` | запись `backups` |

- **Генерация.** `make-env-prod.sh init` создаёт все ключи случайными, на экран не печатает и дописывает недостающие в существующий файл. Копии для VPS 2
  (`WAL_S3_*`, `BACKUP_RUSTFS_*`) он выставляет равными `S3_WAL_*` и `S3_BACKUP_*` при каждом запуске; `extract-db` отдаёт на VPS 2 только их — корневого
  ключа и ключей ERP/CRM/Langfuse там нет. Только ключи S3, не трогая остальное (и не возвращая переменные VPS 2, убранные `drop-db-only`), создаёт
  `make-env-prod.sh s3-keys`; именно его вызывает `reset-prod.sh` (S0-8) на шаге 0. Четыре строки для VPS 2 из ключей сервисов печатает
  `make-env-prod.sh extract-s3` (работает и после `drop-db-only`; вывод — в файл, он содержит секреты).
- **Создание пользователей.** Одноразовый `s3-init` (`infra/s3/init.sh`, образ `rustfs/rc` с закреплёнными версией и digest) при **каждом** деплое: создаёт бакеты,
  обновляет политики `rt-<сервис>` и пользователей, удаляет пользователей, которых нет в списке, ставит правило `erp-temp` и проверяет матрицу доступа реальными запросами
  под ключом каждого сервиса (чужой бакет доступен, запись в `backups` у CRM открыта — деплой останавливается с ошибкой). Остальные сервисы ждут `s3-init`.
- **Обновление существующего прода** (`.env.prod` до S0-9): `make-env-prod.sh s3-keys` делает прежний `S3_ACCESS_KEY/S3_SECRET_KEY` корневым `S3_ROOT_*` (корень
  не меняется — RustFS и VPS 2 со старой копией ключа работают без перерыва), удаляет старые строки и генерирует ключи сервисов. Порядок: `s3-keys` → деплой (`s3-init` заведёт
  пользователей; ERP, CRM и Langfuse переходят на свои ключи) → `extract-s3 > /tmp/s3.env` → заменить такие же строки в `/opt/rt-db/.env.db` на VPS 2 → `db-up.sh`
  (WAL-G и бэкап переходят на свои ключи) → `shred -u /tmp/s3.env`. До этого VPS 2 ходит старым (теперь корневым) ключом — работает, но с лишними правами.
- **Ротация ключа сервиса.** Поменять `S3_<СЕРВИС>_SECRET_KEY` (или оба значения) в `.env.prod` →
  деплой (`s3-init` обновит пользователя, старый секрет перестаёт действовать сразу; смена идентификатора удаляет прежнего пользователя; ERP/CRM/Langfuse подхватят новый
  ключ при пересоздании контейнеров этим же деплоем) → для `wal` и `backup` дальше `extract-s3` → `.env.db` на VPS 2 → `db-up.sh`. Корневой ключ меняется так же, но требует
  перезапуска `rustfs`. Проверено на стенде: старый секрет — 403, новый — 200, лишний пользователь удалён.
- **Правило `erp-temp`**: объекты старше **1 суток** удаляются сервером (правило `rt-erp-temp-expire-1d` ставит `s3-init`; импорт правила заменяет набор целиком, повтор ничего не
  дублирует). Посмотреть: `docker compose … run --rm --entrypoint sh s3-init -c 'rc alias set r http://rustfs:9000 "$S3_ROOT_ACCESS_KEY" "$S3_ROOT_SECRET_KEY" >/dev/null; rc bucket lifecycle rule list r/erp-temp'`.
  Срабатывание зависит от сканера RustFS (проходит не мгновенно); в `erp-temp` лежит только промежуточное — важного там быть не должно.
- **Проверка доступа руками** (на стенде, после `up`): `infra/deploy/tests/s3-keys-live-test.sh <проект compose> <файл env>` — независимым клиентом (curl SigV4) проверяет, что
  ключом ERP нельзя читать `wal` и бакеты CRM, ключом CRM — бакеты ERP, а свои бакеты читаются.

## 5. Что где проверять

| Симптом | Куда смотреть |
|---|---|
| Сайт не открывается / нет сертификата | `docker compose … logs caddy`; DNS, порты 80/443; лимит выпусков Let's Encrypt |
| `pg_dump-гейт` падает | доступ VPS 1 → VPS 2:5432 (`ufw`, `pg_hba`, `DB_INTERNAL_IP`, пароль роли), `docker logs rt-db-postgres-1` на VPS 2 |
| ERP/CRM не стартуют после деплоя | `docker compose … logs erp-backend crm-api crm-bot`; `ps` — какие контейнеры не healthy |
| Redis: ERP в журнале «Кэш (Redis) недоступен», сессии Платформы не работают, очередь стоит | «Redis: брокер и кэш раздельно» ниже: `docker compose … ps redis-broker redis-cache`, `logs`, `redis-cli ping` |
| Бэкап не создаётся | `docker logs rt-db-backup-1` на VPS 2, `/var/backups/rt/last_success`, healthcheck контейнера `backup` |
| WAL-архив: `walg` unhealthy, `archive command failed` | `docker inspect --format '{{json .State.Health}}' rt-db-walg-1`, `docker exec -u postgres rt-db-walg-1 rt-pitr status`, `docker logs rt-db-postgres-1` — `docs/runbooks/backup-pitr.md`, разделы 4–5 |
| Не хватает памяти | `docker stats`; профили `observability` и `kb-ingest` не включать вместе |

Эскалация: владелец; агент Infra — правки compose/Caddy/скриптов через PR.

## Redis: брокер и кэш раздельно (S0-2)

Один Redis делили очередь задач, кэш, сессии Платформы и Langfuse; кэш без игнорирования ошибок ронял ERP вместе с собой. Теперь два экземпляра
(`infra/compose/base.yml`, лимиты памяти — `prod.yml`, `servers.md`), у каждого свой пароль:

| | `redis-broker` | `redis-cache` |
|---|---|---|
| Что хранит | брокер и результаты Celery ERP (БД 1), Channels ERP (БД 2), очереди Langfuse — BullMQ (БД 3, S0-9) | кэш Django, троттлинг DRF, блокировка входа, одноразовые `jti` SSO/привязки/MCP и метки 2FA ERP (БД 0); сессии BFF Платформы (БД 3) |
| Пароль (`.env.prod`) | `REDIS_BROKER_PASSWORD` | `REDIS_CACHE_PASSWORD` |
| Политика | `appendonly yes` (`everysec`), `noeviction`, `maxmemory` 128 МБ (`REDIS_BROKER_MAXMEMORY`) | `volatile-lru`, `maxmemory` 96 МБ (`REDIS_CACHE_MAXMEMORY`), RDB-снимок раз в 5 минут |
| Том | `redis_broker_data` (AOF) | `redis_cache_data` (снимок) |
| Лимит контейнера | 256 МБ | 192 МБ |

У всех ключей кэша есть срок жизни: вытесняются только ключи со сроком (`volatile-lru`); тест `core/tests/test_cache_resilience.py` не даёт записать в кэш ключ без срока.
Langfuse (BullMQ) требует `noeviction`, поэтому его очереди живут на `redis-broker` (БД 3, отдельно от Celery и Channels) — предупреждение «Eviction policy is volatile-lru» ушло.
Цена: очередь Langfuse делит с Celery лимит `maxmemory` брокера (128 МБ); при переполнении запись упрётся в `OOM` у обоих, а не потеряет данные молча. Следить за `used_memory`
брокера, пока Langfuse включают профилем `observability`; если очередь Langfuse разрастётся — поднять `REDIS_BROKER_MAXMEMORY` (и лимит контейнера в `prod.yml`).

**Что происходит при отказе `redis-cache`** (остановка, переполнение, сеть):

- ERP работает без кэша: ответы API 200, в журнале `erp-backend` одно предупреждение «Кэш (Redis) недоступен, ERP работает без кэша» раз в 30 секунд (и «снова доступен»
  при восстановлении); первые секунды запросы чуть медленнее (таймаут подключения 1 с, затем 5 секунд ERP вообще не обращается к кэшу). Троттлинг и блокировка входа по числу
  попыток на это время пропускают запросы; пароль и код 2FA проверяются как обычно. `/health/` ERP остаётся 200, `healthy` контейнера не меняется: `erp-backend` ждёт кэш только
  по запуску (`service_started`), на его отказ не перезапускается. Поле `queue_alive` health интеграции теперь про брокер, а не про кэш.
- Вход по SSO из CRM, привязка ERP к CRM по доказательству и вызовы `erp-mcp` — **отказ, а не пропуск**: одноразовый `jti` негде запомнить. SSO отвечает 503
  `SSO_TEMPORARILY_UNAVAILABLE` с текстом «Проверка одноразового токена временно недоступна… Повторите попытку через минуту» (токен не погашен, живёт свои 60 с); второй шаг входа с 2FA — 503
  `2FA_TEMPORARILY_UNAVAILABLE`; MCP и привязка — 503 `SERVICE_TEMPORARILY_UNAVAILABLE`. Вход по паролю без 2FA работает.
- Платформа: сессии лежат в `redis-cache`, поэтому вход и все запросы с сессией дают 503 `BACKEND_UNAVAILABLE` (не 500), `/api/v1/health` — `degraded` с `redis: fail`;
  после возврата кэша сессии, не вытесненные и не потерянные с ним (снимок раз в 5 минут, при полной потере — вход заново), снова работают.

**Что при отказе `redis-broker`:** задачи Celery не ставятся и не берутся (письма, PDF, импорты, доставка вебхуков в CRM — ERP при этом отвечает на запросы, но `queue_alive=false`,
интеграционный `/health` 503); события в журнале `IntegrationWebhookEvent` не теряются (повторная постановка — beat). После рестарта очередь на месте (AOF).

**Диагностика:**

```bash
cd /opt/rt/current/infra/compose
dc() { docker compose -f base.yml -f prod.yml --env-file /opt/rt/.env.prod "$@"; }
dc ps redis-broker redis-cache                                   # оба healthy
dc exec redis-broker redis-cli info memory | grep -E 'used_memory_human|maxmemory_human'   # пароль подставляет REDISCLI_AUTH
dc exec redis-broker redis-cli -n 1 llen default                 # длина очереди default (ai, pdf, imports — те же llen)
dc exec redis-broker redis-cli info persistence | grep aof_       # aof_enabled:1, aof_last_write_status:ok
dc exec redis-cache redis-cli info stats | grep evicted_keys     # вытеснения: рост = кэш мал, поднять REDIS_CACHE_MAXMEMORY и лимит
dc exec redis-cache redis-cli -n 0 dbsize
dc logs --since 10m erp-backend | grep -E 'Кэш \(Redis\)'      # предупреждения ERP о кэше
```

Кэш можно очистить без последствий (кроме выхода всех из Платформы и забытых меток `jti` на 10 минут): `dc exec redis-cache redis-cli flushall`. Брокер — **нет**: `flushall` на нём теряет очередь.
Старый том `rt-platform_redis_data` и контейнер `redis` после перехода не нужны: контейнер уберёт `--remove-orphans`, том — `docker volume rm rt-platform_redis_data` (на проде данных в нём нет — сброс по S0-8).

## Платформа (INF-P0-5)

Единое рабочее место сотрудника (`apps/platform`): BFF `platform-bff` (FastAPI, `redis-cache` БД 3 — сессии) и статика `platform-web`
за тем же Caddy, домен `platform.railtech.uz`. Нового секрета и базы у Платформы нет. Образы `rt-platform-bff`, `rt-platform-web`
собирает тот же `deploy.yml` (тег = sha), на VPS 1 они занимают ≈ 256 МБ + 64 МБ (лимиты в `prod.yml`).

> **Внимание.** После слияния INF-P0-5 ЛЮБОЙ деплой (в том числе не связанный с Платформой) остановится в `deploy.sh`, пока в
> `/opt/rt/.env.prod` нет `PLATFORM_DOMAIN`. Если `PLATFORM_DOMAIN` задан, а DNS-записи нет, деплой покраснеет на smoke после `up`
> (сервисы при этом работают). Поэтому порядок такой: A-запись, затем строка в `.env.prod`, затем деплой.
> Caddy ждёт `healthy` у всех сервисов, включая `platform-bff` и `platform-web`: не стартовавший образ Платформы не даст Caddy
> подняться и уронит ВСЕ домены, а не только Платформу.

**Перед первым деплоем Платформы (владелец):**

1. **DNS.** A-запись `platform.railtech.uz` → публичный IP VPS 1 (как у `crm.`, `erp.`, `cabinet.`). Сначала запись, потом деплой: без неё
   Caddy не пройдёт проверку Let's Encrypt, а повторы быстро упираются в лимит выпусков. Проверка: `dig +short platform.railtech.uz`.
2. **Переменная.** В `/opt/rt/.env.prod` на VPS 1 добавить строку: `echo 'PLATFORM_DOMAIN=platform.railtech.uz' >> /opt/rt/.env.prod`
   (повторный `make-env-prod.sh init` тоже допишет её, но вернёт и переменные VPS 2 — после него нужен `drop-db-only`, см. §1.2).
   `deploy.sh` останавливается с понятным сообщением до pull и миграций, пока строки нет. `PLATFORM_SESSION_TTL_HOURS` (часы жизни сессии, по умолчанию 12) —
   необязательна, закомментирована в примере.
   Так же необязательны `PLATFORM_ERP_REFRESH_COOKIE` (имя refresh-cookie ERP, по умолчанию `refresh_token`) и `PLATFORM_LOGIN_RATE_PER_MINUTE`
   (неудачных попыток входа в минуту, по умолчанию 10), `PLATFORM_CRM_TIMEOUT_SECONDS` (таймаут CRM в BFF, по умолчанию 5) и
   `PLATFORM_TRUSTED_PROXIES` (прокси, которым BFF верит в `X-Forwarded-For`; по умолчанию частные сети compose),
   `PLATFORM_CRM_PUBLIC_URL` и `PLATFORM_ERP_PUBLIC_URL` (адреса старых фронтов для кнопок моста; по умолчанию BFF выводит их из `platform.<домен>`). `PLATFORM_COOKIE_SECURE` на проде не настраивается: `prod.yml` жёстко ставит `true`, на http-стенде
   `dev.yml` ставит `false`.
   Если перед Caddy появится CDN или прокси (например, Cloudflare), настройте в Caddy `trusted_proxies` (иначе весь трафик придёт с одного адреса) и сузьте
   `PLATFORM_TRUSTED_PROXIES` до подсети compose: иначе IP-лимит входа начнёт блокировать всех сотрудников разом.
3. **GitHub environment `production`** — ничего обязательного; необязательная Variable `PLATFORM_DOMAIN` (§1.4) нужна, только если
   домен отличается от `platform.railtech.uz`: по ней smoke с раннера ходит на Платформу.
4. **Деплой** — обычный (§2): Actions → Deploy → `ref` = `main`, `action` = `deploy`. Не запускать, пока в `main` вливается PR (§6, гонка).

**Проверка после деплоя:**

- `curl -fsS https://platform.railtech.uz/api/v1/health` — ответ `200` и `"status":"ok"`: BFF видит `redis-cache`, CRM `/health` и ERP `/health`.
  `"status":"degraded"` при живых CRM и ERP — смотреть в теле поле `checks` (`redis`, `crm`, `erp` — `ok`/`fail`; схема `Health` в
  `packages/contracts/openapi/platform-bff.yaml`), затем `docker compose … logs platform-bff` и `docker compose … ps` (`platform-bff`,
  `platform-web` — `healthy`). BFF отвечает `200` всегда, `degraded` не ошибка запуска, но smoke деплоя считает его сбоем.
- `https://platform.railtech.uz/` открывает страницу каркаса «Платформа — каркас P0» (до фазы P1 входа нет); `/mcp/x` снаружи — 404.
- Сертификат выпущен автоматически (Caddy); при сбое — `docker compose … logs caddy`, DNS, порты 80/443.

**Откат.** `rollback.sh` берёт список сервисов из compose релиза, на который откатываемся: откат на тег до Платформы убирает её
контейнеры (`--remove-orphans`) и не проверяет её домен; на тег с Платформой — тянет оба образа и проверяет `/api/v1/health`.
Smoke с раннера в задании `rollback` устроен так же: домен Платформы добавляется к трём, если в `base.yml` релиза отката есть `platform-bff`.

**Сбой Платформы не должен лишать входа остальных (INF-P1-0).** Caddy зависит от `platform-bff` и `platform-web` по `service_started`,
не `service_healthy`: упавший BFF или SPA Платформы дают `502` только на её домене, CRM, ERP и Cabinet отвечают. `deploy.sh` и
`rollback.sh` поднимают стек функцией `up_stack` (`infra/deploy/lib.sh`): сначала всё, кроме Платформы, затем Платформа отдельно —
её сбой (даже ошибка запуска контейнера) только предупреждение в журнале. Итог по Платформе — четвёртый домен в smoke: деплой при
этом красный, CRM, ERP и Cabinet уже работают; чинить Платформу и повторить деплой (или `rollback.sh`).

## EDS — сервис документооборота (волна 12, E2)

Отдельный сервис `apps/eds` (FastAPI, SQLAlchemy 2, Alembic, Procrastinate; ADR-0015): образ `rt-eds`, три сервиса compose — `eds-api`, `eds-worker`,
`eds-migrate` (один образ; лимиты 256 МБ у `eds-api` и 192 МБ у `eds-worker`, факт гейта C1 ≈ 110 и 95–100 МиБ — C1-G-8, `eds-migrate` одноразовый). **Внешнего маршрута нет**: Caddyfile.prod на EDS не ведёт
ни с одного домена, порты наружу не публикуются; сотрудники придут через BFF Платформы (этап D), системы — по шине `rt_bus`
(`http://eds-api:8000/bus/v1/events` внутри сети compose). Устройство и команды — `docs/systems/eds/README.md`.

**Что нужно на проде до первого деплоя с EDS** (всё — без значений в репозитории):

1. **VPS 1, `/opt/rt/.env.prod`.** `make-env-prod.sh init` на сервере дописывает недостающее и генерирует секреты (на экран не печатает): `DB_EDS_PASSWORD`,
   `EDS_ACCESS_SECRET`, ключ S3 `S3_EDS_ACCESS_KEY` / `S3_EDS_SECRET_KEY` (раздел «Ключи S3 на сервис»), секреты пар шины `RT_BUS_SECRET_CRM_EDS`,
   `RT_BUS_SECRET_ERP_EDS`, `RT_BUS_SECRET_EDS_ERP`, `RT_BUS_SECRET_EDS_PLATFORM_BFF`; пустой `RT_BUS_ENDPOINT_EDS` — переопределение адреса, нужно редко.
   Общий `PLATFORM_SSO_SECRET` уже есть (его проверяет и EDS: токен сотрудника с `aud=eds`). После `init` вернувшиеся переменные VPS 2 уберите `drop-db-only` (§1.2).
2. **VPS 2: база `eds` и роль `eds_app`.** Новый пароль надо передать на VPS 2: `make-env-prod.sh extract-db > …` (или вручную дописать `DB_EDS_PASSWORD` в
   `/opt/rt-db/.env.db`), затем под root `infra/deploy/db-up.sh` — он идемпотентно выполняет `infra/db/prod-init.sh` (роль `eds_app`, база `eds`, `REVOKE CONNECT` чужим
   ролям, `rt_backup` читает), пересобирает `pg_hba.conf` (строка `hostssl eds eds_app <внутренний IP VPS 1>/32`) и перечитывает конфигурацию. Новая переменная в окружении `postgres` пересоздаёт его контейнер — PostgreSQL перезапустится на секунды, приложения переподключатся.
   Бэкап (`DB_NAMES`), WAL-G и проверка восстановления уже включают `eds`. Проверка с VPS 1:
   `docker run --rm -e PGPASSWORD=… -e PGSSLMODE=require pgvector/pgvector:0.8.7-pg17 psql -h <DB_INTERNAL_IP> -U eds_app -d eds -c 'select 1'`.
3. **Бакет `eds-private` и ключ.** Ничего вручную: `s3-init` создаёт бакет и пользователя с политикой `rt-eds` (чтение и запись только `eds-private`) при каждом деплое и
   проверяет, что чужие бакеты ему закрыты. Если `S3_EDS_*` нет в `.env.prod`, compose не разбирается — `make-env-prod.sh s3-keys` дописывает ключ.
4. **Деплой** — обычный (§2). Порядок: pg_dump-гейт теперь снимает и `eds` (нет роли или базы — дамп падает и миграции не идут: это сигнал, что п. 2 не выполнен) →
   `eds-migrate` → `up` → ожидание `healthy` у `eds-api` и `eds-worker` (до 120 с каждый). Образ `rt-eds` входит в проверку базы CPU (`cpu-baseline-check.sh`) и в задание `cpu-image`.

**Проверка после деплоя.** `docker compose -f /opt/rt/current/infra/compose/base.yml -f /opt/rt/current/infra/compose/prod.yml --env-file /opt/rt/.env.prod ps eds-api eds-worker` —
оба `healthy`; изнутри сети: `docker compose … exec eds-api python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/health').read())"` → `{"status":"ok",…,"checks":{"database":"ok"}}`.
Снаружи любые пути на всех доменах — 404 или ответ чужого сервиса: EDS в Caddy нет (проверяет `infra/deploy/tests/eds-prod-test.sh`, `make deploy-check`).
Очереди и шина: `docker compose … exec eds-api python -m app bus status` (метрики outbox, DLQ, inbox, подписчики); повтор `dead`/`failed` — `bus retry-dead`, `bus retry-inbox <id события>`.

**Порядок выкладки EDS и ERP (E5, EDS-03).** С волны 12 одобрение КП директором — только маршрут EDS: ERP после виз публикует
`quote.ready_for_approval` и ждёт `approval.decided`. EDS выкладывается **раньше или вместе с ERP** (один `deploy.sh` поднимает
оба); ERP без EDS принимает КП на согласование, но они остаются в `PENDING_APPROVAL` — событие лежит в outbox ERP до появления
подписчика `eds` и уходит после включения EDS (проверка — `bus status` у ERP). Откат EDS при работающей ERP с EDS-03 не делать.

**Сотрудники заведены до EDS (E7b, C1-G-3).** Сотрудники, созданные в CRM **до** появления подписчика `eds`, в проекции EDS не появляются
(вход — 403 `USER_NOT_PROVISIONED`); правка без изменений события не даёт. После деплоя с EDS выполнить на VPS 1:
`docker compose … exec crm-api python -m app republish-identity --dry-run` (счёт), затем `… republish-identity` (все сотрудники;
`--user-id N` — один). Команда публикует `identity.user.updated.v1` с полным снимком через outbox, повтор безопасен
(`docs/runbooks/rt-bus-crm.md`, «Действия» п. 5). На чистом проде, где EDS деплоится вместе с CRM до создания сотрудников, не нужна.

**Новый код EDS в каталоге ролей (W13-A2, `bus.manage`; автоматически с W13C-F4).** Права EDS — проекция из `identity.user.*`,
обмен SSO их не меняет; когда в `packages/contracts/platform-rbac.yaml` (`backend.eds`) меняется набор кодов, заведённые
сотрудники получают их только после переопубликации. **Обычно ручной шаг не нужен: воркер CRM (`crm-worker`) при старте сам
сравнивает отпечаток этой части каталога с записанным в `identity_catalog_state` и при изменении публикует
`identity.user.updated.v1` всем сотрудникам** (под advisory-блокировкой, один раз на изменение; в логе воркера
`eds_rights_republished`, при сбое — `eds_rights_republish_failed`, повтор при следующем старте). Проверка после деплоя: под
администратором Admin · Журнал интеграций (`/admin/bus`) показывает подписчиков EDS без плашки «EDS не дал доступ к журналу». Резерв
(воркер не стартовал, в логе сбой шины, нужно немедленно): на VPS 1 `docker compose … exec crm-api python -m app republish-identity
--dry-run` (счёт), затем `… republish-identity`; повтор безопасен (Q-W13-A2-3, решено в W13C-F4).

**Откат.** `rollback.sh` на тег до EDS убирает его контейнеры (`--remove-orphans`) и не проверяет здоровье; на тег с EDS тянет `eds-api` и ждёт `healthy`.
Миграции Alembic EDS не откатываются (как у CRM и ERP). Сброс `reset-prod.sh` (S0-8) включает базу `eds` и бакет `eds-private`: список — `crm,erp,eds`, дамп `eds` обязателен, подтверждение на VPS 2 — ввод `crm,erp,eds`.

## 6. Первая установка 2026-10-21 — что пошло не так и как учтено

- **Старое на серверах.** На VPS 1 работали старый B2B (`b2b.railtech.uz`), GradeSentinel, системный Caddy и два self-hosted
  раннера GitHub, на VPS 2 — системный PostgreSQL 17. По решению владельца удалены без бэкапа (тестовые данные). Перенос
  старого прода (M5-ERP-01) больше не нужен.
- **Вход по паролю.** На VPS 1 `PasswordAuthentication yes` стоял в `/etc/ssh/sshd_config.d/50-cloud-init.conf` — он
  подключается раньше основного файла, правка `sshd_config` из §1.1 не действовала. Проверять итог `sshd -T | grep passwordauth`.
- **Внутренняя сеть.** Интерфейс `ens8`: VPS 1 — `10.0.0.3`, VPS 2 — `10.0.0.2` (это `APP_INTERNAL_IP` / `DB_INTERNAL_IP`).
  WireGuard `wg0` (`10.8.0.x`, порт 51820) остался от старой схемы, платформой не используется.
- **Гонка деплоя с мержем.** `workflow_dispatch` берёт `deploy.yml` с коммита `main` на момент запуска, а код — с `main` на момент
  старта job: PR, влитый между ними (17 с), дал релиз без нового файла. Не запускать деплой, пока в `main` вливается PR;
  кандидат в хвост — список файлов релиза в самом репозитории, а не в `deploy.yml`.
- **CPU без x86-64-v2** (QEMU 2.5+, хостер не меняет) — официальный LiteLLM и numpy ≥ 2.4 не стартуют. Решено в M5-INF-02
  (PR #123): свой образ LiteLLM на Debian, numpy < 2.4 в CRM, `cpu-baseline-check.sh` до миграций; ClickHouse/Langfuse на этих
  VPS недоступны (`docs/runbooks/servers.md`, «CPU прод-VPS»). Docling на проде не используется — база знаний принимает только
  Markdown (M5-CRM-02, PR #124).
- **Вебхук Telegram (временный обход, FIX-66).** При `TELEGRAM_MODE=webhook` и пустом `TELEGRAM_WEBHOOK_URL` CRM передавала
  Telegram пустой адрес — вебхук удалялся, бот молчал. С согласия владельца в `/opt/rt/.env.prod` вписано
  `TELEGRAM_WEBHOOK_URL=https://crm.railtech.uz/telegram/webhook`; после FIX-66 (адрес из `CRM_DOMAIN`) строку можно убрать.
- **Компания ERP руками (2026-10-21).** На чистой базе ERP не имела своей компании, а администратор из CRM упирался в тупик «не
  привязана к компании»: архитектор создал её в `manage.py shell`, `OWN_COMPANY_ID` и `PLATFORM_SSO_ENABLED=true` правились в
  `.env.prod`. Заменено мастером первого запуска ERP (FIX-65), автоопределением своей компании и SSO по умолчанию. На проде
  компания уже есть — мастер не покажется.
- **Не фильтровать службы по подстроке.** При удалении старых служб `grep grade` зацепил `apt-daily-upgrade` и
  `unattended-upgrades` — восстановлены; список служб смотреть глазами перед `disable`.

### Первый вход (владелец)

Единственное обращение к серверу — код мастера CRM из лога; дальше всё в браузере, без правок `.env.prod` и `manage.py shell` (FIX-65).

1. Код мастера первого запуска CRM (живёт 24 ч, пишется в лог один раз):
   `ssh deploy@176.101.56.141 'docker logs rt-platform-crm-api-1 2>&1 | grep setup_code_issued'`.
2. `https://crm.railtech.uz/setup` → код, e-mail и пароль первого администратора (пароль задаёт владелец, в логах и чате его нет).
3. **Подключить ERP — тоже в консоли админа CRM, без ssh.** «Подключения» → вкладка «ERP» → «Подключить ERP»: адрес уже подставлен
   (`http://erp-backend:8000` — внутренний сервис compose), код не нужен, вводится только пароль администратора. CRM и ERP читают один
   `.env.prod`, поэтому CRM сама доказывает ERP владение общим `PLATFORM_SSO_SECRET`, создаёт ключи, передаёт их ERP и сразу проверяет
   связь (ADR-0009, `docs/runbooks/crm-erp-pairing.md`). Это работает один раз: после первого сопряжения путь без кода закрыт навсегда;
   код из ERP (`manage.py pairing_code` или «Настройки → Интеграция с CRM») нужен только для ERP на другом сервере или для повторного
   подключения. Внешний адрес ERP в production — только `https://`.
   **Если ERP уже настроена через `.env`** (токены шва заданы руками, как на стендах до M3-ERP-05), окно «без кода» открыто, пока не было
   ни одного сопряжения: сначала сопрячь кодом или закрыть окно `docker compose exec erp-backend python manage.py pairing_close_bootstrap`
   (`docs/runbooks/crm-erp-pairing.md`, «Живой стенд…»).
4. «Пользователи» → себе включить доступ к ERP (`platform_access`). `PLATFORM_SSO_ENABLED=true` на проде уже по умолчанию.
5. В шапке CRM «Перейти в ERP». ERP на чистой базе открывает мастер «Настройка ERP: ваша компания»: название (обязательно), ИНН,
   юридический адрес, телефон, e-mail. Вы становитесь владельцем; `OWN_COMPANY_ID` вписывать не нужно.
6. Остальное — «Настройки → Реквизиты» в ERP (банк, подписант, логотип); затем ключи моделей, бот Telegram, почта в консоли CRM.

Мастер показывается, только пока в ERP нет своей компании, и только администратору. Сотрудник без компании до завершения мастера
видит «администратор ещё не завершил первоначальную настройку ERP».

## 7. Сброс прода и первый запуск (S0-8)

**Когда применять.** Один раз, по решению владельца 2026-10-23: в проде нет ни данных, ни аккаунтов, и он переводится на чистые базы
(стратегия §7, волна 10). Сценарий **разрушает** базы `crm` и `erp`, файлы приложений в RustFS и тома Redis. На живых данных его не
запускают; после первого запуска он не нужен.

**Что делает** `infra/deploy/reset-prod.sh [тег]` (VPS 1, под `deploy`; тег по умолчанию — `state/current_tag`; ввод идёт с терминала,
флага «без вопросов» нет — нужен `ssh -t`):

| Шаг | Действие | Не трогает |
|---|---|---|
| 0 | Проверки до разрушения: `.env.prod`, релиз, **подтверждение вводом имени домена CRM**, ключи S3 на сервис (`make-env-prod.sh s3-keys`: недостающие дописывает и генерирует, значения не печатает; если ключи `wal`/`backup` созданы заново — в конце напоминание про VPS 2), `compose pull`, `cpu-baseline-check.sh` | — |
| 1 | Останавливает приложения проекта (CRM, ERP, Cabinet, Платформа, Redis, Langfuse, воркеры) | `rustfs`, `caddy`, `litellm`, `clickhouse` продолжают работать |
| 2 | **Дамп** `crm` и `erp` (`predeploy-dump.sh`) и копия в `/opt/rt/state/reset/dumps/<время>/` (там дамп не вытесняется ротацией) | — |
| 3 | Пересоздаёт `crm` и `erp` на VPS 2: `DROP DATABASE … WITH (FORCE)`, затем `10-prod-init.sh` (`CREATE DATABASE` с владельцем-ролью, `pgvector` в `crm`). С VPS 1 проверяет, что обе базы пусты | базы `litellm` (ключи моделей) и `langfuse`; роли и пароли |
| 4 | Очищает бакеты RustFS `erp-private`, `erp-public`, `erp-temp`, `client-documents`, `tg-attachments`, `kb-sources` корневым ключом (одноразовый `s3-init`: ключи сервисов чужих бакетов не видят, S0-9) | бакеты `backups`, `wal`, `langfuse` |
| 5 | Удаляет тома Redis: `redis_data` (старый), `redis_broker_data`, `redis_cache_data` | `s3_data` (RustFS), `caddy_data` (**сертификаты**), `caddy_config`, `postgres_*` |
| 6 | `deploy.sh <тег>`: миграции на пустые базы, `up`, smoke | — |
| 7 | Печатает, где взять код первого запуска CRM (сам код не печатает) | — |

**Решения, принятые в сценарии.**

- **Шаг 3 — отдельным заходом на VPS 2.** У `deploy` на VPS 2 нет `sudo`, а давать VPS 1 ключ `root` от VPS 2 ради одного сброса не нужно. Скрипт
  печатает команду для VPS 2 (`<каталог>/infra/deploy/reset-prod.sh db --drop crm,erp`, от root), ждёт Enter и сам проверяет с VPS 1, что базы пусты и
  `vector` в `crm` на месте. Если у VPS 1 есть ключ к VPS 2, `RT_RESET_DB_SSH=root@<VPS 2>` делает этот заход сам. Режим `db` принимает только `crm` и `erp`
  (`litellm` и `langfuse` он отклоняет) и сверяет число таблиц `litellm` до и после. **Барьер перед `DROP`:** либо VPS-1-часть передаёт флаг `--dump-taken <каталог дампа>` (только
  после снятия дампа; так работает `RT_RESET_DB_SSH`), либо человек вводит `crm,erp` с терминала; без флага и без терминала режим отказывает. На VPS 2 каталог `infra` должен быть той же версии, что релиз
  (при выкладке S0-3 его обновляют так же, как в п. 1.3: скопировать `infra/` релиза в `/opt/rt-db/infra`).
- **WAL-архив не переключается.** Кластер PostgreSQL тот же: `DROP`/`CREATE DATABASE` — обычные транзакции в том же потоке WAL, имена сегментов не повторяются,
  поэтому `WAL_S3_PREFIX` и `WAL_ENC_KEY` остаются прежними (смена префикса — только при новом кластере, `initdb`, и по `backup-pitr.md` §6). Следствие: на момент до
  сброса (до 14 суток) восстановление на момент времени остаётся возможным и вернёт старые данные; бакет `wal` сценарий не чистит. Чтобы у новых баз была своя
  базовая копия раньше ночной, после первого запуска можно выполнить на VPS 2 `docker exec -u postgres rt-db-walg-1 walg-daemon --backup-now`.
- **`langfuse` не сбрасывается.** Это служебная база трассировки (аккаунтов и данных клиентов в ней нет), её ключи прописаны в env CRM, а ClickHouse/Langfuse на этих
  VPS не запускаются (`servers.md`, «CPU прод-VPS»): сброс ничего не очистил бы и только создал бы расхождение ключей.
- **Дампы `backups` на VPS 2** (`/var/backups/rt`, бакет `backups`) хранят прежние данные до конца срока хранения (14 дней). Если они не должны жить дольше, владелец
  решает отдельно: сценарий их не удаляет.
- **Повторный запуск безопасен.** Шаги 1, 3–5 идемпотентны (остановленное не останавливается, пустые базы пропускаются, пустые бакеты и отсутствующие тома — не ошибка), дамп
  второй раз не снимается. Состояние прерванного сброса — `/opt/rt/state/reset/run` (дамп снят, данные сброшены); если «данные сброшены» уже записано, повтор в течение
  24 ч пропускает шаги 1–5 и сразу деплоит. Начать заново: `rm /opt/rt/state/reset/run`.

### 7.1. До сброса

1. **Сохранить офлайн** (если ещё нет): `/opt/rt/.env.prod`, `/opt/rt-db/.env.db`, отдельно `BACKUP_ENC_PASSPHRASE`, `WAL_ENC_KEY`, `LITELLM_SALT_KEY`; токен бота Telegram от BotFather
   (он хранится в базе CRM и исчезнет вместе с ней; после сброса вводится в «Подключениях» заново); при желании — пароли и ключи моделей, которые лежат у владельца вне сервера.
   Ключи моделей в базе `litellm` сохраняются, но ключ `LITELLM_SALT_KEY` обязателен для их расшифровки.
2. **Переменные VPS 1** (порядок важен, подробности — `backup-pitr.md` §1): `infra/deploy/make-env-prod.sh init` допишет новые переменные (`REDIS_BROKER_PASSWORD`,
   `REDIS_CACHE_PASSWORD`, `WAL_*` и др.), **впервые сгенерирует `WAL_ENC_KEY`** и ключи S3 на сервис `S3_*` (прежний `S3_ACCESS_KEY/S3_SECRET_KEY` станет корневым `S3_ROOT_*`;
   S0-9). Сразу после `init`: (а) **сохранить `WAL_ENC_KEY` офлайн** — повторный `init` после `drop-db-only` создаст другой ключ, а потерянный не восстановить; (б) вписать вместо
   заглушек `192.0.2.x` реальные адреса: `WAL_S3_ENDPOINT=http://<APP_INTERNAL_IP>:9000` (и `BACKUP_RUSTFS_ENDPOINT`, если `init` его дописал; деплой отказывается работать с
   заглушками). `drop-db-only` пока **не** запускать: сначала п. 4. `PLATFORM_DOMAIN` и A-запись на месте (раздел «Платформа»).
3. **Деплой main** обычным способом (Actions → Deploy, `ref` = `main`): он создаёт бакет `wal` и ключи сервисов (`s3-init`), без них архив на VPS 2 только копит WAL на диске. Если деплой
   упал на миграциях старых данных — это не помеха сбросу: релиз уже лежит в `/opt/rt/releases/<sha>/`, а сам сброс (шаг 6) поднимет стек и создаст бакеты. Нужно только,
   чтобы там был `infra/deploy/reset-prod.sh` (`ls`), а образы с этим тегом уже в GHCR.
4. **VPS 2** (S0-3, ключи S3 — S0-9): дописать в `/opt/rt-db/.env.db` **только** настройки WAL и ключи S3 — слепой `extract-db > .env.db` перезаписал бы пароли баз VPS 2.
   Ключи берутся из `extract-s3` (ключи сервисов `wal` и `backup`, не корневой), остальное `WAL_*` — из `extract-db`; прежние строки этих переменных на VPS 2 заменяются:
   ```bash
   # VPS 1, от deploy (файл с секретами — только для владельца)
   umask 077
   { infra/deploy/make-env-prod.sh extract-db | grep -E '^(WAL_|BACKUP_RUSTFS_(ENDPOINT|BUCKET)=)' | grep -vE '^WAL_S3_(ACCESS|SECRET)_KEY='; infra/deploy/make-env-prod.sh extract-s3; } > /tmp/vps2.env
   scp /tmp/vps2.env deploy@<VPS 2>:/tmp/vps2.env && shred -u /tmp/vps2.env
   # VPS 2, от deploy: убрать прежние строки этих переменных, дописать новые, пароли баз не трогать
   ssh deploy@<VPS 2> 'f=/opt/rt-db/.env.db; t=$(mktemp); grep -vE "^($(cut -d= -f1 /tmp/vps2.env | paste -sd"|" -))=" "$f" > "$t"; cat /tmp/vps2.env >> "$t"; cat "$t" > "$f"; shred -u "$t" /tmp/vps2.env; chmod 600 "$f"'
   # затем обновить /opt/rt-db/infra версией релиза (п. 1.3) и поднять базу с WAL-архивом
   ssh root@<VPS 2> /opt/rt-db/infra/deploy/db-up.sh
   # после этого на VPS 1:
   infra/deploy/make-env-prod.sh drop-db-only
   ```
   Проверка WAL — `backup-pitr.md` §1 («Проверка»): `postgres` и `walg` healthy, бакет `wal` непустой.
5. Не запускать сброс, пока в `main` вливается PR (гонка с релизом, раздел 6).

### 7.2. Сброс и первый запуск

```bash
# VPS 1, под deploy, интерактивно (ssh -t): подтверждение — имя домена CRM; тег указывайте явно; на шаге 3 скрипт попросит выполнить команду на VPS 2
ssh -t deploy@<VPS 1> /opt/rt/releases/<sha>/infra/deploy/reset-prod.sh <sha>
# VPS 2, по просьбе скрипта на шаге 3, от root, с терминалом (-t): режим db попросит ввести crm,erp
ssh -t root@<VPS 2> /opt/rt-db/infra/deploy/reset-prod.sh db --drop crm,erp     # затем Enter в сеансе VPS 1
```

После сообщения «сброс завершён» — первый запуск (один заход на сервер — за кодом, дальше браузер):

1. Код первого запуска CRM (живёт 24 ч, выпускается при каждом старте `crm-api`, пока нет администратора): `ssh deploy@<VPS 1> 'docker logs rt-platform-crm-api-1 2>&1 | grep setup_code_issued | tail -1'`.
   Нужна **последняя** строка: журнал контейнера хранит и прежние запуски (скрипт в конце печатает имя контейнера и число найденных строк).
2. `https://<CRM_DOMAIN>/setup` → код, e-mail и пароль первого администратора (пароль задаёт владелец).
3. **Платформа: Admin → Подключения** (то же есть в консоли CRM): бот Telegram — токен от BotFather; ERP — кнопка «Подключить ERP»: адрес `http://erp-backend:8000`
   подставлен, **код не нужен**, вводится пароль администратора (`crm-erp-pairing.md`). Окно «без кода» одноразовое: на чистых базах оно открыто.
4. Роли: «Пользователи» — доступ в ERP (`platform_access`) и роли сотрудников; мастер ERP «Настройка ERP: ваша компания» — при первом входе в ERP (раздел «Первый вход», п. 5–6).

### 7.3. Что проверить после

| Что | Как | Ожидается |
|---|---|---|
| Все домены | `curl -sS -o /dev/null -w '%{http_code}\n' https://<CRM_DOMAIN>/health` (то же для ERP и Cabinet) и `https://<PLATFORM_DOMAIN>/api/v1/health` | 200; у Платформы `"status":"ok"` |
| `/mcp` снаружи | `curl … https://<домен>/mcp/x` для CRM, ERP, Cabinet, Платформы; `https://<ERP_DOMAIN>/mcp/erp/` | 404 везде |
| Машинный API и admin ERP | `curl … https://<ERP_DOMAIN>/api/integration/v1/health` и `…/admin/` | 404 |
| Сервисы VPS 1 | `docker compose -f /opt/rt/current/infra/compose/base.yml -f /opt/rt/current/infra/compose/prod.yml --env-file /opt/rt/.env.prod ps` | `crm-bot`, `crm-api`, `erp-backend`, `litellm`, `redis-broker`, `redis-cache`, `platform-bff` — `healthy`; `redis` (старый) и `redis_data` нет |
| `walg` и `postgres` на VPS 2 | `docker inspect --format '{{.State.Health.Status}}' rt-db-walg-1 rt-db-postgres-1` | `healthy`; `docker exec -u postgres rt-db-walg-1 rt-pitr status` — архив идёт |
| Что сохранилось | в «Подключениях» CRM модели и ключи на месте (база `litellm`); `ls` бакетов `backups` и `wal` не пуст; сертификаты Caddy те же (сайт открывается без паузы на выпуск) | да |
| Что очищено | `/setup` открыт (мастер), список лидов/клиентов пуст, бакеты `erp-*` пусты | да |
| Бот | сообщение боту после ввода токена; `docker compose … logs crm-bot` | отвечает, без `409` дольше минуты |

### 7.4. Если сброс упал на середине

Состояние всегда видно в выводе скрипта (номер шага) и в `/opt/rt/state/reset/run`. Общее правило: **повторите тот же запуск** (`reset-prod.sh <sha>`, ввод домена снова) —
выполненное не повторяется. Блокировка от двойного запуска — `/opt/rt/state/reset.lock` (после жёсткого обрыва: `rmdir`).

| Где упало | Что с данными | Что делать |
|---|---|---|
| До шага 1 (`pull`, `cpu-baseline-check`, `config`, неверный домен) | не тронуто, приложения работают | исправить причину (образ в GHCR, `.env.prod`), запустить снова |
| Шаг 1–2 (остановка, дамп) | приложения остановлены, базы и файлы целы | дамп не прошёл — доступ VPS 1 → VPS 2:5432 (раздел 5, `pg_dump-гейт`); поднять приложения можно `deploy.sh <прежний тег>`; затем повторить сброс |
| Шаг 3 (база) | дамп есть; базы могли удалиться не обе | повторить команду на VPS 2 (`DROP IF EXISTS` и init идемпотентны); `docker logs rt-db-postgres-1`; затем снова `reset-prod.sh` |
| Шаг 4–5 (бакеты, тома) | базы уже пусты, приложения остановлены | причина — RustFS не healthy / образ CRM не запускается (`docker compose … logs rustfs`); повторить запуск |
| Шаг 6 (миграции, `up`, smoke) | данные сброшены, дамп сохранён | чинить причину по разделу 5 (`logs erp-backend crm-api`, DNS, сертификат); затем `reset-prod.sh <sha>` (пропустит шаги 1–5) или `deploy.sh <sha>` |

**Откат данных** (нужен только если сброс сделан по ошибке): приложения остановить, затем восстановление боевой базы из раздела 4, взяв дамп из
`/opt/rt/state/reset/dumps/<время>/{crm,erp}.dump` (на VPS 2 они доставляются как в пункте 4 «Восстановление боевой базы»). Файлы бакетов и Redis восстановить нельзя —
они удалены; поэтому подтверждение вводом домена обязательно.

### 7.5. Архитектору: последовательность команд

1. Перед началом (владелец/архитектор): офлайн-копии `.env.prod`, `.env.db`, `BACKUP_ENC_PASSPHRASE`, `WAL_ENC_KEY`, `LITELLM_SALT_KEY`, токен бота (п. 7.1.1). Убедиться, что в `main` ничего не вливается.
2. VPS 1: `infra/deploy/make-env-prod.sh init` (WAL_ENC_KEY и ключи S3 на сервис генерируются; прежний `S3_ACCESS_KEY` становится корневым) → сразу сохранить `WAL_ENC_KEY` офлайн → вписать `WAL_S3_ENDPOINT=http://<APP_INTERNAL_IP>:9000` (и `BACKUP_RUSTFS_ENDPOINT`, если там заглушка). `drop-db-only` пока не запускать (п. 7.1.2).
3. Actions → Deploy → `ref` = `main`, `action` = `deploy` (создаёт бакет `wal` и ключи сервисов). Дождаться окончания; красный результат на миграциях старых данных допустим, если релиз `<sha>` лёг на VPS 1.
4. VPS 2 (п. 7.1.4): `extract-db | grep -E '^(WAL_|BACKUP_RUSTFS_(ENDPOINT|BUCKET)=)'` без `WAL_S3_*_KEY` + `extract-s3` → заменить такие же строки в `/opt/rt-db/.env.db` (не перезаписывать файл, пароли баз не трогать) → обновить `/opt/rt-db/infra` → `ssh root@<VPS 2> /opt/rt-db/infra/deploy/db-up.sh` → на VPS 1 `drop-db-only`.
5. `ssh -t deploy@<VPS 1> /opt/rt/releases/<sha>/infra/deploy/reset-prod.sh <sha>` → ввод имени домена CRM (на шаге 0 скрипт сам вызовет `s3-keys`) → на шаге 3 в другом окне `ssh -t root@<VPS 2> /opt/rt-db/infra/deploy/reset-prod.sh db --drop crm,erp` (ввод `crm,erp`) → Enter в сеансе VPS 1.
6. Код: `ssh deploy@<VPS 1> 'docker logs rt-platform-crm-api-1 2>&1 | grep setup_code_issued | tail -1'` → `https://<CRM_DOMAIN>/setup` → Платформа: Admin → Подключения (бот, «Подключить ERP») → роли → проверки п. 7.3.
7. Данные для входа передать владельцу; затем гейт этапа 0 (`wave10-stage0.md` §3).
