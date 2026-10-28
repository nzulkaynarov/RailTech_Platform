#!/usr/bin/env bash
# Правила проверки базы CPU (M5-INF-02, S0-7): ЕДИНАЯ таблица «образ -> команда, исполняющая нативный код образа».
# Подключается (source) двумя проверками — не запускать:
#   infra/deploy/cpu-baseline-check.sh  на VPS 1 при деплое: настоящий `docker run` на прод-CPU (после pull, до миграций);
#   scripts/qemu_cpu_check.sh           в CI и локально: тот же набор команд под эмуляцией CPU qemu64 (qemu-x86_64 в user-mode).
# Новый образ прода — новая строка в `case` ниже (иначе deploy-проверка напечатает его в списке «не проверены», а CI его не знает).
# shellcheck shell=bash

# Нативные колёса, если они есть в образе: отсутствие модуля — не ошибка, падение при import — ошибка.
CPU_PY_NATIVE='import importlib.util as u; [__import__(m) for m in ("numpy","pandas","scipy") if u.find_spec(m)]'

# cpu_baseline_names — имена образов, для которых есть правило (одно на строку).
cpu_baseline_names() {
  printf '%s\n' rt-crm-backend rt-erp-backend rt-platform-bff rt-eds rt-litellm rt-crm-frontend rt-erp-frontend rt-cabinet rt-platform-web \
    rt-db-postgres rt-db-backup caddy redis rustfs rc rclone
}

# cpu_baseline_rules <имя образа без реестра и тега> <обработчик>
# Для каждой команды проверки вызывает «<обработчик> <программа> <аргументы...>»; программа — имя или абсолютный путь внутри образа.
# Возвращает 1, если для образа правила нет. Обработчик, вернув не 0, не прерывает остальные команды: он сам копит отказы.
cpu_baseline_rules() {
  local name="$1" run="$2"
  case "$name" in
    rt-crm-backend | rt-platform-bff | rt-erp-backend) "$run" python -c "$CPU_PY_NATIVE" ;;
    # EDS: нет numpy, зато нативные колёса стека (Rust pydantic-core/rpds, libpq psycopg-binary, uvloop, httptools, watchfiles) — import исполняет их код.
    rt-eds)
      "$run" python -c "$CPU_PY_NATIVE"
      "$run" python -c "import pydantic_core, psycopg, psycopg_binary, uvloop, httptools, watchfiles, rpds, yaml, jwt, sqlalchemy"
      ;;
    rt-litellm) "$run" python -c "import numpy; import litellm.proxy.proxy_server" ;;
    # Статика: Caddy (Go, GOAMD64 определяется при старте) и nginx; -t разбирает конфигурацию образа (pcre, openssl).
    rt-crm-frontend | rt-platform-web | caddy) "$run" caddy version ;;
    rt-erp-frontend | rt-cabinet) "$run" nginx -t ;;
    redis) "$run" redis-server --version ;;
    rustfs) "$run" rustfs --version ;;
    # Клиент RustFS в одноразовом s3-init (S0-9): пользователи, политики, правило erp-temp.
    rc) "$run" rc --version ;;
    # Внешняя копия архива на Google Drive (offsite-backup, OPS-GDRIVE): официальный образ rclone (Go).
    rclone) "$run" rclone version ;;
    # VPS 2 (infra/db): WAL-G (Go + libsodium), сервер PostgreSQL с pgvector; бэкап — pg_dump 17, rclone, openssl.
    # Бинарники PostgreSQL в образе pgvector лежат вне PATH — абсолютные пути.
    rt-db-postgres)
      "$run" wal-g --version
      "$run" /usr/lib/postgresql/17/bin/postgres --version
      ;;
    rt-db-backup)
      "$run" /usr/lib/postgresql/17/bin/pg_dump --version
      "$run" rclone version
      "$run" openssl version
      ;;
    *) return 1 ;;
  esac
}
