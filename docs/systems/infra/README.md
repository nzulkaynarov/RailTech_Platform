# Инфраструктура ансамбля — `infra/`
Статус: действует · Владелец: лид · Обновлено: 2026-10-23

| Папка | Содержимое | Задача |
|---|---|---|
| `compose/` | `base.yml` (все сервисы) + `dev.yml` (hot reload, порты на 127.0.0.1); `make-env.sh` для `.env`; `prod.yml` — M5-INF-01 (образы GHCR и лимиты памяти, в том числе Платформа — INF-P0-5) | M0-INF-03 ✓ |
| `caddy/` | `Caddyfile.dev`: `crm.`, `erp.`, `cabinet.`, `platform.localhost` (+ `langfuse.`, `s3.`); ERP/Cabinet — заглушки до своих вех; `Caddyfile.prod` — M5-INF-01 (четыре домена, Платформа — INF-P0-5) | M0-INF-03 ✓ |
| `ai/` | `litellm.config.yaml` (шлюз, бюджеты, fallbacks), `litellm.models.yaml` (алиасы CRM и ERP по умолчанию; засевает `litellm-seed`) | M0-INF-03 ✓, ADR-0005 |
| `db/` | `init-databases.sh`: базы `crm`, `erp`, `litellm`, `langfuse` на одной инстанции (ADR-0002), pgvector в `crm`; бэкапы — M5-INF-01 | M0-INF-03 ✓ |
| `deploy/` | скрипты деплоя и отката прода (`deploy.sh <тег>`) | M5-INF-01 |
| CI | `.github/workflows/ci.yml` — пояснения в [`ci.md`](ci.md) | M0-INF-04 |

Запуск и устройство стенда — `docs/runbooks/stand.md`. Секретов здесь нет: только `.env.example` в корне (ORCHESTRATOR §3.6).

Прод на двух VPS — [`docs/runbooks/servers.md`](../../runbooks/servers.md), деплой и откат — [`docs/runbooks/deploy.md`](../../runbooks/deploy.md).
Целевая инфраструктура (WAL-архив, раздельный Redis, третий сервер, наблюдаемость) — стратегия 2026-10-23 §3.5–§3.7, ADR-0017.
