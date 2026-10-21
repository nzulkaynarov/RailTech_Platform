# Runbook: прод на двух VPS — установка, деплой, откат, бэкапы (M5-INF-01)

Раскладка и лимиты памяти — `docs/runbooks/servers.md`. Файлы: `infra/compose/prod.yml` (VPS 1, поверх `base.yml`),
`infra/compose/db.yml` (VPS 2), `infra/caddy/Caddyfile.prod`, `infra/deploy/*`, `infra/db/*`, `infra/.env.prod.example`,
`.github/workflows/deploy.yml`. Статус: **конфигурация проверена `compose config`, `caddy validate`, shellcheck, actionlint;
на самих VPS не запускалась** — ждёт внутренние IP, SSH-ключ и DNS (OWNER-CHECKLIST «До M5»). Первый деплой — вместе
с агентом Infra; ошибки первого запуска вносить сюда.

## Как устроено

- **Образы** собирает `deploy.yml` (только `workflow_dispatch`) и кладёт в GHCR с тегом = полный git sha:
  `rt-crm-backend`, `rt-crm-frontend`, `rt-erp-backend`, `rt-erp-frontend`, `rt-cabinet`. Деплоится только код, уже входящий в `main`.
- **Релиз** на VPS 1 — каталог `/opt/rt/releases/<sha>/` (`infra/`, `apps/crm/infra/casbin`, `packages/contracts/mcp-tools.json`, `packages/contracts/events.schema.json`), `/opt/rt/current` — ссылка на текущий.
  Состояние — `/opt/rt/state/{current_tag,previous_tag}`; хранятся пять последних релизов.
- **Секреты приложений** лежат только на серверах: `/opt/rt/.env.prod` (VPS 1) и `/opt/rt-db/.env.db` (VPS 2), оба `chmod 600`.
  В GitHub environment `production` — лишь доступ к серверу (SSH-ключ, known_hosts) и несекретные имена. Решение принято
  здесь, чтобы десятки секретов приложений не жили в GitHub; владелец вправе передумать (тогда `deploy.yml` дописывается).
- **База** — на VPS 2: PostgreSQL 17 + pgvector, 4 базы, по роли на базу (`crm_app`, `erp_app`, `litellm_app`, `langfuse_app`),
  `pg_hba` — только TLS и только внутренний IP VPS 1.
- **Порядок деплоя** (`infra/deploy/deploy.sh <sha>`): проверка env → `pull` → **pg_dump-гейт** `crm` и `erp`
  (`predeploy-dump.sh`; нет читаемого дампа — миграций нет) → миграции CRM и ERP явно (`AUTO_MIGRATE=false` у ERP) → `up -d` → smoke.
- Правило FIX-03: `/mcp` снаружи — 404 на всех трёх доменах (Caddy); smoke это проверяет.

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
| Variable | `TELEGRAM_BOT_USERNAME` | имя бота без `@` (не секрет; зашивается в образ Cabinet) |

## 2. Первый деплой и обычный деплой

Actions → **Deploy** → Run workflow: `ref` = `main` (или sha, входящий в `main`), `action` = `deploy`. Порядок и сбои:

1. Сборка и push пяти образов в GHCR; загрузка релиза на VPS 1.
2. `deploy.sh` на сервере. Если упал **pg_dump-гейт** — миграции не запускались, сервисы не тронуты; чините доступ к базе и запускайте снова.
3. Smoke с сервера и с раннера: `/health` трёх доменов — 200, `erp…/mcp/erp/` — 404.

На первом запуске Caddy получает сертификаты Let's Encrypt — DNS должен уже указывать на VPS 1, порты 80/443 открыты. После деплоя:

- вписать `OWN_COMPANY_ID` в `/opt/rt/.env.prod` после создания компании-владельца (FIX-11) и перезапустить ERP;
- Telegram-вебхук ставит CRM сама при `TELEGRAM_MODE=webhook`;
- Langfuse (`RT_PROFILES=observability` в `.env.prod`) открывается SSH-туннелем: `ssh -L 3000:127.0.0.1:3000 deploy@<VPS 1>`;
  docling на проде **не используется** (M5-CRM-02): `DOCLING_URL` в `prod.yml` пуст. База знаний принимает только Markdown по
  `docs/kb/FORMAT.md` (готовит человек или ИИ-агент по `docs/kb/PROMPT.md`) и индексирует его встроенным конвертером CRM; docling
  в базе знаний не участвует вовсе. Остался только для текста документов клиентов (при пустом `DOCLING_URL` он помечается `failed`);
  профиль `kb-ingest` — опция для этого (вернуть `DOCLING_URL=http://docling:5001` и `DOCLING_API_KEY`), вместе с Langfuse не включать (8 ГБ).

`erp-mcp` (инструменты ERP для агента CRM) лежит под профилем `mcp` и по умолчанию не стартует: CRM к нему пока не ходит (M3-CRM-07).
Файл контракта уже едет в релизе: `/opt/rt/releases/<sha>/packages/contracts/mcp-tools.json` монтируется в контейнер по пути
`../../packages/contracts/mcp-tools.json` от `prod.yml` (без файла сервис не стартует). Включает профиль M3-CRM-07: добавить `mcp`
в `RT_PROFILES` в `.env.prod` (`RT_PROFILES=mcp`, через запятую с остальными) и выполнить обычный деплой; снаружи `/mcp` остаётся 404.

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
  docker compose -f … stop crm-api crm-worker crm-mcp-kb crm-mcp-crm crm-mcp-docs erp-backend erp-worker erp-worker-ai erp-beat
  # VPS 2: пересоздать базу и залить дамп (пример для erp)
  docker exec -u postgres rt-db-postgres-1 psql -U postgres -c 'DROP DATABASE erp' -c 'CREATE DATABASE erp OWNER erp_app'
  docker exec -i -u postgres rt-db-postgres-1 pg_restore -U postgres -d erp --no-owner --role=erp_app < /var/backups/rt/<штамп>/erp.dump
  # VPS 1: запустить приложения (deploy.sh <текущий sha> или rollback.sh), smoke
  ```
  Для `crm` после восстановления проверьте, что расширение `vector` на месте (`restore-check.sh` это делает). Внешнюю копию сначала
  расшифровать: `openssl enc -d -aes-256-cbc -pbkdf2 -in crm.dump.enc -out crm.dump -pass env:BACKUP_ENC_PASSPHRASE`.
- Файлы клиентов (RustFS на VPS 1, том `s3_data`) этим бэкапом **не** покрыты — только базы. Копирование бакетов — хвост M5 (см. PROGRESS).

## 5. Что где проверять

| Симптом | Куда смотреть |
|---|---|
| Сайт не открывается / нет сертификата | `docker compose … logs caddy`; DNS, порты 80/443; лимит выпусков Let's Encrypt |
| `pg_dump-гейт` падает | доступ VPS 1 → VPS 2:5432 (`ufw`, `pg_hba`, `DB_INTERNAL_IP`, пароль роли), `docker logs rt-db-postgres-1` на VPS 2 |
| ERP/CRM не стартуют после деплоя | `docker compose … logs erp-backend crm-api`; `ps` — какие контейнеры не healthy |
| Бэкап не создаётся | `docker logs rt-db-backup-1` на VPS 2, `/var/backups/rt/last_success`, healthcheck контейнера `backup` |
| Не хватает памяти | `docker stats`; профили `observability` и `kb-ingest` не включать вместе |

Эскалация: владелец; агент Infra — правки compose/Caddy/скриптов через PR.
