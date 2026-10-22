# Runbook: серверы ансамбля (прод)

Решение владельца 2026-10-13: два VPS с внутренней сетью. Распределение ресурсов — агент Infra (ниже).
Реализация прод-стенда — задача **M5-INF-01** (compose `prod.yml` + `db.yml`, Caddy prod, деплой-workflow,
бэкапы, мониторинг); этот документ фиксирует раскладку, чтобы M1–M4 не делали предположений.

## Серверы

| | VPS 1 — `app` | VPS 2 — `db` |
|---|---|---|
| Публичный IP | `176.101.56.141` | `170.168.6.209` |
| Ресурсы | 4 vCPU · 8 ГБ ОЗУ · NVMe 120 ГБ | 2 vCPU · 2 ГБ ОЗУ · NVMe 40 ГБ |
| Сеть | TAS-IX 200 Мбит/с · Интернет 200 Мбит/с · внутренняя сеть между VPS | то же |
| Роль | все приложения и общие сервисы, вход (Caddy, три домена) | PostgreSQL 17 (базы `crm`, `erp`, `litellm`, `langfuse`), бэкапы |
| Внутренний IP | **уточнить у владельца** (OWNER-CHECKLIST) | **уточнить у владельца** |

Почему так: база — единственное, что нельзя потерять, и единственное, что не нуждается в CPU и памяти
приложений; отдельный хост даёт ей свою память, свой диск и независимый бэкап. 2 ГБ для PostgreSQL двух
небольших баз достаточно (`shared_buffers` 512 МБ, `work_mem` 8 МБ, `max_connections` 100). Langfuse с ClickHouse
на VPS 2 не помещается, поэтому остаётся на VPS 1 профилем.

## Что где (compose-проекты)

**VPS 1 (`infra/compose/base.yml` + `prod.yml`, проект `rt-platform`):**

| Сервис | Лимит памяти | Примечание |
|---|---|---|
| `caddy` | 64 МБ | четыре домена, TLS (ACME), security headers |
| `redis` | 128 МБ | БД 0 Langfuse, 1 ERP Celery, 2 ERP Channels, 3 сессии BFF Платформы |
| `rustfs` | 512 МБ | бакеты CRM, `erp`, `langfuse`, `backups` |
| `litellm` | 768 МБ | шлюз моделей, свой образ `rt-litellm` (Debian, см. «CPU прод-VPS»); его БД `litellm` — на VPS 2 |
| `crm-api`, `crm-bot`, `crm-worker` | 512 + 512 + 512 МБ | `crm-bot` (S0-4) — Telegram отдельным процессом, реплика одна; факт на стенде ≈ 320–340 МБ у каждого из `crm-api`/`crm-bot` |
| `crm-mcp-kb`, `crm-mcp-crm`, `crm-mcp-docs` | 3 × 256 МБ | |
| `crm-web` | 64 МБ | статика за Caddy |
| `erp-backend` | 768 МБ | Daphne |
| `erp-mcp` | 256 МБ (лимит; факт ≈ 200 МБ) | инструменты ERP для агента CRM, SDK `mcp`, образ `erp-backend` (FIX-36); порт 8104 только внутри сети; файл `packages/contracts/mcp-tools.json` монтируется в контейнер (контракты шины вшиты в образ, B3); профиль `mcp` включён на проде (`RT_PROFILES=mcp`): бот CRM в сервисном режиме берёт из него данные клиента (M3-CRM-07) |
| `erp-worker`, `erp-worker-ai`, `erp-beat` | 512 + 384 + 192 МБ | |
| `erp-web` | 64 МБ | nginx со сборкой |
| `platform-bff` | 256 МБ (лимит; факт ≈ 150 МБ) | BFF Платформы (INF-P0-5): uvicorn, 2 процесса; БД нет, сессии в Redis БД 3 |
| `platform-web` | 64 МБ | статика Платформы за Caddy |
| `s3-init`, `crm-migrate`, `litellm-seed`, `erp-ai-gateway` и одноразовые `run` миграций | 256–384 МБ | одноразовые, живут секунды при деплое; в «Итого постоянно» не входят; pg_dump-гейт идёт в отдельном контейнере с `pg_dump` (без лимита, до `up`) |
| **Итого постоянно** | **≈ 6,2 ГБ** (5,2 + `erp-mcp` ≈ 0,2 + Платформа 0,3 + `crm-bot` 0,5 по лимитам) | + ОС ≈ 0,5 ГБ; остаётся ≈ 1,3 ГБ из 8 |
| `docling` (профиль `kb-ingest`) | 1,5 ГБ | **на проде не используется** (M5-CRM-02): база знаний принимает только Markdown (`docs/kb/FORMAT.md`), docling нужен лишь для текста документов клиентов; профиль — опция на случай, если сервер станет мощнее |
| `clickhouse`, `langfuse-web`, `langfuse-worker` (профиль `observability`) | 768 + 768 + 512 МБ | включать, когда `docling` выключен; дашборд затрат ИИ (M3-CRM-09) не зависит от Langfuse — он читает БД LiteLLM |

`docling` и Langfuse одновременно в 8 ГБ не помещаются — это осознанный выбор, не ошибка конфигурации.
Если трейсы нужны постоянно, вариант — апгрейд VPS 1 до 16 ГБ (решение владельца при пилоте).

**VPS 2 (`infra/compose/db.yml`, проект `rt-db`):**

| Сервис | Лимит памяти | Примечание |
|---|---|---|
| `postgres` (образ `rt-db-postgres`: pgvector 0.8.7-pg17 + WAL-G) | 1,25 ГБ | слушает только внутренний IP; `pg_hba`: только внутренний IP VPS 1; непрерывный архив WAL в бакет `wal` RustFS (S0-3) |
| `walg` (тот же образ) | 384 МБ (лимит; факт — десятки МБ, пик ≈ 50 МБ на проверке восстановления малой базы) | ежедневная базовая копия WAL-G 21:00 UTC, срок хранения 14 дней, `wal-verify`, ежемесячная проверка восстановления; `unhealthy` = сбой архива — `docs/runbooks/backup-pitr.md`. Всего лимитов на VPS 2 ≈ 1,9 ГБ из 2 ГБ: разовое восстановление `restore-pitr.sh` (по умолчанию 512 МБ) запускать с оглядкой |
| `backup` | 256 МБ | ежедневно 22:00 UTC (03:00 Ташкент): `pg_dump` всех баз → локально (14 дней) и в бакет `backups` RustFS на VPS 1; еженедельно — копия во внешнее хранилище (решение владельца: какое) |

## Сеть и доступ

- Приложения на VPS 1 ходят в базу по внутреннему IP VPS 2: `postgresql://…@<internal-ip-vps2>:5432/<db>?sslmode=require`
  (TLS между хостами — самоподписанный сертификат сервера, проверка `verify-ca` после пилота).
- Файрвол VPS 2 (`ufw`): `5432/tcp` только с внутреннего IP VPS 1; SSH только по ключу; публичного входа на базу нет.
- Файрвол VPS 1: `80`, `443` отовсюду; SSH только по ключу; `9000`/`9001` RustFS и `4000` LiteLLM — не публикуются (внутри compose-сети).
- DNS: `crm.railtech.uz`, `erp.railtech.uz`, `cabinet.railtech.uz` → `176.101.56.141` (A-записи, TTL 300 на время пилота).
- Деплой: GitHub Actions (после разблокировки, Q-10) собирает образы в GHCR, по SSH на VPS 1 выполняет `pull` + `up`
  с pg_dump-гейтом перед миграциями (как в B2B/CRM). Реализовано в M5-INF-01: `.github/workflows/deploy.yml` (только вручную) и `infra/deploy/deploy.sh` на сервере — `docs/runbooks/deploy.md`.

## CPU прод-VPS: только базовый x86-64 (M5-INF-02)

Оба прод-сервера (Eskiz, KVM) отдают гостю процессор **«QEMU Virtual CPU version 2.5+»**: нет SSE4.2, SSSE3, POPCNT, AVX —
это базовый x86-64 (v1). Хостер модель CPU не меняет. Проверка на сервере: `grep -m1 'model name' /proc/cpuinfo`, `grep -o -w 'sse4_2\|ssse3\|popcnt\|avx' /proc/cpuinfo | sort -u` (пусто).

| Что | Состояние на этом CPU |
|---|---|
| Официальный `ghcr.io/berriai/litellm` (Wolfi) | **не работает**: `Fatal glibc error: CPU does not support x86-64-v2`. Вместо него — свой образ `rt-litellm` на `python:3.12-slim-bookworm` (`infra/ai/litellm/Dockerfile`, та же версия `litellm[proxy]`, prisma сгенерирован при сборке) |
| numpy 2.4+ (в CRM приходит через docling-core → pandas) | **не работает**: `NumPy was built with baseline optimizations: (X86_V2)`. В CRM ограничение `numpy<2.4` (`constraint-dependencies` в `apps/crm/backend/pyproject.toml`); 2.3.5 и 2.2.6 проверены, ERP на numpy 1.26.4 |
| ClickHouse / Langfuse (профиль `observability`) | **недоступен**: ClickHouse требует SSE4.2. Трейсы Langfuse на этих VPS не включать; расходы ИИ (M3-CRM-09) читаются из БД LiteLLM и от Langfuse не зависят |
| docling / torch (профиль `kb-ingest`) | **не проверено**: при первом включении запустить `import torch, numpy` в образе `docling-serve-cpu`; колёса torch под AVX на базовом CPU могут падать |
| redis 7.4.11, rustfs 1.0.1, caddy 2.11.7, pgvector pg17, образы erp-backend, веб-образы, миграции CRM | работают |

**Правило:** новые образы и нативные колёса (numpy, scipy, torch, onnx и т. п.) — только с базой x86-64 v1. Перед добавлением образа или обновлением
пакета с нативным кодом проверить на самом проде заранее нельзя, поэтому ловим на деплое: `infra/deploy/cpu-baseline-check.sh` (вызывается из `deploy.sh`
после `pull`, до pg_dump-гейта и миграций) запускает в каждом образе прода короткую команду, исполняющую нативный код. Для нового образа
добавить правило в `case` скрипта (иначе он попадёт в список «не проверены»). Тест скрипта — `infra/deploy/tests/cpu-baseline-test.sh` (в `make deploy-check`).
При падении проверки образ заменяют или фиксируют версию пакета (`constraint-dependencies` в `pyproject.toml` для Python), а не обходят проверку.
Локально воспроизвести CPU без v2 на Mac нельзя (Rosetta/Apple Silicon); на x86-Linux — `qemu-x86_64 -cpu qemu64 <команда>` внутри контейнера.

## Диск

- VPS 1 (120 ГБ): образы и слои (~15 ГБ), RustFS (файлы клиентов и база знаний), ClickHouse Langfuse (ротация 30 дней), логи json-file с ротацией.
- VPS 2 (40 ГБ): данные PostgreSQL (ориентир < 10 ГБ на пилоте), локальные дампы 14 дней; WAL копится на диске, если архив не уходит (healthcheck `walg` краснеет при `pg_wal` > 2 ГБ или свободном месте < 4 ГБ); разовое восстановление и ежемесячная проверка занимают ≈ размер базы.

## Что нужно от владельца до M5-INF-01

См. `docs/OWNER-CHECKLIST.md` «До M5»: внутренние IP обоих VPS, SSH-доступ (публичный ключ деплоя на оба хоста,
пользователь с `docker`), DNS-записи, внешнее хранилище для недельных копий бэкапов, секреты в GitHub environment `production`.
