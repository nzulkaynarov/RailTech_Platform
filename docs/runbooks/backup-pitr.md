# Runbook: WAL-архив PostgreSQL и восстановление на момент времени (S0-3)

Основание: ADR-0017 п. 2 (RPO ≤ 5 мин, RTO ≤ 4 ч), стратегия §3.7. Ежедневный `pg_dump` (`docs/runbooks/deploy.md` п. 4) остаётся
вторым рубежом: он нужен, когда WAL-архив недоступен или нужна одна база целиком без разбирательств с моментом времени.

## Как устроено

```
VPS 2 (db)                                                  VPS 1 (app)                      внешнее S3 (по желанию владельца)
┌────────────────────────────────────────────┐            ┌──────────────────┐             ┌──────────────────────────┐
│ postgres  (образ rt-db-postgres: pgvector  │  wal-push  │ rustfs           │  rclone     │ BACKUP_EXT_BUCKET        │
│   + WAL-G), archive_mode=on,               ├───────────►│ бакет wal        ├────────────►│   wal/<WAL_S3_PREFIX>/   │
│   archive_timeout=60s                      │ каждый     │   <WAL_S3_PREFIX>│ каждые 5 мин│                          │
│ walg      (тот же образ) — раз в сутки     │ сегмент    │   basebackups_005│ (copy)      └──────────────────────────┘
│   базовая копия, срок хранения 14 дней,    ├───────────►│   wal_005        │
│   wal-verify, ежемесячная проверка         │ backup-push└──────────────────┘
│ backup    — ежедневный pg_dump (как раньше)│
└────────────────────────────────────────────┘
```

| Что | Значение |
|---|---|
| Непрерывный архив | `archive_mode=on`, `archive_command = rt-walg wal-push %p`, `archive_timeout=60s`: сегмент журнала уходит в хранилище по заполнении или раз в 60 с при записи → потеря при отказе ≤ 1–2 мин (цель RPO ≤ 5 мин) |
| Базовая копия | ежедневно в 21:00 UTC (`WAL_BASEBACKUP_AT_UTC`) сервисом `walg`; первая — сразу при первом запуске. Полная, сжатая zstd, зашифрована |
| Срок хранения | 14 дней (`WAL_KEEP_DAYS`): после каждой копии удаляется всё старше копии, покрывающей границу срока. Восстановление возможно на любой момент последних 14 суток |
| Хранилище | по умолчанию бакет `wal` RustFS на VPS 1 (`WAL_S3_ENDPOINT`, ключи `WAL_S3_ACCESS_KEY/SECRET_KEY`, каталог `WAL_S3_PREFIX`, по умолчанию `pg17`). Копия уже вне VPS 2, но на площадке VPS 1; «вне площадки» наступает, когда владелец даёт внешнее S3 |
| Внешнее S3 | если заданы `BACKUP_EXT_ENDPOINT` и `BACKUP_EXT_BUCKET` (те же переменные, что у недельного pg_dump), `walg` каждые 5 минут копирует архив в `<BACKUP_EXT_BUCKET>/wal/<WAL_S3_PREFIX>/` и применяет там свой срок хранения. Пусто — выключено. Хранилище вне площадки — в Узбекистане (ADR-0017) |
| Шифрование | libsodium, ключ `WAL_ENC_KEY` (64 hex-символа), общий для основного и внешнего хранилища. Генерирует `make-env-prod.sh init` |
| Проверки | `wal-verify` раз в 6 ч (нет дыр в цепочке сегментов); проверка восстановления — через час после первой копии и затем 1-го числа каждого месяца в 02:00 UTC |
| Сигнал сбоя | healthcheck контейнера `walg` (`docker ps` → `unhealthy`) и отметки в томе `walg_state`; как у контейнера `backup` (`/var/backups/rt/last_success`) |
| Бинарь WAL-G | v3.0.9, официальный релиз, закреплён версией и SHA-256 в `infra/db/Dockerfile.postgres`; Go-сборка `GOAMD64=v1` |

Образ свой, а не боковой контейнер с бинарём: `archive_command` и `restore_command` исполняет сам PostgreSQL, поэтому `wal-g` обязан
быть в его контейнере; боковой контейнер потребовал бы общий том с бинарём и добавил точку отказа в самый критичный путь. Всё остальное
(копии, срок хранения, проверка) делает боковой сервис `walg` из того же образа: он общается с базой по общему unix-сокету
(`peer` от пользователя `postgres`), каталог данных видит только на чтение.

### CPU прод-VPS (без x86-64-v2)

Прод-VPS отдают «QEMU Virtual CPU 2.5+» (`docs/runbooks/servers.md`). Бинарь WAL-G проверен под `qemu-x86_64 -cpu qemu64` (и с явно
выключенными `sse4.1,sse4.2,ssse3,popcnt,avx,avx2`): `wal-g --version`, а также шифрованная запись и чтение сегмента WAL
(`wal-push` → `wal-fetch`, libsodium + zstd) дали побайтно тот же файл. Кроме того, `db-up.sh` запускает `wal-g --version` из свежесобранного
образа на самом сервере **до** перезапуска боевой базы и останавливается, если бинарь не стартует.

Воспроизвести проверку на Mac/Linux (в контейнере Debian, нужен каталог `sysroot` с `ld-linux-x86-64.so.2`, `libc.so.6`, `libm.so.6` из amd64-образа):
`qemu-x86_64 -cpu qemu64 -L sysroot wal-g-pg-22.04-amd64 --version`.

## 1. Включение на проде

**Когда применять:** первый запуск WAL-архива на VPS 2 (в рамках сброса прода S0-8 или на работающем проде).

**Подготовка (VPS 1, от `deploy`):**

1. Выкатить релиз с бакетом `wal` (`deploy.sh` → `s3-init` создаёт бакет). Бакет должен существовать до запуска на VPS 2, иначе архив
   будет повторять попытки (WAL копится на диске VPS 2, данные не теряются).
2. `infra/deploy/make-env-prod.sh init` — допишет в `/opt/rt/.env.prod` новые переменные `WAL_*`, сгенерирует `WAL_ENC_KEY`, подставит
   `WAL_S3_ACCESS_KEY/SECRET_KEY` (те же, что `S3_*`). Впишите вручную `WAL_S3_ENDPOINT=http://<APP_INTERNAL_IP>:9000`.
3. **Сохраните `WAL_ENC_KEY` офлайн** (рядом с `BACKUP_ENC_PASSPHRASE` и `LITELLM_SALT_KEY`). Потеряли ключ — архив не прочитать, восстановления
   на момент времени не будет; ключ нельзя восстановить из архива. Не генерируйте его повторно: повторный `init` после `drop-db-only`
   создаст новое значение — на VPS 1 `init` запускают только для новых переменных, а `extract-db` выполняют один раз.
4. `infra/deploy/make-env-prod.sh extract-db > /tmp/env.db`, скопировать на VPS 2 в `/opt/rt-db/.env.db`, `shred -u /tmp/env.db`,
   затем `drop-db-only` (убирает `WAL_*` и прочее VPS-2-only с VPS 1).

**Запуск (VPS 2):** `ssh root@<VPS 2> /opt/rt-db/infra/deploy/db-up.sh` — собирает образ, проверяет `wal-g` на CPU сервера, перезапускает
`postgres` (короткий простой базы, приложения переподключаются сами), поднимает `walg`.

**Проверка:**

```bash
docker ps --format '{{.Names}} {{.Status}}' | grep rt-db        # postgres и walg — healthy
docker exec -u postgres rt-db-walg-1 rt-pitr status            # копии в хранилище, archived_count растёт, failed_count не растёт
docker logs rt-db-walg-1 | grep -E 'walg_backup_done|walg_archive_timeout_armed|walg_wal_verify_ok'
docker exec -u postgres rt-db-walg-1 walg-daemon --check-now   # проверка восстановления сразу; ждите pitr_check_ok
```

На VPS 1: бакет `wal` в RustFS непустой (`basebackups_005/`, `wal_005/`).

**Эскалация:** `walg` не становится `healthy` за 10 минут → раздел 5; владелец, если нужны внешнее хранилище или смена параметров.

## 2. Где лежат копии и как их смотреть

| Что | Где |
|---|---|
| Основное хранилище | RustFS VPS 1, бакет `wal`, каталог `WAL_S3_PREFIX` (`pg17`): `basebackups_005/` — базовые копии, `wal_005/` — сегменты WAL. Данные RustFS — том `s3_data` на VPS 1 |
| Внешнее | `<BACKUP_EXT_BUCKET>/wal/<WAL_S3_PREFIX>/`, если задано |
| Дампы `pg_dump` (второй рубеж) | `/var/backups/rt/<штамп>/` на VPS 2 и бакет `backups` RustFS |
| Отметки состояния | том `walg_state` (внутри `walg`: `/walg-state/*`, секунды Unix) |
| Журнал | `docker logs rt-db-walg-1` — JSON-строки `walg_*`, `pitr_*`; сообщения PostgreSQL об архиве — `docker logs rt-db-postgres-1` |

```bash
docker exec -u postgres rt-db-walg-1 rt-pitr status                 # копии, архиватор, отметки
docker exec -u postgres rt-db-walg-1 rt-walg backup-list --detail   # базовые копии с временем начала и конца
docker exec -u postgres rt-db-walg-1 rt-walg wal-show              # какие ветки времени и сегменты есть
docker exec -u postgres rt-db-walg-1 rt-walg --source ext backup-list   # то же во внешнем хранилище
```

## 3. Восстановление на момент времени

**Когда применять:** удалили или испортили данные (нужно «как было вчера в 14:30»); отказ диска/сервера VPS 2; подозрение на порчу базы.
Если нужна сегодняшняя целая база и момент не важен — проще дамп из `deploy.md` п. 4.

**Диагностика:** уточните момент в UTC (`+00`), какие базы затронуты, жива ли боевая база.
Момент должен лежать внутри окна хранения (14 суток) и **не позже последней зафиксированной транзакции в архиве**: иначе PostgreSQL остановится
с `recovery ended before configured recovery target was reached`. Для «самого свежего состояния» используйте `--latest`.

**Действие 1 — восстановить в отдельный контейнер (боевая база не трогается):**

```bash
# VPS 2, из каталога infra репозитория; образ rt-db-postgres:local собирает db-up.sh
infra/db/restore-pitr.sh --target-time "2026-10-22 14:30:00+00"          # на момент (часовой пояс обязателен)
infra/db/restore-pitr.sh --latest --name rt-pitr-now                      # до конца архива
infra/db/restore-pitr.sh --target-time "..." --source ext                 # из внешнего хранилища (если VPS 1 недоступен)
infra/db/restore-pitr.sh --drop [--name rt-pitr]                          # убрать контейнер и том восстановления
```

Скрипт: берёт последнюю базовую копию, завершённую до момента; поднимает контейнер `rt-pitr` (имя должно начинаться с `rt-pitr`, боевые
`rt-db-*` не затрагиваются) на отдельном томе `rt-pitr-data` с `archive_mode=off` — в боевой архив он не пишет; ждёт конца восстановления и
печатает, как проверить и как переключить. Нужно свободного места на диске VPS 2 примерно размер базы (на пилоте < 10 ГБ). **Память:** на VPS 2 всего 2 ГБ, из них лимиты боевых контейнеров — ≈ 1,9 ГБ;
восстановленный экземпляр по умолчанию ограничен 512 МБ (`--memory`, `shared_buffers` 64 МБ). При живой боевой базе не поднимать `--memory` выше — рискуете получить OOM у боевого
`postgres`; для большой базы восстанавливайте на другом хосте с Docker (образ `rt-db-postgres:local` и `.env.db`) либо после остановки `walg`/`backup`. Ключи читает из `/opt/rt-db/.env.db` (`--env-file` для другого файла; для старого архива после ротации — файл со старыми
значениями `WAL_ENC_KEY` и `WAL_S3_PREFIX`).

**Проверка восстановленных данных:**

```bash
docker exec -it -u postgres rt-pitr psql -U postgres -d erp            # или crm / litellm / langfuse
docker logs rt-pitr 2>&1 | grep -E 'recovery stopping|archive recovery complete'   # на какой транзакции остановились
```

**Действие 2 — переключение (решает владелец; запись в базу при этом остановлена):**

*A. Вернуть часть данных (типичный случай).* Снять дамп нужной базы из `rt-pitr` и залить в боевую по `deploy.md` п. 4:
`docker exec -u postgres rt-pitr pg_dump -U postgres -Fc -d erp > /var/backups/rt/pitr-erp.dump`, дальше `DROP/CREATE DATABASE` и `pg_restore`
(или точечно нужные таблицы). Приложения VPS 1 остановить на время заливки.

*B. Заменить кластер целиком (потерян том или повреждена база).* Проверено на стенде: после переключения кластер идёт на новую ветку времени
(`timeline` 2), архив продолжается в тот же каталог, следующее восстановление видит и новые данные.

```bash
# VPS 1: остановить приложения, ходящие в базу (список — deploy.md п. 4)
# VPS 2 (имена томов — по проекту compose; посмотреть: docker volume ls | grep postgres_data):
cd /opt/rt-db/infra && DC="docker compose -f compose/db.yml --env-file /opt/rt-db/.env.db"
$DC stop postgres walg backup && docker stop rt-pitr                      # боевая и восстановленная базы остановлены
docker volume create rt-db_postgres_data_old                              # страховочная копия боевого тома
docker run --rm -v rt-db_postgres_data:/from:ro -v rt-db_postgres_data_old:/to alpine cp -a /from/. /to/
$DC down && docker volume rm rt-db_postgres_data                          # контейнеры и старый том убрать, пересоздать том через compose
$DC up --no-start postgres
docker run --rm -v rt-pitr-data:/from:ro -v rt-db_postgres_data:/to alpine cp -a /from/. /to/
docker run --rm -v rt-db_postgres_data:/d alpine sed -i '/rt-pitr: восстановление/,$d' /d/postgresql.auto.conf   # убрать настройки восстановления
docker rm -f rt-pitr
$DC up -d
docker exec -u postgres rt-db-walg-1 walg-daemon --backup-now             # сразу новая базовая копия на новой ветке времени
# VPS 1: запустить приложения (deploy.sh <sha> / rollback.sh), smoke
```

После успешной проверки данных удалить страховочный том (`docker volume rm rt-db_postgres_data_old`) и том `rt-pitr-data` (`restore-pitr.sh --drop`).

**Эскалация:** восстановление не стартует или данные неполные → не трогать боевое, сохранить `docker logs rt-pitr`, обратиться к владельцу; запасной
путь — дамп `pg_dump` (раздел «Бэкапы» `deploy.md`).

## 4. Ежемесячная проверка восстановления

**Что делает:** `walg` по расписанию (первая — через час после первой копии, затем 1-го числа в 02:00 UTC; `WAL_CHECK_DAY`, `WAL_CHECK_AT_UTC`)
выполняет `rt-pitr check`: скачивает последнюю копию и весь архив во временный каталог (`walg_restore`), поднимает временный PostgreSQL
(без архива и без сети), сверяет с боевой базой — каждая база на месте, таблицы есть, `vector` в `crm`, а отставание архива по LSN не больше 64 МБ.
Если задано внешнее хранилище, проверяются оба. Каталог удаляется.

**Отчёт:** в журнал `walg` пишутся JSON-строки:

```
{"event":"pitr_check_ok","source":"primary","seconds":"8","lag_bytes":"56","databases":"crm=1tables erp=3tables ..."}
{"event":"pitr_check_failed","source":"ext","reason":"..."}
```

и отметки `check_last_success` / `check_last_failure` в `walg_state`.

**Алерт при провале:** контейнер `walg` становится `unhealthy` (`docker ps`), пока не пройдёт следующая проверка; после провала проверка повторяется раз в сутки.
Так же — если успешной проверки нет больше 40 суток или первой нет 3 суток после запуска. Это тот же сигнал, что и у остальных сбоев `walg`;
смотрят его так же, как контейнер `backup`: `docker ps`, `docker inspect --format '{{json .State.Health}}' rt-db-walg-1` (причина — в `Output`).

**Вручную:** `docker exec -u postgres rt-db-walg-1 walg-daemon --check-now` (занимает минуты; нужно свободное место на диске ≈ размер базы).

**Диагностика провала** — по `reason` в журнале:

| Причина | Что делать |
|---|---|
| `не удалось скачать копию из хранилища` | проверить доступность RustFS с VPS 2 (`curl http://<APP_INTERNAL_IP>:9000/health`), ключи `WAL_S3_*`; `backup-fetch` не завершился за 2 ч или завис — чаще всего **неверный `WAL_ENC_KEY`** (в журнале `corrupted chunk`) |
| `PostgreSQL остановился во время восстановления` | в `reason` хвост журнала: нет сегмента WAL (дыра — см. `wal_wal_verify_failed`) или порча; `rt-walg wal-verify integrity timeline` |
| `архив отстаёт от боевой базы на N байт` | архив не успевает: `pg_stat_archiver`, раздел 5 |
| `в восстановленной базе нет таблиц` / `нет расширения vector` | восстановленный кластер пуст — не доверять архиву; немедленно снять дамп `backup-now.sh`, эскалация |
| `восстановление не закончилось за N с` | рост базы: увеличить `WAL_CHECK_TIMEOUT_S` (по умолчанию 3600) |

## 5. Сбои архива и бэкапа (`walg` unhealthy)

Причина — первой строкой в `docker inspect --format '{{json .State.Health}}' rt-db-walg-1`.

| Сообщение healthcheck | Что значит | Что делать |
|---|---|---|
| `базовая копия не делалась больше 26 ч` / `завершилась ошибкой` | `backup-push` падает | `docker logs rt-db-walg-1`; чаще — хранилище недоступно или полно; после устранения `docker exec -u postgres rt-db-walg-1 walg-daemon --backup-now` |
| `archive_command не срабатывает` | PostgreSQL не может отправить сегмент WAL: **WAL копится на диске VPS 2** | `docker logs rt-db-postgres-1 \| grep -A2 'archive command failed'`; проверить хранилище и ключи; после устранения PostgreSQL сам доотправит накопленное (проверено на стенде: дыр нет). Следить за диском: `df -h`, размер `pg_wal` (`docker exec rt-db-postgres-1 du -sh /var/lib/postgresql/data/pg_wal`) |
| `в цепочке WAL-архива есть пропуск` | `wal-verify` нашёл отсутствующий сегмент | `docker exec -u postgres rt-db-walg-1 rt-walg wal-verify integrity timeline`; восстановление на моменты внутри дыры невозможно; сделать новую копию `walg-daemon --backup-now` — моменты после неё снова доступны; пропуск уйдёт из проверки, когда старая копия выйдет из срока хранения |
| `проверка восстановления завершилась ошибкой` | раздел 4 | |
| `архив приостановлен выключателем` | включён аварийный выключатель (см. ниже) | убрать файл `rt-archive-off` после устранения причины и сделать новую копию |
| `pg_wal занимает ... МБ` / `свободно ... МБ` | WAL копится или кончается место | см. «archive_command не срабатывает» и «Крайняя мера» ниже; расчистить диск |
| `копия WAL во внешнее хранилище не обновлялась` | `rclone copy` во внешнее S3 падает (`walg_ext_sync_failed` в журнале) | проверить `BACKUP_EXT_*`, доступность внешнего хранилища; основной архив при этом цел |
| `PostgreSQL недоступен по сокету` | база не запущена или сокет-том не смонтирован | `docker ps`, `docker logs rt-db-postgres-1` |

**Крайняя мера, если диск VPS 2 вот-вот заполнится, а хранилище не вернуть:** не удалять файлы из `pg_wal` вручную (база остановится). Включить
выключатель архива — `wal-push` начнёт отвечать PostgreSQL «успех», ничего не отправляя, и WAL перестанет копиться (рабочий путь без перезапуска базы;
`ALTER SYSTEM SET archive_command` здесь **не работает**: `archive_command` задан флагом `-c` в `db.yml`, а он сильнее `postgresql.auto.conf`):

```bash
docker exec rt-db-postgres-1 touch /var/run/postgresql/rt-archive-off       # включить: WAL больше не копится, цепочка архива рвётся
# ... чинить хранилище/диск ...
docker exec rt-db-postgres-1 rm /var/run/postgresql/rt-archive-off          # выключить после возврата хранилища
docker exec -u postgres rt-db-walg-1 walg-daemon --backup-now               # сразу новая копия: моменты до неё между пропуском недоступны
```

Пока файл есть, healthcheck `walg` красный (`архив приостановлен выключателем`), в журнале `postgres` — строка `архив приостановлен ... НЕ отправлен` на каждый сегмент.
Пропущенные сегменты в хранилище не попадут; `wal-verify` покажет дыру, пока старая копия не выйдет из срока хранения. Решает владелец.

Пороги healthcheck, которые ловят проблему заранее: `pg_wal` больше `WAL_MAX_PGWAL_MB` (2048) или свободно меньше `WAL_MIN_FREE_MB` (4096) на диске данных;
внешняя копия (если задана) не обновлялась больше `WAL_EXT_MAX_AGE_S` (3600 с). `wal-push` ограничен `WAL_PUSH_TIMEOUT_S` (300 с): зависание хранилища даёт
сбой команды и повтор, а не тихую остановку.

Если недавно перезапускали PostgreSQL: `archive_timeout` в только что запущенной базе не действует, пока checkpointer не проснётся (до 5 мин). Сервис `walg`
сам будит его (`pg_reload_conf`) при каждом новом запуске базы — событие `walg_archive_timeout_armed` в журнале.

## 6. Ротация ключа шифрования

Старые копии зашифрованы старым ключом и читаются только им; WAL-G не умеет перешифровать архив на месте. Поэтому ротация = **новый каталог в хранилище + новый ключ**,
старый каталог доживает срок хранения.

1. Сгенерировать ключ: `openssl rand -hex 32`. Сохранить офлайн новое значение **и оставить старое** до удаления старого каталога.
2. В `/opt/rt-db/.env.db` (VPS 2) поменять `WAL_ENC_KEY` и `WAL_S3_PREFIX` (например, `pg17` → `pg17-2`); то же — в офлайн-копии.
3. `ssh root@<VPS 2> /opt/rt-db/infra/deploy/db-up.sh` → PostgreSQL перезапустится и пойдёт писать в новый каталог новым ключом.
4. Сразу `docker exec -u postgres rt-db-walg-1 walg-daemon --backup-now`: до этой копии восстановление из нового каталога невозможно; в эти минуты
   доступны моменты из старого каталога.
5. Проверка: `rt-pitr status`, `walg-daemon --check-now` → `pitr_check_ok`.
6. Через 14+ суток удалить старый каталог из бакета (в RustFS на VPS 1 и во внешнем хранилище) и стереть старый ключ.

Восстановление из старого каталога в переходный период: `restore-pitr.sh --env-file <файл со старыми WAL_ENC_KEY и WAL_S3_PREFIX> ...`.
Та же процедура — после сброса прода на чистые базы (новый кластер): новый `WAL_S3_PREFIX`, иначе имена сегментов совпадут с архивом прежнего кластера и
`wal-push` остановится на «файл уже есть с другим содержимым».

## 7. Бакет заполняется

**Когда:** `df` на VPS 1 показывает рост тома `s3_data`, RustFS отвечает ошибками записи, в `docker logs rt-db-postgres-1` — `archive command failed` с ошибкой
загрузки.

**Диагностика:**

```bash
# VPS 1: сколько занимает RustFS
docker system df -v | grep s3_data ; df -h /var/lib/docker
# сколько копий и WAL в хранилище
docker exec -u postgres rt-db-walg-1 rt-walg backup-list --detail
docker exec -u postgres rt-db-walg-1 rt-walg st ls wal_005/ | wc -l
docker logs rt-db-walg-1 | grep -E 'walg_retention'         # срок хранения отрабатывает после каждой копии?
```

**Действие:**

1. Срок хранения не срабатывает (`walg_retention_failed`, нет `walg_retention_done`) → прочитать причину в журнале `walg`, устранить, запустить
   `docker exec -u postgres rt-db-walg-1 walg-daemon --backup-now` (удаление выполняется после каждой успешной копии).
2. Размер разумен, но места мало → освободить диск VPS 1 (образы, логи: `docker system prune` для неиспользуемого) или расширить диск у провайдера.
3. Сократить `WAL_KEEP_DAYS` (в `.env.db`, затем `db-up.sh` и `walg-daemon --backup-now`) — только с согласия владельца: сокращается окно восстановления.
4. Остаётся заполненным: включить внешнее хранилище (`BACKUP_EXT_*`) и/или вынести RustFS на больший диск; эскалация владельцу.

Ориентир объёма: базовая копия ≈ сжатый размер базы (раз в сутки, 15 штук за срок), WAL ≈ объём записи за 14 суток, сжатый zstd.

**Проверка:** `rt-pitr status` без роста `failed_count`; `walg` healthy.

## 8. Пример проверки на стенде (S0-3)

Стенд: проекты compose `rt-s0-3-s3` (RustFS, настоящие `base.yml` + `prod.yml`, `s3-init` создал бакет `wal`) и `rt-s0-3-db` (`db.yml`);
запись A, пауза, запись B, пауза, запись C; моменты `T1` (между A и B) и `T2` (между B и C) сняты по часам PostgreSQL.

```
запись A
T1 (между A и B) = 2026-10-22 13:54:00+00
запись B
T2 (после B)     = 2026-10-22 13:54:10+00
запись C (после T2)
ожидание архива (archive_timeout=60s)...   → archived=17 failed=0

$ infra/db/restore-pitr.sh --target-time "2026-10-22 13:54:00+00" --name rt-pitr-t1
  базовая копия: base_00000001000000000000000E (источник primary)
  recovery stopping before commit of transaction 790, time 2026-10-22 13:54:05.625373+00
  данные: A                                   ← есть A, нет B

$ infra/db/restore-pitr.sh --target-time "2026-10-22 13:54:10+00" --name rt-pitr-t2
  recovery stopping before commit of transaction 791, time 2026-10-22 13:54:16.274245+00
  данные: A,B                                 ← есть A и B, нет C

$ infra/db/restore-pitr.sh --latest --name rt-pitr-latest
  archive recovery complete
  данные: A,B,C

$ infra/db/restore-pitr.sh --target-time "2026-10-22 13:45:00+00" --name rt-pitr-old
  базовая копия: base_000000010000000000000004 (выбрана более ранняя копия, окончившаяся до момента)
  данные: состояние на 13:45
```

Восстановление из внешнего хранилища (`--source ext`, второй бакет того же RustFS) на `T2` дало тот же результат `A,B`. Проверка восстановления:
`{"event":"pitr_check_ok","source":"primary","seconds":"8","lag_bytes":"56",...}`.

Отдельно проверено на стенде:

- **Отказ хранилища:** PostgreSQL перезапущен с неверным секретным ключом S3 → `archive command failed`, `failed_count` растёт, healthcheck
  `walg`: `UNHEALTHY: archive_command не срабатывает`; ключ возвращён → накопленные сегменты доотправлены, `wal-verify` — `OK`, дыр нет, `healthy`.
- **Неверный `WAL_ENC_KEY`:** проверка восстановления завершается `pitr_check_failed` (`corrupted chunk`), healthcheck красный; верный ключ — `healthy`.
- **Дыра в архиве:** удалён сегмент → `wal-verify`: `MISSING_LOST`, `walg_wal_verify_failed`, healthcheck красный.
- **Срок хранения:** `WAL_KEEP_DAYS=0` после новой копии оставил только копию, покрывающую границу срока, и WAL от неё; старые копии и сегменты удалены.
- **Перезапуск PostgreSQL:** без «будящего» `pg_reload_conf` сегмент закрывался только по checkpoint (≈ через 5 мин); с `walg_archive_timeout_armed` — через ≈ 60 с.

## 9. Ограничения

- WAL-G пишет в одно хранилище; копия во внешнее S3 — отдельное копирование объектов (`rclone copy`, без удалений), срок хранения во внешнем применяется отдельно.
  Лаг внешней копии до 5 минут + время копирования.
- Видимость в CRM («Внешние сервисы» → «Хранилище резервных копий» читает только бакет `backups`) для WAL-архива не сделана — сигнал пока только
  healthcheck `walg` и журнал. Показ статуса WAL-архива в CRM — хвост.
- Бакеты файлов (RustFS) этим архивом не покрыты — только PostgreSQL (файлы ERP — задача S0-1, копия бакетов — отдельно).
- RTO на пилоте не измерен на реальных объёмах: время = скачивание базовой копии (канал 200 Мбит/с) + проигрывание WAL; на пустой базе — секунды.
