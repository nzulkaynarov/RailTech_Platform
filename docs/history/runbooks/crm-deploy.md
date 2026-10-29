> **История.** Заменено: docs/runbooks/deploy.md (прод выкладывается ансамблем: `main` → CI → одобрение → VPS1). Документ описывает отдельный деплой CRM до монорепозитория. Не используется для решений.

# Деплой и откат prod

## Когда применять
Выкладка новой версии (тег `v*`), первичная настройка VPS, откат после неудачной выкладки.

## Первичная настройка (один раз, человек)
1. VPS: Ubuntu LTS, 4 vCPU / 8 GB / 80 GB SSD; Docker Engine + compose plugin; пользователь
   `deploy` в группе `docker`; ssh только по ключу; ufw: 22, 80, 443 (tcp) и 443/udp.
2. DNS: `A` для `DOMAIN`, `langfuse.DOMAIN`, `s3.DOMAIN` → IP VPS.
3. `git clone https://github.com/nzulkaynarov/crm-rt-ai.git /srv/railtech && cd /srv/railtech`
4. `scripts/bootstrap_dev.sh` создаёт `.env` с секретами; затем в `.env`: `APP_ENV=prod`,
   `TELEGRAM_MODE=webhook`, `TELEGRAM_WEBHOOK_URL=https://DOMAIN/telegram/webhook`,
   `DOMAIN`, `ACME_EMAIL`, `ADMIN_ALLOW_CIDRS` (офис/VPN), prod-ключи провайдеров
   (с лимитами расходов в консолях, ADR-0014). `SECRETS_KEY` (ADR-0018) `bootstrap_dev.sh` генерирует
   сам — **сохраните его копию вне сервера**: без него токен бота, сохранённый в CRM, не расшифровать.
   Токен бота можно не вписывать в `.env`: его вводит админ в «Система → Подключения».
   `LITELLM_SALT_KEY` (ADR-0020) тоже генерируется сам — **сохраните копию вне сервера и не меняйте**:
   им зашифрованы ключи провайдеров, введённые в «Модели ИИ». Модели ролей хранятся в базе `litellm`
   того же Postgres (создаёт `litellm-db-init`), значения по умолчанию засевает `litellm-seed`
   из `infra/litellm.models.yaml` при каждом `make up-prod` (только отсутствующие алиасы).
7. **Первый запуск без терминала** (ADR-0018): пока в БД нет админа, CRM открывает `/setup`.
   Одноразовый код — в логах api: `make logs s=api | grep setup_code_issued` (24 ч; новый — после
   рестарта api). Дальше — чек-лист «Настройка CRM» на главной: модели, бот, канал, база знаний, команда.
5. GitHub → Settings → Environments → `production` (required reviewers — по желанию), secrets:
   `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY` (приватный ключ deploy), `VPS_KNOWN_HOSTS`
   (`ssh-keyscan -t ed25519 <host>`), `VPS_APP_DIR=/srv/railtech`.
6. Пакеты GHCR приватные: на VPS вход выполняет сам workflow (токен job'а), отдельный PAT не нужен.

## Выкладка
1. `main` зелёный (CI + Eval gate). `git tag v1.2.0 && git push origin v1.2.0`.
2. Workflow **Deploy prod**: сборка `railtech-backend|frontend|backup:<sha>` → GHCR → ssh →
   `scripts/deploy.sh v1.2.0 <sha>`: бэкап → checkout тега → `IMAGE_TAG` в `.env` →
   `make up-prod` (pull, `migrate`, рестарт) → `scripts/smoke_prod.sh`.
3. Smoke провален → автоматический откат на предыдущие тег и образы, job красный.

## Диагностика
- Лог job'а (вывод `deploy.sh`, `smoke_prod.sh`); на VPS: `make ps`, `make logs s=api`,
  `curl -s https://DOMAIN/ready`.
- Миграция упала → `docker compose ... logs migrate`; api не стартует, пока `migrate` не успешен.

## Действие (ручной откат)
1. `cd /srv/railtech && git tag --sort=-creatordate | head` — предыдущий тег.
2. `scripts/deploy.sh <пред-тег> $(git rev-list -n1 <пред-тег>)` — образы этого sha уже в GHCR.
3. ⚠️ Миграции не откатываются автоматически. Правило: миграции обратно совместимы
   (expand → contract в следующем релизе). Если всё же нужно вернуть схему — восстановление
   из бэкапа перед выкладкой (`backup-restore.md`), данные после него будут потеряны.

## Проверка
`make smoke-prod` → «Smoke prod OK»; тестовое сообщение боту → ответ; вход в CRM.

## Эскалация
Разработчику: ссылка на run, вывод `make ps`, логи api/migrate за время выкладки (Asia/Tashkent).
