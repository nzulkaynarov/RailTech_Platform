# LiteLLM Proxy на Debian (M5-INF-02). Официальный ghcr.io/berriai/litellm (Wolfi, glibc собран под x86-64-v2) на прод-VPS
# не стартует: процессор виртуальной машины — только базовый x86-64 (docs/runbooks/servers.md «CPU прод-VPS»).
# Версия — та же, что была у официального образа. Колёса litellm и зависимостей — manylinux под базовый x86-64.
# Режим с БД (STORE_MODEL_IN_DB, DATABASE_URL = Postgres) требует prisma: клиент генерируется и движки скачиваются
# при сборке, на старте контейнер в сеть за бинарниками не ходит.
FROM python:3.12-slim-bookworm

ARG LITELLM_VERSION=1.105.0
ARG PRISMA_PY_VERSION=0.15.0

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PRISMA_BINARY_CACHE_DIR=/opt/prisma-cache \
    XDG_CACHE_HOME=/opt/prisma-cache

# openssl — нужен движкам prisma; nodejs — prisma CLI (migrate deploy при старте прокси).
RUN apt-get update \
    && apt-get install -y --no-install-recommends openssl ca-certificates nodejs npm \
    && rm -rf /var/lib/apt/lists/*

# numpy<2.4: колёса numpy 2.4+ собраны с базой x86-64-v2 и падают на прод-CPU при import. prisma — клиент БД
# прокси (в extras `proxy` его нет; официальный образ ставит его отдельно).
RUN printf 'numpy<2.4\n' > /tmp/constraints.txt \
    && pip install -c /tmp/constraints.txt "litellm[proxy]==${LITELLM_VERSION}" "prisma==${PRISMA_PY_VERSION}" \
    && rm /tmp/constraints.txt

WORKDIR /app
# prisma generate по схеме самого пакета litellm + загрузка движков в PRISMA_BINARY_CACHE_DIR (внутри образа).
RUN SCHEMA="$(python -c 'import litellm.proxy, os; print(os.path.join(os.path.dirname(litellm.proxy.__file__), "schema.prisma"))')" \
    && cp "$SCHEMA" /app/schema.prisma \
    && prisma generate --schema /app/schema.prisma \
    && chmod -R a+rX /opt/prisma-cache

EXPOSE 4000
ENTRYPOINT ["litellm"]
CMD ["--port", "4000"]
