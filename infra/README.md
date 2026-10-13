# infra — общая инфраструктура ансамбля

| Папка | Назначение | Задача |
|---|---|---|
| `compose/` | `base.yml` / `dev.yml` / `prod.yml` для всего ансамбля: PostgreSQL 17 (базы `crm` с pgvector и `erp`), Redis, LiteLLM, Langfuse, RustFS (бакеты `crm`, `erp`), Caddy | M0-INF-03, M5-INF-01 |
| `caddy/` | три домена: `crm.`, `erp.`, `cabinet.` (`*.localhost` на dev) | M0-INF-03 |
| `ai/` | LiteLLM (модели по алиасам, бюджеты, теги `system=crm|erp`), Langfuse | M0-INF-03, ADR-0005 |
| `db/` | инициализация двух баз, бэкапы pg_dump → S3 | M0-INF-03, M5-INF-01 |
| `ci/` | один workflow с матрицей по путям; `legacy/b2b` исключён | M0-INF-04 |

Секретов здесь нет: только `.env.example` с комментариями (ORCHESTRATOR §3.6).
