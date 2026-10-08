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
   (с лимитами расходов в консолях, ADR-0014), prod-токен бота.
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
