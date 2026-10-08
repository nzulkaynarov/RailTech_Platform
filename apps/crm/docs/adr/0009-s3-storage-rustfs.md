# 0009. S3-хранилище: RustFS вместо MinIO

- Статус: accepted (2026-10-08, выбор владельца продукта: «по MinIO выбираем RustFS»)
- Дата: 2026-10-08
- Связано: SPEC §2 (Файлы, Бэкапы), §3.2, §11, §13, §14; BUSINESS.md §8 («бесплатные open-source решения на собственном сервере»); docs/QUESTIONS.md Q-002

## Контекст и проблема

SPEC v2.0 выбирал MinIO (`minio/minio`) для документов клиентов, исходников KB и вложений. На 2026-10-08:

- образы `minio/minio` и `minio/mc` удалены с Docker Hub (по сторонним отчётам — 2026-09-11);
- README репозитория `minio/minio` начинается с «THIS REPOSITORY IS NO LONGER MAINTAINED» и отсылает к коммерческому AIStor;
- последний community-образ `RELEASE.2025-09-07T16-13-09Z` в `quay.io/minio/minio` тоже недоступен — GitHub Actions получил `unauthorized` при pull;
- сборка MinIO от Chainguard (`cgr.dev/chainguard/minio`) доступна бесплатно только под тегом `latest` и зависит от развития заброшенного апстрима.

Нужно поддерживаемое S3-совместимое хранилище с открытой лицензией.

## Драйверы решения

- S3-совместимость: код работает только по протоколу S3 (presigned URL с TTL — Фаза 6).
- Активная разработка и исправления безопасности.
- Лицензия для бесплатного self-hosted использования.
- Совместимость с Langfuse (path-style, SigV4).
- Лёгкость эксплуатации на одном VPS (single-drive).

## Рассмотренные варианты

1. RustFS (`rustfs/rustfs`, Apache-2.0).
2. SeaweedFS (`chrislusf/seaweedfs`, Apache-2.0).
3. Garage (`dxflrs/garage`, AGPL-3.0).
4. MinIO в сборке Chainguard (`cgr.dev/chainguard/minio:latest`) — временное решение первой версии этого PR.

## Решение

**RustFS 1.0.1** (`rustfs/rustfs:1.0.1`, тег зафиксирован; обновляет Dependabot).

Конфигурация (проверено по исходникам тега 1.0.1 и запуском бинарника 1.0.1):

- учётка — `RUSTFS_ACCESS_KEY` / `RUSTFS_SECRET_KEY` (в `.env` — `S3_ACCESS_KEY` / `S3_SECRET_KEY`); анонимный доступ — 403;
- один том `/data` (single-drive): проверка независимости дисков для одного пути не выполняется;
- health — `GET :9000/health` (без учётных данных); в образе есть `curl` и `sh`;
- консоль — `:9001`, включена только на dev (`RUSTFS_CONSOLE_ENABLE`);
- бакеты создаёт одноразовый сервис `s3-init` тем же образом: `curl --aws-sigv4 … -X PUT /<bucket>` (повторный PUT → 200, идемпотентно); подпись с регионами `us-east-1` и `auto` (так подписывает Langfuse) принимается;
- приложение: `S3_ENDPOINT`, `app/integrations/s3.py`, проверка `s3` в `GET /ready`.

### Последствия

- Хорошо: поддерживаемый проект под Apache-2.0; воспроизводимый тег; замена прозрачна для кода (только S3 и `/health`).
- Плохо: RustFS моложе MinIO и SeaweedFS — выше риск регрессий, поэтому integration-тесты хранилища в CI обязательны на каждом PR, а обновления RustFS — отдельными PR Dependabot с прогоном CI.
- Бэкапы: `mc mirror` из SPEC v2.0 недоступен — инструмент зеркалирования S3-бакетов (rclone, aws-cli или средства RustFS) выбирается в Фазе 8 (отметка в SPEC §2).
- Обновлены: SPEC §2, §3.1, §3.2, §4, §7.1, §9.2, §11, §13, §14, §16 (v2.1); PLAN; CLAUDE.md §3, §6; compose, CI, `.env.example`, README, runbook.

### Как проверяем

CI integration-job поднимает `rustfs/rustfs:1.0.1` и прогоняет `tests/integration/test_dependencies.py::test_s3_ping`; с Фазы 1 — тесты put/get/presigned. Пересмотр — при проблемах совместимости S3 API или прекращении поддержки RustFS.

## Плюсы и минусы вариантов

### RustFS

- Плюс: позиционируется как замена MinIO (те же порты, консоль, совместимость S3), Apache-2.0, активные релизы.
- Минус: молодой проект.

### SeaweedFS

- Плюс: зрелый, Apache-2.0.
- Минус: S3 — шлюз над собственной архитектурой (master/volume/filer), сложнее в эксплуатации на одном узле.

### Garage

- Плюс: лёгкий.
- Минус: AGPL-3.0; ограниченная поддержка части S3 API.

### MinIO (Chainguard)

- Плюс: без изменений кода и SPEC.
- Минус: апстрим не поддерживается; бесплатно только `latest` — невоспроизводимо.
