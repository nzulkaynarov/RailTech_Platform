---
name: task-start
description: Подготовить worktree задачи RailTech Platform — .claude/worktrees/<задача> от свежего origin/main, ветка, зависимости затронутых приложений, ERP_TEST_NS, проверка git-хуков и Docker. Лид — перед запуском исполнителя; исполнитель без лида — в начале своей задачи.
---

# Worktree задачи

Правила — ORCHESTRATOR §4.1 («Worktree — только `.claude/worktrees/<задача>`», «Зависимости ставит тот, кто готовит
worktree», «Git — только в своём worktree») и `CLAUDE.md` корня.

## Шаги

1. Имя задачи — ID в нижнем регистре (`d2-8`, `fix-15`). Оно же — `ERP_TEST_NS` для тестов ERP и проект compose `rt-<задача>`.
2. Ветка — как велит runbook волны; если не велит — как в истории (`git log origin/main --merges --format=%s -30`):
   `w<волна>/<id>-<slug>`, `fix/<система>-<slug>`, `docs/<slug>`, `ops/<slug>`.
3. Из корня основного checkout:
   ```bash
   git fetch origin main
   git worktree add .claude/worktrees/<задача> -b <ветка> origin/main
   ```
   Только от `origin/main` — не от неслитых веток соседей (их нужное — заглушкой).
4. Зависимости — только затронутых систем, из корня worktree:

   | Система | Команда |
   |---|---|
   | CRM | `make -C apps/crm install` |
   | ERP | `make -C apps/erp install` (линтеры и фронтенд; pytest — в Docker) |
   | Cabinet | `make -C apps/cabinet install` |
   | Платформа | `make -C apps/platform install` (+ `cd apps/platform/web && pnpm exec playwright install chromium` для e2e) |
   | EDS | `make -C apps/eds install` |
   | rt-bus, rt-docs | `make -C packages/rt-bus install`, `make -C packages/rt-docs install` |
   | Контракты | `make -C packages/contracts install` |

5. Проверка места:
   - git-хуки: `ls "$(git -C .claude/worktrees/<задача> rev-parse --path-format=absolute --git-path hooks)"` — есть
     `pre-commit` и `commit-msg`; нет — `make hooks` в корне (один раз на клон, действует во всех worktree);
   - Docker для ERP, EDS, rt-bus, rt-docs, `ci_local.sh`: `docker info`;
   - рядом не больше двух наборов тестов ERP и одного стенда волны (HANDOFF §5): `docker ps --format '{{.Names}}' | grep -E '^rt-'`.
6. Исполнителю в промпт — абсолютный путь worktree, ветка, `ERP_TEST_NS=<задача>`.

## После слияния

`git worktree remove .claude/worktrees/<задача>` (ветку на GitHub удаляет автослияние); свои контейнеры —
`docker compose -p rt-<задача> down -v`, тома тестов — по префиксу задачи. Общие очистки Docker запрещены.
