# Бэкап и восстановление

## Когда применять
Плановая проверка (раз в месяц), перед рискованной операцией, потеря данных, переезд.

## Как устроено (ADR-0013)
Сервис `backup` ежедневно в 03:00 Asia/Tashkent: `pg_dump` (custom) + копия бакетов
`kb-sources`, `client-documents`, `tg-attachments` → том `railtech_backups`,
каталог `<UTC-штамп>/` с `SHA256SUMS`; хранится 14 дней (`BACKUP_KEEP_DAYS`).
Том смонтирован и в api: экран CRM «Резервные копии» (`/backups`, админ) показывает список,
возраст последней копии (предупреждение > 26 ч) и кнопку «Сделать сейчас» — она кладёт в том
файл-флаг `request_now`, демон `backup` проверяет его раз в 30 с и запускает тот же `backup_once`.
pg_dump есть только в образе `backup`, поэтому api сам бэкап не делает. На dev демон не запущен
(профиль `backup`) — запрос будет ждать; там используйте `make backup`.
Демон раз в 30 с (и во время бэкапа) пишет `heartbeat` (epoch) в том: старше 2 мин — CRM
показывает «Сервис резервного копирования не отвечает» (экран «Резервные копии» и «Состояние»);
запрос, не забранный за 2 мин, помечается зависшим, и кнопку можно нажать снова.

## Диагностика
- `scripts/backup.sh --prod --list` — список бэкапов; последний — не старше суток.
- `docker compose ... ps backup` — `healthy` (unhealthy = бэкапа нет > 26 ч);
  `make logs s=backup` — события `backup_done` / `backup_failed`.
- Каталоги `*.partial` — незавершённые попытки (удаляются автоматически через 6 ч).

## Действие
**Внеочередной бэкап:** CRM → «Резервные копии» → «Сделать сейчас» (через ~30 с `make logs s=backup`
покажет `backup_requested` → `backup_done`), или с сервера `scripts/backup.sh --prod`.
Запрос «завис» (контейнер backup остановлен): запустите его или удалите флаг —
`docker compose ... exec api rm /backups/request_now`.

**Копия вне VPS (раз в неделю, человек):**
`docker run --rm -v railtech_backups:/b -v "$PWD":/out alpine tar -czf /out/backups.tgz -C /b .`
→ перенести в защищённое хранилище.

**Восстановление** ⚠️ перезаписывает БД и файлы стенда:
1. `scripts/backup.sh --prod --list` → выбрать штамп.
2. `scripts/restore.sh --prod <штамп>` (подтвердить `yes`): остановит api/worker/MCP,
   проверит суммы, `pg_restore --clean`, загрузит объекты, запустит сервисы, smoke.

**Проверка восстановления на dev (гейт Фазы 8, ежемесячно):**
1. На VPS: `scripts/backup.sh --prod`; архив тома (см. выше) скопировать на dev-машину.
2. На dev: `docker run --rm -v railtech_backups:/b -v "$PWD":/in alpine tar -xzf /in/backups.tgz -C /b`.
3. `make restore b=latest` → `scripts/smoke_dev.sh` → в CRM видны лиды и документы с prod.

## Проверка
`/ready` 200; в CRM количество лидов = prod на момент бэкапа; документ клиента скачивается.

## Эскалация
Разработчику: вывод restore.sh, `make logs s=backup`, штамп бэкапа.
