# Волна 10 — этап 0 «Чистый лист и надёжность» (версия 0.9)

Архитектор, 2026-10-23. Основание: стратегия §1.1, §7; ADR-0013, ADR-0017; карт-бланш владельца 2026-10-23 (прод — на чистых базах,
данных и аккаунтов нет). Параллельно идут волна 9 (роли, `apps/crm` модели и ролевой каталог) и волна 11 (шина: интеграционный
код CRM и ERP, `packages/rt-bus`, `packages/contracts/events`) — их зоны не трогать.

## 0. Промпт лида — одним сообщением

```
Ты — лид разработки RailTech Platform (ORCHESTRATOR §4.1), ведёшь волну 10 «Этап 0: чистый лист и надёжность» по
docs/runbooks/wave10-stage0.md. Код сам не пишешь. Прочитай: CLAUDE.md корня, ORCHESTRATOR.md (§3, §4.1, §7), docs/HANDOFF.md,
docs/strategy/2026-10-23-platform-architecture-strategy.md (§1.1, §3.7, §7), ADR-0013, ADR-0017, этот runbook целиком,
docs/research/2026-10-23-architecture/arch-audit-current.md (§1, §3, §7), docs/runbooks/deploy.md, infra/compose/*.yml, infra/caddy/*.
Исполнители — субагенты model "sonnet", по одному на задачу, не больше трёх одновременно, worktree .claude/worktrees/<задача> от
свежего origin/main (зависимости ставишь ты). Преамбула исполнителя — docs/runbooks/wave7-platform-p0.md §3 с подставленными
значениями. Ревью — свежий субагент ≠ исполнитель, по «готово, когда». Перед автослиянием — merge origin/main, повтор проверок,
make deploy-check для задач infra; затем gh pr merge --auto --merge <n>. CI не опрашиваешь, логи CI не читаешь; перед шагом — одна
проверка своих PR (gh pr view --json state,mergeable,mergeStateStatus,statusCheckRollup). Уборка после слияния — сразу (TaskStop,
worktree, ветка, тестовые контейнеры). Правка ci.yml, ci_local.sh, deploy.yml разрешена владельцем. Прод не деплоишь — деплой и сброс
прода делает архитектор после закрытия волны (§3.8). Вопросы вне задачи — архитектору сообщением.
Закрытие: docs-PR (PROGRESS — раздел «Стратегия: этап 0», HANDOFF п. 13), отчёт архитектору: PR, что проверено, что осталось.
```

## 1. Раскладка

| Задача | Что | Зоны | Ветка |
|---|---|---|---|
| **S0-1** | Файлы ERP — в RustFS | `apps/erp/backend/core/settings/project.py`, `core/storage.py`, `infra/compose/*`, `.env.example`, `infra/.env.prod.example` | `s0/erp-files-s3` |
| **S0-2** | Redis: брокер и кэш раздельно | `infra/compose/*`, `apps/erp/backend/core/settings/infra.py`, `apps/platform/bff/app/config.py` (только адрес), примеры env | `s0/redis-split` |
| **S0-3** | WAL-архив PostgreSQL и восстановление на момент времени | `infra/compose/db.yml`, `infra/db/*`, `infra/deploy/*`, runbook | `s0/wal-archive` |
| **S0-4** | Бот — отдельный процесс от API CRM | `apps/crm/backend/app/main.py`, `app/bot/*` (запуск), `infra/compose/*`, `infra/caddy/*` (маршрут вебхука) | `s0/crm-bot-process` |
| **S0-5** | Закрыть снаружи машинный API ERP и `/admin`; выключить старую подпись вебхуков | `infra/caddy/Caddyfile.prod`, `Caddyfile.dev`, `apps/crm/backend/app/config.py` (флаг), примеры env | `s0/edge-hardening` |
| **S0-6** | Журналы доступа Caddy, `X-Request-ID` от входа, проброс CRM → ERP по HTTP | `infra/caddy/*`, `apps/crm/backend/app/integrations/erp_http.py` | `s0/request-id-edge` |
| **S0-7** | Проверка старта образов под CPU `qemu64` в CI | `.github/workflows/*`, `infra/deploy/cpu-baseline-check.sh`, `scripts/` | `s0/qemu64-check` |
| **S0-8** | Сценарий сброса прода на чистые базы и первый запуск | `infra/deploy/reset-prod.sh`, `docs/runbooks/deploy.md` | `s0/prod-reset` |

Раунды: 1 — S0-1 ∥ S0-2 ∥ S0-5; 2 — S0-3 ∥ S0-4 ∥ S0-6; 3 — S0-7 ∥ S0-8. Зоны compose пересекаются у S0-1, S0-2, S0-4 —
разносить по раундам или сливать последовательно с merge main.

## 2. «Готово, когда»

### S0-1. Файлы ERP в RustFS
- ERP пишет и читает все файлы (PDF, сканы, загрузки портала, медиа) через S3-хранилище: `MINIO_ENDPOINT` и ключи заданы в
  compose dev и prod на RustFS; бакеты `erp-private` (по умолчанию), `erp-public` (только то, что раньше было публичным),
  `erp-temp`; `s3-init` создаёт их; том `erp_media` удалён из compose.
- Выдача файлов клиенту и сотруднику — по подписанным ссылкам, как раньше; поведение для пользователя не меняется.
- Переноса существующих файлов нет (прод сбрасывается, §3.8).
Проверка: `make check-erp`; на проекте compose `-p rt-s0-1`: выпуск PDF КП, загрузка в портал, скачивание — файлы в бакете,
локальной папки медиа нет; `make deploy-check`.

### S0-2. Redis раздельно
- Два экземпляра: `redis-broker` (Celery-брокер и результаты, Channels — с записью на диск `appendonly yes`, `noeviction`,
  лимит памяти под нагрузку) и `redis-cache` (кэш Django, троттлинг, одноразовые `jti`, сессии BFF — `volatile-lru`, у всех
  ключей TTL); Langfuse (BullMQ требует `noeviction`) — на `redis-broker` отдельной БД 3 (решение архитектора, S0-9).
- Кэш ERP переживает отказ `redis-cache`: при недоступности — работа без кэша, предупреждение в журнале, без 5xx
  (`IGNORE_EXCEPTIONS` или своя обёртка; для `jti` SSO — отказ входа безопаснее, чем пропуск: явный текст ошибки).
- Пароли — разные на экземпляр.
Проверка: тест ERP «кэш недоступен — ответ 200»; `make deploy-check`; на проекте compose — остановка `redis-cache` не роняет ERP.

### S0-3. WAL-архив
- WAL-G в контейнере PostgreSQL (или боковом) на VPS2: непрерывный архив WAL и ежедневная базовая копия в S3 — по умолчанию
  бакет `wal` RustFS на VPS1 (копия уже вне VPS2), опционально внешнее S3 (`BACKUP_EXT_*`, когда владелец даст хранилище) —
  туда же; шифрование; срок хранения 14 дней.
- `infra/db/restore-pitr.sh` — восстановление на заданный момент в отдельный контейнер; `restore-check` по расписанию раз в
  месяц с отчётом в журнал и алертом при провале.
- Цель RPO ≤ 5 мин (`archive_timeout = 60s`).
Проверка: на стенде — запись, ожидание, восстановление на момент до записи и после; runbook `docs/runbooks/backup-pitr.md`.

### S0-4. Бот отдельно от API
- Сервис `crm-bot` (`python -m app bot`): polling или приём вебхука Telegram — в нём; `crm-api` бота не запускает.
- В режиме webhook Caddy отдаёт `/telegram/webhook` в `crm-bot`; смена режима и токена из «Подключений» доходит до `crm-bot`
  (через БД и перезапуск процесса бота в нём же).
- Перезапуск или падение `crm-api` не останавливает бота и наоборот.
Проверка: `make check-crm`, `ci_local.sh crm-integration` (с `ITEST_NS`); на проекте compose — остановка `crm-api`, бот отвечает
(тестовым токеном владельца на стенде — если его нет, проверка обработчика на фейковом Bot API).

### S0-5. Граница наружу
- Caddy prod и dev: `/api/integration/*` и `/admin*` домена ERP снаружи — 404; CRM и коннекторы ходят по внутренней сети
  (`http://erp-backend:8000`).
- `ERP_WEBHOOK_SIGN_LEGACY` по умолчанию `false`, код приёма старой подписи v1 удалён.
Проверка: `make deploy-check`; curl снаружи на стенде — 404; тест CRM на отказ подписи v1.

### S0-6. Идентификатор запроса
- Caddy пишет журнал доступа JSON (stdout) и ставит `X-Request-ID`, если его нет, во все апстримы.
- CRM передаёт `X-Request-ID` во все HTTP-вызовы ERP (общий клиент, без нового `AsyncClient` на вызов).
- Проброс в очереди и события — задача волны 11 (`correlationid` в конверте).
Проверка: один запрос через Caddy виден по одному идентификатору в журналах Caddy, CRM и ERP.

### S0-7. Проверка CPU
- В CI (задание infra) и в `make deploy-check`: каждый собранный образ запускает свою стартовую команду проверки (`python -c
  "import …"`, `--version`) под эмуляцией CPU `qemu64` (`qemu-x86_64 -cpu qemu64` в user-mode или аналог); падение «illegal
  instruction» или «x86-64-v2 required» — красное задание с именем образа.
- Если эмуляция на раннере GitHub невозможна — исполнитель докладывает с доказательством, лид присылает архитектору.

### S0-8. Сброс прода и первый запуск
- `infra/deploy/reset-prod.sh` (запуск на VPS1 под `deploy`, подтверждение вводом имени домена): останавливает приложения,
  пересоздаёт базы `crm` и `erp` на VPS2 (база `litellm` сохраняется — там ключи моделей), очищает бакеты RustFS приложений,
  снимает тома приложений, затем обычный `deploy.sh` текущего релиза; печатает, где взять код первого запуска.
- Runbook: порядок «сброс → `/setup` CRM → Платформа: Admin → Подключения (бот, ERP — кнопка «Подключить ERP») → роли».
Проверка: прогон на стенде (локальная копия prod-compose), `make deploy-check`, shellcheck.

## 3. После волны (архитектор)

1. Деплой main на прод и **сброс прода** по S0-8 (разрешено владельцем 2026-10-23).
2. Первый запуск: `/setup`, «Подключить ERP», проверка всех доменов; данные для входа — владельцу.
3. Гейт этапа 0 (стратегия §2.2): восстановление на момент времени проверено на стенде; события не теряются (закрывает волна 11).
