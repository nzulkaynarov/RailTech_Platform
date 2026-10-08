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
| CRM (заглушка Фазы 0) | http://localhost |
| API + Swagger | http://localhost:8000/docs |
| Готовность | http://localhost:8000/ready |
| RustFS console (S3) | http://localhost:9001 (`S3_ACCESS_KEY` / `S3_SECRET_KEY` из `.env`) |
| LiteLLM | http://localhost:4000 |
| Langfuse (`make up-obs`) | http://localhost:3000 |

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

Конвертацию файлов выполняет сервис `docling` (образ ~4.4 ГБ, первый `make up` дольше; ADR-0011).

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
