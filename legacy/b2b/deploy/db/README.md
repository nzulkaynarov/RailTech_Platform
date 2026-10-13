# Бэкапы прод-базы — скрипты и сторож

Здесь лежит **источник правды** для двух скриптов, которые физически живут на серверах.
Как и с Caddy (`deploy/caddy/`): правим в репозитории, копируем на сервер осознанно.
Автоматического применения нет — эти файлы трогают боевые данные.

| Файл | Где стоит | Что делает |
|---|---|---|
| `railtech-db-backup.sh` | DB-VPS `/usr/local/bin/`, cron `/etc/cron.d/railtech-db-backup`, 02:30 | Снимает `pg_dump -Fc`, **проверяет дамп** `pg_restore --list`, чистит старше 14 дней, пишет `LAST_BACKUP_STATUS` |
| `railtech-backup-check.sh` | app-VPS `/usr/local/bin/`, cron `/etc/cron.d/railtech-backup-check`, 03:30 | Спрашивает DB-VPS по SSH, был ли свежий успешный дамп; при беде — событие в Sentry |

## Почему проверка живёт на ДРУГОЙ машине

Скрипт бэкапа не может пожаловаться на то, что его самого перестали запускать: упал cron,
кончилось место, сервер не поднялся после перезагрузки — для него это неотличимо от тишины.
До 18-08 «OK» в логе означал лишь, что `pg_dump` завершился: битый или обрезанный дамп
выглядел бы так же, а лог видел только тот, кто зашёл на сервер. Поэтому:

1. **Дамп проверяется** — `pg_restore --list` читает архив. Единственное, что отличает
   архив от набора байтов. Плюс порог размера.
2. **Статус машиночитаемый** — `/var/backups/railtech-db/LAST_BACKUP_STATUS` (JSON).
3. **Спрашивает сосед** — app-VPS по SSH, порог свежести 26 ч, и при беде шумит в Sentry,
   куда владелец и так смотрит.

## Грабли (обе пойманы прогоном ломаного входа 18-08)

- **`pg_restore` запускать от root, не от `postgres`.** Дамп лежит `root:600`, и проверка от
  `postgres` падала на «нет доступа» — ложная тревога на исправном дампе. Соединение с БД
  для `--list` не нужно, разбирается сам файл.
- **Sentry шлём `manage.py shell -c`, а НЕ `python -c`.** `sentry_sdk.init` живёт в настройках
  Django: у голого интерпретатора клиента нет, `capture_message` молча уходит в никуда, а
  скрипт при этом рапортует успех. В скрипте стоит `assert ...get_client().is_active()`.

## Установка / обновление

```bash
scp deploy/db/railtech-db-backup.sh vps-db:/usr/local/bin/railtech-db-backup.sh
ssh vps-db 'chmod 755 /usr/local/bin/railtech-db-backup.sh && /usr/local/bin/railtech-db-backup.sh'

scp deploy/db/railtech-backup-check.sh root@176.101.56.141:/usr/local/bin/railtech-backup-check.sh
ssh root@176.101.56.141 'chmod 755 /usr/local/bin/railtech-backup-check.sh && /usr/local/bin/railtech-backup-check.sh'
```

Сторож проверять **ломаным входом**, иначе он проверяет только сам себя:

```bash
# подложить провальный статус и убедиться, что проверка кричит (exit 1) и Sentry не ругается недоставкой
ssh vps-db 'cp /var/backups/railtech-db/LAST_BACKUP_STATUS /tmp/st.bak;
  echo "{\"ts\":\"$(date -Is)\",\"status\":\"FAILED\",\"file\":\"x\",\"bytes\":0,\"detail\":\"проба\"}" \
  > /var/backups/railtech-db/LAST_BACKUP_STATUS'
ssh root@176.101.56.141 '/usr/local/bin/railtech-backup-check.sh; echo "exit=$?"'
ssh vps-db 'cp /tmp/st.bak /var/backups/railtech-db/LAST_BACKUP_STATUS && rm /tmp/st.bak'
```

**Доступ:** app-VPS ходит на DB-VPS ключом `railtech-app-vps-backup-check` (лежит в
`authorized_keys` root@10.0.0.2). Проверка только читает файл статуса.
