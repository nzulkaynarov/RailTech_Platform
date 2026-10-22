# Runbook: прод на двух VPS — установка, деплой, откат, бэкапы (M5-INF-01)

Раскладка и лимиты памяти — `docs/runbooks/servers.md`. Файлы: `infra/compose/prod.yml` (VPS 1, поверх `base.yml`),
`infra/compose/db.yml` (VPS 2), `infra/caddy/Caddyfile.prod`, `infra/deploy/*`, `infra/db/*`, `infra/.env.prod.example`,
`.github/workflows/deploy.yml`. Статус: **установлено на VPS 2026-10-21** (архитектор, резерв Opus): первый успешный деплой
`main @ 735256f7` (run 39565753265) — три домена по HTTPS (Let's Encrypt), `/health` 200, `/ready` CRM — база, S3, LiteLLM `ok`,
`/mcp` снаружи 404. Ошибки первого запуска — §6.

## Как устроено

- **Образы** собирает `deploy.yml` (только `workflow_dispatch`) и кладёт в GHCR с тегом = полный git sha:
  `rt-crm-backend`, `rt-crm-frontend`, `rt-erp-backend`, `rt-erp-frontend`, `rt-cabinet`, `rt-platform-bff`, `rt-platform-web`, `rt-litellm` (свой образ LiteLLM на Debian, `infra/ai/litellm/`; официальный на прод-CPU не стартует). Деплоится только код, уже входящий в `main`.
- **Релиз** на VPS 1 — каталог `/opt/rt/releases/<sha>/` (`infra/`, `apps/crm/infra/casbin`, `packages/contracts/mcp-tools.json`, `packages/contracts/events.schema.json`), `/opt/rt/current` — ссылка на текущий.
  Состояние — `/opt/rt/state/{current_tag,previous_tag}`; хранятся пять последних релизов.
- **Секреты приложений** лежат только на серверах: `/opt/rt/.env.prod` (VPS 1) и `/opt/rt-db/.env.db` (VPS 2), оба `chmod 600`.
  В GitHub environment `production` — лишь доступ к серверу (SSH-ключ, known_hosts) и несекретные имена. Решение принято
  здесь, чтобы десятки секретов приложений не жили в GitHub; владелец вправе передумать (тогда `deploy.yml` дописывается).
- **База** — на VPS 2: PostgreSQL 17 + pgvector, 4 базы, по роли на базу (`crm_app`, `erp_app`, `litellm_app`, `langfuse_app`),
  `pg_hba` — только TLS и только внутренний IP VPS 1.
- **Порядок деплоя** (`infra/deploy/deploy.sh <sha>`): проверка env → `pull` → **проверка базы CPU образов** (`cpu-baseline-check.sh`: в каждом образе запускается import numpy / litellm.proxy / версия бинаря; образ, которому нужен x86-64-v2, останавливает деплой до дампа и миграций, см. servers.md «CPU прод-VPS») → **pg_dump-гейт** `crm` и `erp`
  (`predeploy-dump.sh`; нет читаемого дампа — миграций нет) → миграции CRM и ERP явно (`AUTO_MIGRATE=false` у ERP) → `up -d` → smoke.
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
infra/deploy/make-env-prod.sh extract-db > /tmp/env.db    # часть для VPS 2
scp /tmp/env.db deploy@<VPS 2>:/opt/rt-db/.env.db && shred -u /tmp/env.db
infra/deploy/make-env-prod.sh drop-db-only    # убрать с VPS 1 то, что нужно только VPS 2 (суперпользователь, ключи бэкапа)
```

Сохраните офлайн копию обоих файлов и отдельно `BACKUP_ENC_PASSPHRASE` и `LITELLM_SALT_KEY` (потеря первой — потеря внешних копий
бэкапа; второй — расшифровки ключей провайдеров в БД LiteLLM). После `drop-db-only` повторный `init` вернёт удалённые
переменные — на VPS 1 его запускать только для добавления новых и снова выполнять `drop-db-only`.

### 1.3. VPS 2: база

```bash
# каталог infra скопирован от deploy в /opt/rt-db/infra, /opt/rt-db/.env.db на месте (п. 1.2)
ssh root@<VPS 2> /opt/rt-db/infra/deploy/db-up.sh      # только от root: chown сертификата на uid 999
```

Скрипт создаёт сертификат TLS (самоподписанный, `sslmode=require`; проверка `verify-ca` — после пилота), `pg_hba.conf` с IP VPS 1,
поднимает `postgres` и `backup`, создаёт роли и базы (`crm`, `erp`, `litellm`, `langfuse`, `pgvector` в `crm`). Повторный запуск
безопасен и применяет смену паролей из `.env.db`. Проверка с VPS 1:
`docker run --rm -e PGPASSWORD=… -e PGSSLMODE=require pgvector/pgvector:0.8.7-pg17 psql -h <DB_INTERNAL_IP> -U crm_app -d crm -c 'select 1'`.

### 1.4. GitHub environment `production`

Settings → Environments → `production` (включить Required reviewers — владелец):

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

Actions → **Deploy** → Run workflow: `ref` = `main` (или sha, входящий в `main`), `action` = `deploy`. Порядок и сбои:

1. Сборка и push восьми образов в GHCR; загрузка релиза на VPS 1.
2. `deploy.sh` на сервере. Если упал **pg_dump-гейт** — миграции не запускались, сервисы не тронуты; чините доступ к базе и запускайте снова.
3. Smoke с сервера и с раннера: `/health` CRM, ERP, Cabinet — 200, `/api/v1/health` Платформы — 200 и `status: ok`, `erp…/mcp/erp/` и `<платформа>/mcp/x` — 404.

На первом запуске Caddy получает сертификаты Let's Encrypt — DNS должен уже указывать на VPS 1, порты 80/443 открыты. После деплоя:

- свою компанию ERP создаёт мастер первого запуска (п. «Первый вход», FIX-65); `OWN_COMPANY_ID` вписывать не нужно — только если
  в базе окажется несколько компаний-продавцов с участниками;
- Telegram-вебхук ставит CRM сама при `TELEGRAM_MODE=webhook`; адрес берётся из `CRM_DOMAIN` (`https://<CRM_DOMAIN>/telegram/webhook`,
  `prod.yml`), вписывать `TELEGRAM_WEBHOOK_URL` вручную не нужно — задавайте её, только если вебхук должен идти на другой https-адрес
  (явное значение переопределяет). Режим `webhook` с пустым или не-https адресом бота не запускает и вебхук не трогает: в журнале CRM
  `bot_webhook_not_configured`, в «Центре внешних сервисов» → Telegram — сбой «Вебхук Telegram не настроен» с подсказкой; там же
  фактический адрес вебхука и последняя ошибка доставки из `getWebhookInfo`. Если на VPS адрес был вписан вручную — после выкладки
  с этим изменением строку можно убрать из `.env.prod` (значение по умолчанию совпадёт);
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

**Схема событий ERP → CRM (M5-INF-01c).** Файл `packages/contracts/events.schema.json` едет в релизе и монтируется read-only в
`/packages/contracts/events.schema.json` сервисов `erp-backend`, `erp-worker`, `erp-worker-ai`, `erp-beat` (и `erp-mcp` под
профилем `mcp`): по нему ERP проверяет тело каждого события перед отправкой (`ERP_EVENTS_CONTRACT_MODE=log` в проде —
несоответствие пишется в лог ERROR без значений полей, событие уходит). Образ прода схему не содержит. `deploy.sh` останавливается
до pull и миграций, если файла нет в релизе (релиз собран старым `deploy.yml`) — тогда пересобрать релиз с актуального `main`.
Проверить после деплоя: `docker compose exec erp-backend ls -l /packages/contracts/events.schema.json`, а в логе ERP нет строки
«events.schema.json не найден».

Вручную с сервера (без Actions): `/opt/rt/releases/<sha>/infra/deploy/deploy.sh <sha>`; без миграций и дампа — `make up-prod RT_IMAGE_TAG=<sha>`.

## 3. Откат

- **Код:** Actions → Deploy → `action` = `rollback` (или на VPS 1: `/opt/rt/current/infra/deploy/rollback.sh [sha]`). Поднимает
  предыдущий тег (`state/previous_tag`) с конфигурацией того релиза. **Миграции не откатываются**: откат безопасен, пока
  миграции отменяемого релиза обратно совместимы со старым кодом. Если нет — восстановление данных (п. 4) решает владелец.
- Предмиграционные дампы последних пяти деплоев — `/opt/rt/state/predeploy/<sha>-<время>/{crm,erp}.dump`.

## 4. Бэкапы и восстановление

- **Расписание:** контейнер `backup` на VPS 2 ежедневно в 22:00 UTC (03:00 Ташкент) делает `pg_dump` каждой базы, проверяет читаемость
  (`pg_restore -l`), хранит `BACKUP_KEEP_DAYS` (14) дней в `/var/backups/rt/<UTC-штамп>/`, выгружает в бакет `backups` RustFS
  на VPS 1 (ежедневно) и **зашифрованную** (AES-256, `BACKUP_ENC_PASSPHRASE`) копию во внешнее S3-хранилище (раз в неделю,
  `BACKUP_EXT_DAY`). Адрес и ключи внешнего хранилища — переменные `BACKUP_EXT_*`; провайдера выбирает владелец.
- **Сейчас:** `infra/deploy/backup-now.sh [--ext]` на VPS 2.
- **Статус в CRM:** «Внешние сервисы» → «Хранилище резервных копий» читает бакет `backups` RustFS (M5-CRM-01); нет копии за 26 ч — инцидент и оповещение. Подробно — `apps/crm/docs/runbooks/backup-restore.md`.
- **Проверка восстановления** (раз в неделю и после любых изменений бэкапа): `infra/db/restore-check.sh [каталог]` на VPS 2 — разворачивает
  каждый дамп во временную базу, считает таблицы, проверяет `vector` в `crm`, удаляет базу. Боевые базы не затрагиваются.
- **Восстановление боевой базы** (остановка записи обязательна):
  ```bash
  # VPS 1: остановить приложения, ходящие в базу
  docker compose -f … stop crm-api crm-worker crm-mcp-kb crm-mcp-crm crm-mcp-docs erp-backend erp-mcp erp-worker erp-worker-ai erp-beat
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
  `DJANGO_DEBUG=true` останавливается с `ImproperlyConfigured` (молча писать на диск контейнера нельзя). Ключ RustFS пока общий с CRM
  (`S3_ACCESS_KEY`/`S3_SECRET_KEY`): отдельный пользователь на сервис требует admin API RustFS (шифрованное тело, нужен `mc`/`rc` в
  отдельном образе) — хвост ADR-0013 п. 6. Проверка: `docker compose … exec erp-backend sh -c 'ls /app/media | wc -l'` — 0;
  листинг бакета: `curl --aws-sigv4 "aws:amz:us-east-1:s3" --user "$S3_ACCESS_KEY:$S3_SECRET_KEY" "http://rustfs:9000/erp-private?list-type=2"`
  из контейнера `s3-init`/`rustfs` (curl есть в образе RustFS).

## 5. Что где проверять

| Симптом | Куда смотреть |
|---|---|
| Сайт не открывается / нет сертификата | `docker compose … logs caddy`; DNS, порты 80/443; лимит выпусков Let's Encrypt |
| `pg_dump-гейт` падает | доступ VPS 1 → VPS 2:5432 (`ufw`, `pg_hba`, `DB_INTERNAL_IP`, пароль роли), `docker logs rt-db-postgres-1` на VPS 2 |
| ERP/CRM не стартуют после деплоя | `docker compose … logs erp-backend crm-api`; `ps` — какие контейнеры не healthy |
| Бэкап не создаётся | `docker logs rt-db-backup-1` на VPS 2, `/var/backups/rt/last_success`, healthcheck контейнера `backup` |
| Не хватает памяти | `docker stats`; профили `observability` и `kb-ingest` не включать вместе |

Эскалация: владелец; агент Infra — правки compose/Caddy/скриптов через PR.

## Платформа (INF-P0-5)

Единое рабочее место сотрудника (`apps/platform`): BFF `platform-bff` (FastAPI, Redis БД 3 — сессии) и статика `platform-web`
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
   (попыток входа в минуту, по умолчанию 10). `PLATFORM_COOKIE_SECURE` на проде не настраивается: `prod.yml` жёстко ставит `true`, на http-стенде
   `dev.yml` ставит `false`.
3. **GitHub environment `production`** — ничего обязательного; необязательная Variable `PLATFORM_DOMAIN` (§1.4) нужна, только если
   домен отличается от `platform.railtech.uz`: по ней smoke с раннера ходит на Платформу.
4. **Деплой** — обычный (§2): Actions → Deploy → `ref` = `main`, `action` = `deploy`. Не запускать, пока в `main` вливается PR (§6, гонка).

**Проверка после деплоя:**

- `curl -fsS https://platform.railtech.uz/api/v1/health` — ответ `200` и `"status":"ok"`: BFF видит Redis, CRM `/health` и ERP `/health`.
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
