"""База данных: бюджет соединений пула и DATABASE_URL-парсинг."""

import os
from urllib.parse import parse_qsl, urlparse

from .web import *  # noqa: F401,F403 — последовательная композиция настроек

# Database
# https://docs.djangoproject.com/en/4.2/ref/settings/#databases
#
# CONNECTION BUDGET (dj-db-conn-pool = a SQLAlchemy pool PER PROCESS).
# Every process that touches the ORM opens its own pool of up to
# DB_POOL_SIZE + DB_MAX_OVERFLOW connections. In prod that is:
#   gunicorn --workers=2         → 2
#   celery-worker --concurrency=2 → up to 3 (parent + 2 children)
#   celery-worker-ai --concurrency=2 → up to 3
#   celery-beat                  → 1
#   ≈ 9 pool-owning processes.
# Peak = 9 × (POOL_SIZE + MAX_OVERFLOW). The OLD 10+20=30 gave a ~270-connection
# ceiling → it exhausted the DB-VPS (PG default max_connections=100, minus the
# superuser-reserved slots) and BLOCKED deploys at the INF-04 pg_dump gate
# ("remaining connection slots are reserved for roles with SUPERUSER").
# New default 3+5=8 → ~72 ceiling, ~27 idle baseline — fits 100 with headroom for
# the backup gate / migrations / psql. Tune via env (no redeploy) against the
# ACTUAL server max_connections (verify: SHOW max_connections; on the DB-VPS).
#
# CONN_MAX_AGE=0 is REQUIRED with an external pool: Django then returns the
# connection to the pool at the end of each request instead of pinning it for
# CONN_MAX_AGE seconds (the old 600 held pooled connections open, defeating reuse
# and multiplying the live count under the async uvicorn workers).

DB_CONN_MAX_AGE = int(os.environ.get("DB_CONN_MAX_AGE", "0"))
_DB_POOL_OPTIONS = {
    "POOL_SIZE": int(os.environ.get("DB_POOL_SIZE", "3")),
    "MAX_OVERFLOW": int(os.environ.get("DB_MAX_OVERFLOW", "5")),
    "RECYCLE": int(os.environ.get("DB_POOL_RECYCLE", "1800")),
    "PRE_PING": True,
}

if os.environ.get("DATABASE_URL"):
    tmpPostgres = urlparse(os.environ.get("DATABASE_URL"))
    DATABASES = {
        "default": {
            "ENGINE": "dj_db_conn_pool.backends.postgresql",
            "NAME": tmpPostgres.path.replace("/", ""),
            "USER": tmpPostgres.username,
            "PASSWORD": tmpPostgres.password,
            "HOST": tmpPostgres.hostname,
            "PORT": tmpPostgres.port or 5432,
            "CONN_MAX_AGE": DB_CONN_MAX_AGE,
            "CONN_HEALTH_CHECKS": True,
            "POOL_OPTIONS": dict(_DB_POOL_OPTIONS),
            "OPTIONS": dict(parse_qsl(tmpPostgres.query)),
        }
    }
    # Enforce TLS to the managed DB unless the URL already pins an sslmode.
    DATABASES["default"]["OPTIONS"].setdefault("sslmode", os.environ.get("DB_SSLMODE", "require"))
else:
    DATABASES = {
        "default": {
            "ENGINE": "dj_db_conn_pool.backends.postgresql",
            "NAME": os.environ.get("POSTGRES_DB", "railtech"),
            "USER": os.environ.get("POSTGRES_USER", "postgres"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "postgres"),
            "HOST": os.environ.get("POSTGRES_HOST", "db"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": DB_CONN_MAX_AGE,
            "CONN_HEALTH_CHECKS": True,
            "POOL_OPTIONS": dict(_DB_POOL_OPTIONS),
            # 'prefer' keeps local docker-postgres (no TLS) working; set DB_SSLMODE=require in prod.
            "OPTIONS": {"sslmode": os.environ.get("DB_SSLMODE", "prefer")},
        }
    }
