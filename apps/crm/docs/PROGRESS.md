# Прогресс

Обновляется агентом в каждом PR; гейт фазы отмечает **человек** (CLAUDE.md §2.1).

> **Решение владельца (2026-10-08):** реализовывать фазы подряд без остановки на гейтах,
> решения принимать по рекомендациям агента; приёмка всех фаз — одним проходом на dev
> после запуска на локальной машине, затем работа над ошибками. Гейты ниже остаются
> чек-листом этой приёмки.

Текущая фаза: **1 — База знаний и поиск** (реализация готова, ожидает приёмки).

| Фаза | Название | Статус | Гейт (человек) | Даты |
|---|---|---|---|---|
| 0 | Фундамент репозитория и окружения | 🟡 ожидает приёмки | ☐ | старт 2026-10-08 |
| 1 | База знаний и поиск | 🟡 ожидает приёмки | ☐ | 2026-10-08 |
| 2 | Диалоговый агент и клиентский бот (prospect) | ⚪ | ☐ | |
| 3 | Квалификатор, стадии, триггеры | ⚪ | ☐ | |
| 4 | CRM-ядро: пользователи, роли, лиды, handoff | ⚪ | ☐ | |
| 5 | Администрирование | ⚪ | ☐ | |
| 6 | Клиентский режим и документы | ⚪ | ☐ | |
| 7 | Evals, наблюдаемость, CI-гейты | ⚪ | ☐ | |
| 8 | Hardening и подготовка prod | ⚪ | ☐ | |
| 9 | Переезд на prod и пилот | ⚪ | ☐ | |
| 10 | Расширения | ⚪ | ☐ | |

Легенда: ⚪ не начата · 🔵 в работе · 🟡 ожидает приёмки · 🟢 гейт пройден.

## Фаза 0 — детали

| # | Задача (PLAN.md) | Статус | Где |
|---|---|---|---|
| 1 | Структура по SPEC §4, `pyproject.toml`, `package.json`, `Makefile` | ✅ | `backend/`, `frontend/`, `Makefile` |
| 2 | Docker Compose base/dev/prod, healthchecks, профиль `observability` | ✅ (проверка запуска — человек) | `infra/` |
| 3 | `config.py` (pydantic-settings), `.env.example` с комментариями | ✅ | `backend/app/config.py`, `.env.example` |
| 4 | App factory, `/health`, `/ready`, structlog JSON, `request_id` | ✅ | `backend/app/main.py`, `log.py`, `api/health.py` |
| 5 | Alembic, первая миграция (`vector`), схема Procrastinate | ✅ | `backend/alembic/` |
| 6 | ruff, mypy (strict: domain/security/schemas), pre-commit, ESLint/Prettier/tsc | ✅ | `pyproject.toml`, `.pre-commit-config.yaml`, `frontend/` |
| 7 | CI: lint → unit → integration → build; Dependabot; PR-шаблон | ✅ | `.github/` |
| 8 | ADR-шаблон + 0001, 0002, 0003, 0005, 0006 | ✅ accepted 2026-10-08 | `docs/adr/` |
| 9 | `.claude/settings.json`, 9 скиллов | ✅ | `.claude/` |
| 10 | README «dev за 15 минут», карта документов | ✅ | `README.md` |
| 11 | `scripts/bootstrap_dev.sh` | ✅ | `scripts/` |

Дополнительно: ADR-0009 (S3-хранилище RustFS вместо MinIO, SPEC v2.1), ADR-0010 (psycopg 3), runbook `dev-stand.md`, `scripts/smoke_dev.sh`.

### Гейт Фазы 0 (PLAN.md)

- [ ] `scripts/bootstrap_dev.sh` на чистой машине → `make up` → `/ready` 200 (без Langfuse) — **человек**
- [x] CI зелёный (lint, unit, integration, build) — PR #1
- [x] 5 ADR (0001, 0002, 0003, 0005, 0006) приняты — 2026-10-08

### Отложено (осознанно, по плану)

- Refine + Ant Design, orval-генерация клиента — Фаза 4.
- `infra/litellm.config.yaml` с моделями и алиасами — Фаза 1 (ADR-0004); сейчас `model_list: []`.
- `infra/casbin/model.conf`, `policy.seed.csv` — Фаза 4.
- MCP-сервисы в compose — Фазы 1, 2, 6.
- `seed`, `backup`, `restore`, `smoke-prod`, `promptfoo` — цели-заглушки с указанием фазы.
- `pip-audit`/`npm audit` в CI — Фаза 8.

## Фаза 1 — детали

| # | Задача (PLAN.md) | Статус | Где |
|---|---|---|---|
| 1 | Миграция `products`, `kb_documents`, `kb_chunks`, `kb_gaps`; ADR-0004, ADR-0007 | ✅ | `alembic/versions/*_kb_tables.py`, `docs/adr/` |
| 2 | `infra/litellm.config.yaml` с алиасами; `integrations/litellm.py` | ✅ | ADR-0004 |
| 3 | Ингест: S3 → docling → чанки → embeddings → `kb_chunks`, статусы, ретраи, идемпотентность по версии | ✅ (docling-serve, ADR-0011) | `services/kb/ingest.py`, `tasks/ingest.py` |
| 4 | `kb-mcp`: `search_kb`, `list_products`; гибридный поиск RRF, фильтр `product_key`, порог | ✅ | `mcp/kb_server.py`, `services/kb/search.py` |
| 5 | CLI ингеста | ✅ `python -m app kb-ingest` / `make kb-ingest` | REST-загрузка — в Фазе 5 с RBAC (временный admin-токен не нужен) |
| 6 | Демо-KB: 3 документа ru + 1 uz | ✅ | `backend/evals/fixtures/kb/` |
| 7 | Тесты: unit чанкинга и RRF; integration поиска | ✅ (+ 15 вопросов: `make kb-eval` с ключами) | `tests/` |

### Гейт Фазы 1 (проверяет человек с ключами моделей)

- [ ] `make kb-demo` → 4 документа `done`; `make kb-eval` → top-3 ≥ 13/15, uz ≥ 3/4.
- [ ] `make kb-ingest f=<pdf с таблицей>` → таблица в чанке читаема (markdown).
- [ ] Стоимость ингеста демо-KB — из логов LiteLLM/Langfuse, записать в PR.
