# ADR CRM-0013. Бэкапить pg_dump той же версии, что сервер (сейчас 17), и копией бакетов кодом приложения в контейнере backup

- Статус: accepted (2026-10-12, владелец: «принимаю все рекомендации», Q-007)
- Дата: 2026-10-08
- Авторы: агент (по поручению владельца принимать решения по рекомендациям)
- Связано: SPEC §2 (бэкапы), §14; PLAN Фаза 8 задача 4; ADR-0009 (RustFS)

## Контекст и проблема

SPEC §2 оставил выбор инструмента зеркалирования S3 на Фазу 8. Нужно: ежедневно,
ротация 14 дней, восстановление одной командой и проверяемое на dev. Версия `pg_dump`
должна совпадать с сервером (16): дамп `pg_dump` 17 содержит `SET transaction_timeout`,
который PostgreSQL 16 не понимает при восстановлении.

## Драйверы решения

- Совпадение версии клиента PostgreSQL с сервером (16).
- Минимум новых зависимостей и образов; всё проверяемо тестами.
- Бэкап не должен получать ключи моделей, JWT и токен бота.

## Рассмотренные варианты

1. Образ `postgres:16-alpine` + `aws-cli`/`rclone` + cron.
2. Отдельный target `backup` backend-образа: `postgresql-client-16` из официального PGDG,
   копия бакетов — CLI приложения `python -m app s3-mirror` (aiobotocore уже в проекте).
3. Снапшоты томов Docker / VPS-провайдера.

## Решение

Вариант 2. Сервис `backup` (профиль `backup`, на prod всегда включён) ежедневно в 22:00 UTC
(03:00 Asia/Tashkent) выполняет `ops/backup.sh`: `pg_dump --format=custom` + `s3-mirror`
в `/backups/<UTC-штамп>/`, `SHA256SUMS`, ротация по `BACKUP_KEEP_DAYS` (14).
`ops/restore.sh` проверяет суммы, делает `pg_restore --clean --if-exists --exit-on-error`
и загружает объекты обратно. Обёртки для человека: `scripts/backup.sh`, `scripts/restore.sh`.

### Последствия

- Хорошо: один образ и один S3-клиент на весь проект; бэкап покрыт integration-тестом
  (выгрузка → восстановление в другой бакет) и проверен вручную на Postgres 16.
- Хорошо: окружение backup — только БД и S3.
- Плохо: копия хранится на том же VPS (том `backups`); вынос копии вне сервера — шаг
  runbook (rsync/rclone человеком) до появления внешнего бакета.
- Плохо: `Content-Type` объектов при восстановлении — `application/octet-stream`
  (приложение отдаёт тип из БД, поэтому на работу не влияет).

### Как проверяем

CI job `build` собирает образ `backup` и проверяет `pg_dump` 16; integration `test_s3_mirror`;
гейт Фазы 8 — восстановление prod-бэкапа на dev (runbook `backup-restore.md`).

## Поправка 2026-10-13 (RailTech Platform, M0)

Сервер ансамбля — PostgreSQL 17 (`docs/history/ARCHITECTURE.md` §10, `infra/compose/base.yml`), поэтому правило «версия клиента = версия сервера» означает `postgresql-client-17`: `backend/Dockerfile` (target `backup`), `ops/backup.sh`, `ops/restore.sh`, образы Postgres в `infra/docker-compose.yml`, `scripts/test_int_local.sh`, `scripts/ci_local.sh` и workflows переведены на 17. Аргументы ADR не меняются.
