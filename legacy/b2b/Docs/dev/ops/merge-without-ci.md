# Мерж без CI — протокол при мёртвых GitHub-hosted раннерах

_Действует с 2026-08-17 (решение владельца: биллинг GitHub Actions не оплачивать). Первый мерж по протоколу — PR #566, первый деплой после него — run 32021973295 (успех). Отменяется, когда CI снова стартует: тогда протокол — просто локальная страховка перед пушем._

## Что именно сломано и что нет

| | Состояние | Почему |
|---|---|---|
| `ci.yml` (11 джоб, `ubuntu-latest`) | **не стартует**: джобы «fail» за 2 с, ноль шагов, аннотация чек-рана «recent account payments have failed or your spending limit needs to be increased» | GitHub-hosted минуты — платные |
| Nightly Playwright e2e (`ubuntu-latest`) | не стартует | то же |
| `deploy-b2b.yml` (`self-hosted, railtech-b2b`) | **работает** — стартует через ~20 с после пуша в `main`, полный цикл ~55 мин без кэша (бэкенд-образ на слабом CPU ~40 мин) | self-hosted раннер минут не тарифицирует; подтверждено прогоном 17-08, а не рассуждением |
| `apply-caddy.yml` (self-hosted, ручной) | работает | то же |
| Защита ветки `main` | **нет** (free plan, приватный репо) | мерж технически возможен всегда — вся дисциплина держится на этом протоколе |

Диагностика «CI мёртв или PR красный?»: `gh run view <id> --json jobs -q '.jobs[].steps|length'` → `0` у всех джоб = биллинг; ненулевые шаги = настоящий красный гейт. Аннотация: `gh api repos/<owner>/<repo>/check-runs/<job_id>/annotations -q '.[].message'`.

## Протокол (одна волна = один PR)

1. **Все гейты локально одной командой:** `make ci-local` (`scripts/ci_local.sh`). Это зеркало 11 джоб `ci.yml` теми же командами и версиями (+ `i18n-check` — локальный бонус). Шаги не прерывают друг друга — прогон идёт до конца и показывает всё, что чинить; итоговый код 1, если красен хоть один. Отчёт-таблица — `.ci-local/report.md`, логи — `.ci-local/logs/<джоба>.log`.
   - Дорогие сетевые шаги можно временно отложить: `SKIP=deps-lock,docker-build make ci-local`, потом догнать: `ONLY=deps-lock make ci-local`. **К мержу все 11 должны быть зелёными в одном коммите** — не «вчера зелёный, сегодня докоммитил».
   - Полный прогон ≈ 30–40 мин (pytest ~7 мин, docker-build ~5, deps-lock ~10 при живой сети).
2. **Таблица из `.ci-local/report.md` — в тело PR** (`gh pr edit N --body-file …` или вручную). Она заменяет чек-раны как свидетельство; без неё мерж по протоколу не считается.
3. **Мерж:** `gh pr merge N --squash --delete-branch` (стиль `main` — squash). Стековые PR — сверху вниз с ретаргетом (PRODUCT RULE 6).
4. **Деплой:** `gh run list --workflow deploy-b2b.yml --limit 1` — стартовал? Ждать `success`. Если run НЕ появился за минуту — см. «Если деплой не стартовал».
5. **Проверка прода снаружи** (без логина): `curl -s https://b2b.railtech.uz/ | grep -o 'assets/index-[^"]*\.js'` → скачать бандл и `grep` строку, добавленную в этом PR (ru.json-текст); `curl https://b2b.railtech.uz/health/` → `database: up`; по SSH — версии зависимостей в контейнере, если менялись локи (`docker exec railtech_backend_prod python -c "import cryptography;print(cryptography.__version__)"`).
6. **Глазами** — если PR трогал UI: сценарий по спеке/волне на проде (PRODUCT RULE 4). Nightly e2e лежит — его заменяет `make e2e-prod` (prod-safe набор с машины разработчика).

## Ловушки, из-за которых протокол чуть не сломался 17-08

- **deps-lock даёт ложный «OK», если pip-compile упал.** Файлы не переписаны → `git diff` пуст → «дрейфа нет». Скрипт проверяет три вещи: код выхода контейнера (`set -e`), mtime обоих локов новее старта шага, `git diff`. Руками — то же: `stat -f %m backend/requirements.txt` после компиляции.
- **Docker Desktop (macOS): egress из Linux-VM протухает** через минуты после старта — `docker pull`/PyPI отвечают `context deadline exceeded`, `docker info` виснет, `osascript quit` не помогает. Лечение: `pkill -9 -f com.docker; open -a Docker` (поднимается за ~10 с). Сетевые шаги (`docker-build`, `deps-lock`, `security`) гонять сразу после рестарта; длинные — бить на части (`ONLY=…`).
- **Тесты идут в контейнере из СВЕЖЕГО образа** — иначе при смене локов проверяется вчерашний набор зависимостей. Поэтому `docker-build` в скрипте стоит ДО `backend-test` и пересоздаёт контейнеры.
- **`pip install` через `docker compose exec` загрязняет живой контейнер** — одноразовые инструменты только `docker compose run --rm --no-deps` (так устроен `make security-backend`).
- **Гейт проверяется ломаным входом.** Каждый новый шаг скрипта проверен подложенным нарушением (лишний ключ в `en.json`, кривой `.py`, лишнее поле сериализатора → красный; убрано → зелёный). Не верить гейту, который никогда не был красным.

## Если деплой не стартовал

Раннер: `ssh root@176.101.56.141 systemctl is-active actions.runner.nzulkaynarov-RailTech_SaaS_B2B.vps-b2b.service` и `gh api repos/nzulkaynarov/RailTech_SaaS_B2B/actions/runners -q '.runners[]|"\(.name) \(.status)"'`. Если раннер online, а run не появился — открыть workflow вручную (`gh workflow run deploy-b2b.yml`). Ручной деплой на VPS повторяет шаги `deploy-b2b.yml` (rsync → .env из секретов → сборка SPA → сборка backend → pg_dump-гейт → migrate → `up -d --build` → health) — но `.env` рендерится из GitHub-секретов, которых на диске нет: без раннера ручной деплой требует секретов у владельца.

## Что вернуть, когда CI оживёт

Ничего ломать не нужно: `ci.yml` не менялся. `make ci-local` остаётся страховкой перед пушем ([[feedback-ci-minutes-are-scarce]] — каждая починка после пуша = ещё один полный прогон). Пометить в CLAUDE.md, что чек-раны снова источник правды.
