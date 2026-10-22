# RailTech CRM

Внутренняя CRM с ИИ-ассистентом первой линии в Telegram (диалоговый агент + асинхронный квалификатор), единым веб-интерфейсом команды и сервисным режимом для клиентов после сделки.

Статус: **Фаза 0 — фундамент** (см. [`docs/PROGRESS.md`](docs/PROGRESS.md)).

## Карта документов

| Документ | Что в нём |
|---|---|
| [`BUSINESS.md`](BUSINESS.md) | Зачем проект, пользователи, сценарии C1–C6, критерии успеха |
| [`SPEC.md`](SPEC.md) | Источник истины по архитектуре (ссылки вида `SPEC §7.1`) |
| [`PLAN.md`](PLAN.md) | Фазы 0–10, задачи, DoD, гейты |
| [`CLAUDE.md`](CLAUDE.md) | Правила работы для Claude Code |
| [`docs/PROGRESS.md`](docs/PROGRESS.md) | Текущая фаза и статусы |
| [`docs/QUESTIONS.md`](docs/QUESTIONS.md) | Открытые вопросы к человеку |
| [`docs/adr/`](docs/adr/README.md) | Архитектурные решения (MADR) |
| [`docs/runbooks/`](docs/runbooks/README.md) | Эксплуатация |
| [`docs/api/openapi.json`](docs/api/openapi.json) | Контракт API (генерируется `make openapi`) |

При противоречиях: `BUSINESS.md` > `SPEC.md` > `PLAN.md` > код.

## dev-стенд за 15 минут

Нужно: Docker (Engine 24+ / Desktop) с `docker compose` v2, `make`, `curl`, `openssl`. 4 ГБ свободной RAM (8 ГБ — с Langfuse).

```bash
git clone <repo> railtech-crm && cd railtech-crm
scripts/bootstrap_dev.sh      # создаёт .env со случайными секретами, собирает и поднимает стенд, ждёт /ready
make smoke-dev                # /health и /ready напрямую и через Caddy
```

После запуска:

| Что | Адрес |
|---|---|
| CRM | http://localhost |
| API + Swagger | http://localhost:8000/docs |
| Готовность | http://localhost:8000/ready |
| RustFS console (S3) | http://localhost:9001 (`S3_ACCESS_KEY` / `S3_SECRET_KEY` из `.env`) |
| LiteLLM | http://localhost:4000 |
| Langfuse (`make up-obs`) | http://localhost:3000 |

Порты выше — по умолчанию; если какой-то занят другим проектом, переопределите его в `.env` (`DEV_API_PORT`, `DEV_POSTGRES_PORT`, `HTTP_PORT` и др., см. `.env.example`).

Повседневные команды: `make up`, `make down`, `make ps`, `make logs s=api`, `make migrate`. Список — `make help`. Проблемы — [`docs/runbooks/dev-stand.md`](docs/runbooks/dev-stand.md).

### База знаний (Фаза 1)

1. Впишите ключи моделей в `.env`: `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` (ADR-0004), затем `make up`.
2. `make kb-demo` — загрузить демо-KB; `make kb-eval` — проверить поиск (гейт: top-3 ≥ 13/15).
3. Свои документы: `make kb-ingest f=path/to/file.pdf lang=ru product=pos-integration`.

### Бот и диалоговый агент (Фаза 2)

1. Создайте dev-бота у @BotFather, впишите `TELEGRAM_BOT_TOKEN` в `.env` (`TELEGRAM_MODE=polling`), затем `make up`.
2. Напишите боту `/start` → приветствие и согласие; после «Согласен» вопросы по демо-KB получают ответ.
3. Трейсы ходов: `make up-obs`, создайте проект и API-ключи в Langfuse, впишите `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`.
4. `make eval` — golden-кейсы агента с judge и кейсы квалификатора (нужны ключи моделей и `make kb-demo`; гейты: faithfulness ≥ 0.9, выдуманных чисел 0; эскалации recall ≥ 0.9, precision ≥ 0.8, стадии ≥ 0.85).
5. Лента решений по лиду (квалификатор, стадии): `curl -s localhost:8000/api/v1/leads/<id>/decisions` (только dev).

Команды бота: `/start`, `/lang`, `/help`, `/human` (передать менеджеру), `/delete` (обезличить переписку).

### CRM и канал команды (Фаза 4)

1. Первый администратор — мастер первого запуска: откройте http://localhost (CRM сама откроет `/setup`), введите одноразовый код из логов api (`make logs s=api | grep setup_code_issued`, действует 24 ч) и создайте админа; затем компания и рабочие часы, остальное — чек-лист «Настройка CRM» на главной. Альтернатива из консоли: `make create-admin email=you@company.uz name="Имя"` (временный пароль выводится один раз).
2. Откройте http://localhost, войдите. Менеджеров создаёт админ в разделе «Пользователи» (временный пароль, обязательная смена при первом входе).
3. Канал команды: создайте приватный канал, добавьте бота администратором, узнайте `channel_id` (например, переслав пост боту @getidsbot) и выполните `make settings key=notifications value='{"channel_id": -100…}'`.
4. Привяжите свой Telegram: админ вписывает ваш Telegram ID в карточке пользователя — тогда кнопка «Забрать» в канале работает от вашего имени.
5. Демо-лиды без Telegram: `make seed pass=<пароль демо-менеджера>` (менеджер `manager@demo.local`).

### Администрирование (Фаза 5)

В CRM у админа: «База знаний» (загрузка файлов, ручные документы, тест «что найдёт бот»), «Пробелы KB», «Настройки» (тексты на 3 языках с предпросмотром, правила эскалации с «сухим прогоном»), «Дашборд», «Аудит». Изменения настроек действуют без рестарта (≤ 30 с).

### Клиенты и документы (Фаза 6)

После «Сделки» в карточке лида — «Сделать клиентом». В карточке клиента: подтверждение Telegram-аккаунтов (бот выдаёт документы только им), загрузка документов (тип, номер, дата, видимость клиенту), журнал доступа, сервисные запросы. Клиент пишет боту «пришлите договор за июль» — бот присылает файл.

E2E (Playwright) против стенда: `make test-e2e-local` с `E2E_MANAGER_PASSWORD=<пароль>`; в CI — job `e2e`.

Конвертацию файлов выполняет сервис `docling` (образ ~4.4 ГБ, первый `make up` дольше; ADR-0011).

### Качество и эксплуатация (Фаза 7)

- `make eval` — golden-набор на реальных моделях (пороги SPEC §12); в PR при изменении промптов/агентов — job **Eval gate** с комментарием-отчётом (нужны GitHub Secrets, `docs/runbooks/eval-gate.md`).
- `LITELLM_API_KEY=<LITELLM_MASTER_KEY> make promptfoo` — матрица «промпт × модель».
- В канал команды: алерты ⚠️ (упавшие задачи, LiteLLM, очередь, бюджет) и «📊 Итоги дня» в 18:05.
- `scripts/sample_dialogs.py` — 20 случайных диалогов для еженедельной разметки (`docs/evals/labeling.md`).

## prod (Фаза 8)

Выкладка — тегом `v*` (workflow **Deploy prod**: образы в GHCR → VPS → бэкап → миграции → smoke → откат при провале). Первичная настройка VPS и откат — `docs/runbooks/deploy.md`.

```bash
make up-prod            # на VPS: pull образов IMAGE_TAG + up (с сервисом backup)
make smoke-prod         # TLS, /ready, заголовки безопасности, закрытый API
scripts/backup.sh --prod / scripts/restore.sh --prod <штамп>   # ADR-0013, runbook backup-restore
scripts/set_webhook.py  # состояние webhook prod-бота
make load-test          # 50 параллельных диалогов на dev: p95 ≤ 6 с (реальные модели)
```

## Разработка без Docker

```bash
make install    # uv sync + pnpm install (нужны uv и pnpm 10: pip install uv; npm i -g pnpm@10)
make check      # ruff, mypy, eslint, prettier, tsc, pytest (unit), vitest — перед каждым коммитом
make openapi    # экспорт docs/api/openapi.json (CI проверяет актуальность)
uv tool install pre-commit && pre-commit install   # хуки: ruff, gitleaks, prettier, eslint
```

Integration-тесты (`make test-int`) требуют Postgres 16 + pgvector и RustFS — их запускает CI; локально — с переменными `POSTGRES_*`, `S3_ENDPOINT`.

## Структура

```
backend/    FastAPI, бот, агенты, воркер (Python 3.12, uv)   — SPEC §4
frontend/   React 18 + TypeScript + Vite (Refine — Фаза 4)
infra/      Docker Compose base/dev/prod, Caddy, LiteLLM
scripts/    bootstrap_dev.sh, smoke_dev.sh, export_openapi.py
docs/       ADR, runbooks, OpenAPI, прогресс, вопросы
.claude/    настройки и скиллы Claude Code
```
