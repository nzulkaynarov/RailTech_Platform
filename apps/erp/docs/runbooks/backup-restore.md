# Резервное копирование и восстановление ERP

## Когда применять

- Регулярное плановое создание снимка данных перед мажорным обновлением или опасными миграциями.
- Аварийное восстановление базы данных `erp` и файлов после сбоя сервера или повреждения данных.
- Разворачивание копии продуктовой базы на dev-стенде для отладки инцидентов.
- Резервное копирование медиафайлов (вложения сделок, аватары, логотипы, сгенерированные PDF).

---

## Архитектура хранилища данных

1. **Реляционная база данных**: PostgreSQL 17, база `erp`, владелец — пользователь `erp`.
2. **Файловое хранилище (Media)**: S3-совместимое хранилище RustFS (`infra/compose`), бакет `erp`. Локальный dev-фолбэк — именованный docker volume `erp_media` (путь `/app/media`).
3. **Изоляция**: База `erp` не имеет общих таблиц или внешних ключей к базе `crm`. Связи хранятся через строковые/числовые внешние ID (`crm_client_id`, `crm_lead_id`).

---

## Диагностика перед снятием дампа

Проверьте размер базы и доступное дисковое пространство:

```bash
docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env exec postgres psql -U erp -d erp -c "
SELECT pg_size_pretty(pg_database_size('erp')) AS erp_db_size;
"
```

---

## Порядок действий

### 1. Создание резервной копии базы данных (Бэкап)

1. Для предотвращения частичной записи фоновых задач приостановите воркеры:
   ```bash
   docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env stop erp-worker erp-worker-ai
   ```
2. Создайте сжатый кастомный дамп PostgreSQL (`pg_dump` в формате `custom` с контрольными суммами):
   ```bash
   BACKUP_FILE="erp_backup_$(date +%Y%m%d_%H%M%S).dump"
   docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env exec -T postgres pg_dump -U erp -d erp -F c -b -v > "${BACKUP_FILE}"
   echo "Бэкап сохранён: ${BACKUP_FILE}"
   ```
3. Возобновите работу воркеров:
   ```bash
   docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env start erp-worker erp-worker-ai
   ```

### 2. Бэкап медиафайлов (S3 / RustFS)
Если используется RustFS стенда:
```bash
# Синхронизация бакета erp в локальный архив
mkdir -p backups/media
docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env exec -T erp-backend python manage.py shell -c "
import shutil, os
if os.path.exists('/app/media'):
    shutil.make_archive('/tmp/erp_media_backup', 'gztar', '/app/media')
    print('Media archive created at /tmp/erp_media_backup.tar.gz')
"
docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env cp erp-backend:/tmp/erp_media_backup.tar.gz backups/media/
```

### 3. ⚠️ Восстановление базы данных из дампа
⚠️ **Внимание: восстановление перезаписывает существующие таблицы базы `erp`!**

1. Остановите сервисы, обращающиеся к базе данных:
   ```bash
   docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env stop erp-backend erp-worker erp-worker-ai erp-beat
   ```
2. Завершите оставшиеся активные подключения к базе `erp`:
   ```bash
   docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env exec -T postgres psql -U postgres -c "
   SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'erp' AND pid <> pg_backend_pid();
   "
   ```
3. Восстановите схему и данные с флагами `--clean --if-exists`:
   ```bash
   docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env exec -T postgres pg_restore --clean --if-exists -U erp -d erp < "${BACKUP_FILE}"
   ```
4. Примените миграции (если дамп был снят на более ранней ревизии кода):
   ```bash
   docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env run --rm erp-backend python manage.py migrate --noinput
   ```
5. Запустите остановленные сервисы:
   ```bash
   docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env start erp-backend erp-worker erp-worker-ai erp-beat
   ```

---

## Проверка восстановления

1. Проверьте liveness и readiness API:
   ```bash
   curl -s http://erp.localhost/api/v1/ready/
   ```
   *Ожидается статус `ok` и все флаги `true`.*
2. Выполните проверку ключевых счётчиков сущностей:
   ```bash
   docker compose -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env exec erp-backend python manage.py shell -c "
   from parties.models import Company
   from sales.models import Deal, Quote
   print('Companies count:', Company.objects.count())
   print('Deals count:', Deal.objects.count())
   print('Quotes count:', Quote.objects.count())
   "
   ```
3. Войдите в веб-интерфейс ERP SPA под учётной записью администратора и проверьте доступность карточек сделок и каталога.

---

## Эскалация

При ошибках `pg_restore` (например, нарушение внешних ключей или несовпадение кодировок):
1. Сохраните полный лог восстановления: `pg_restore -v ... 2> restore_errors.log`.
2. Зафиксируйте версию PostgreSQL на источнике и приёмнике: `psql --version`.
3. Немедленно обратитесь к инженеру инфраструктуры платформы.
