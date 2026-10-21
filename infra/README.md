# infra — общая инфраструктура ансамбля

| Папка | Содержимое | Задача |
|---|---|---|
| `compose/` | `base.yml` (все сервисы) + `dev.yml` (hot reload, порты на 127.0.0.1); `make-env.sh` для `.env`; `prod.yml` — M5-INF-01 | M0-INF-03 ✓ |
| `caddy/` | `Caddyfile.dev`: `crm.`, `erp.`, `cabinet.`, `platform.localhost` (+ `langfuse.`, `s3.`); ERP/Cabinet — заглушки до своих вех; `Caddyfile.prod` — M5-INF-01 | M0-INF-03 ✓ |
| `ai/` | `litellm.config.yaml` (шлюз, бюджеты, fallbacks), `litellm.models.yaml` (алиасы CRM и ERP по умолчанию; засевает `litellm-seed`) | M0-INF-03 ✓, ADR-0005 |
| `db/` | `init-databases.sh`: базы `crm`, `erp`, `litellm`, `langfuse` на одной инстанции (ADR-0002), pgvector в `crm`; бэкапы — M5-INF-01 | M0-INF-03 ✓ |
| `ci/` | один workflow с матрицей по путям; `legacy/b2b` исключён | M0-INF-04 |

Запуск и устройство стенда — `docs/runbooks/stand.md`. Секретов здесь нет: только `.env.example` в корне (ORCHESTRATOR §3.6).
