---
name: pre-pr
description: Подготовить и открыть PR задачи RailTech Platform — «готово, когда» с доказательствами, задания ci_local по изменённым путям, помощь и строка «Для пользователей», снимки UI, коммиты с трейлерами, PR по шаблону, затем стоп. Перед каждым PR исполнителя или лида.
---

# PR задачи

Правила — `CLAUDE.md` корня («Рабочий цикл»), ORCHESTRATOR §4 и §7, шаблон `.github/PULL_REQUEST_TEMPLATE.md`.

## Шаги

1. **«Готово, когда»** — по пунктам: чем доказано (тест, снимок, вывод команды). Ничего сверх задачи.
2. **Затронутые задания.** `git fetch origin main && git diff --name-only origin/main...HEAD` → задания `ci_local.sh`:

   | Изменено | Задания |
   |---|---|
   | любое | `gitleaks` (секреты, ссылки документации, `scripts/tests`) |
   | `apps/crm/**` | `crm` (интеграционные — `crm-integration`, если трогал БД или внешние вызовы) |
   | `apps/erp/**` | `erp` |
   | `apps/cabinet/**` | `cabinet` |
   | `apps/platform/**` | `platform`; e2e — только затронутые спеки: `cd apps/platform/web && pnpm exec playwright test e2e/<спек>.spec.ts` |
   | `apps/eds/**` | `eds` |
   | `packages/contracts/**` | `contracts` + потребители файла — `docs/systems/infra/ci.md` «Правка → какие задания» |
   | `packages/rt-bus/**` | `rt-bus`, `contracts`, `crm`, `erp`, `eds`, `platform` |
   | `packages/rt-docs/**` | `rt-docs`, `contracts` |
   | `packages/ui-tokens/**` | `tokens`, `contracts`, `crm`, `erp`, `cabinet`, `platform` |
   | `docs/kb/**` | `crm`, `platform` |
   | `infra/**`, `scripts/**`, `Makefile` | `infra` |

   Запуск — `scripts/ci_local.sh <задания>`: идут только названные, зелёное на этом дереве пропускается. Флаг `--quick`
   заменяет список целиком (все быстрые задания), с именами его не смешивать. Пока действует временное правило 2026-10-28,
   `crm-integration` и e2e можно отдать CI; после перевода репозитория в приват — локально всё затронутое.
3. **UI** менялся → скилл `ui-evidence` (1440 и 390 px, axe → `docs/screens/<задача>/`). **Экран или поведение для
   сотрудника** → скилл `help-article` и строка «Для пользователей (кому): …».
4. **Контракт** → скилл `contract-change` пройден, обе стороны в этом PR. **Миграция** → `db-migration`. **Событие** → `bus-event`.
5. **Тесты конкурентности** → раздел «Мутационная проверка» (краснеет без защиты, зеленеет с ней).
6. **Коммиты**: Conventional Commits на русском с `(ID)` в конце, трейлеры `Co-Authored-By` и `Claude-Session` (если среда
   выдала). Хук `commit-msg` проверит формат; `--no-verify` запрещён.
7. **PR**: `git push -u origin <ветка>`, затем
   `gh pr create --title "<ID>: …" --body-file <файл>` — разделы шаблона: Задача · Что (+ «Для пользователей») · Почему
   (для продуктовой задачи — benchmark, §3 п. 12) · Как проверить глазами · Проверки · Документация · Открытые вопросы.
   Статус и хвосты — в описании; `docs/PROGRESS.md` не правишь. В облаке без `gh` — GitHub MCP.
8. **Стоп**: ссылка на PR лиду. PR не сливаешь.
