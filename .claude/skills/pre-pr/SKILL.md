---
name: pre-pr
description: Подготовить и открыть PR задачи RailTech Platform — «готово, когда» с доказательствами, задания ci_local по изменённым путям и потребителям контракта, типовые причины красного CI, помощь и «Для пользователей», снимки UI, коммиты с трейлерами, PR по шаблону, затем стоп. Перед каждым PR исполнителя или лида.
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
   | `apps/platform/**` | `platform`; e2e — только затронутые спеки: `cd apps/platform/web && pnpm exec playwright test e2e/<спек>.spec.ts`; маршруты или реестр настроек (`modules/*/module.ts`, `settingsRegistry.ts`) — ещё `crm` (`test_platform_links` читает их) |
   | `apps/eds/**` | `eds` |
   | `packages/contracts/**` | `contracts` + **потребители файла** (абзац ниже) |
   | `packages/rt-bus/**` | `rt-bus`, `contracts`, `crm`, `erp`, `eds`, `platform` |
   | `packages/rt-docs/**` | `rt-docs`, `contracts` |
   | `packages/ui-tokens/**` | `tokens`, `contracts`, `crm`, `erp`, `cabinet`, `platform` |
   | `docs/kb/**` | `crm`, `platform` |
   | `infra/**`, `scripts/**`, `Makefile` | `infra` |

   Потребители контракта — по файлу, не по месту диффа: таблица фильтров `docs/systems/infra/ci.md` «Правка → какие задания»
   (пример: `openapi/crm.yaml` → `crm cabinet platform`, а не только `crm`).

   Запуск — `scripts/ci_local.sh <задания>`: зелёное на этом дереве пропускается; `--quick` заменяет список целиком, с именами его
   не смешивать. Пока действует временное правило 2026-10-28, `crm-integration` и e2e можно отдать CI. Новые файлы — сначала
   `git add`: `scripts/check-doc-links.sh` видит только отслеживаемые, и битая ссылка в неотслеживаемом файле краснеет только в CI.
3. **Типовые причины красного CI** (PR #372–#389), проверь до push:
   - менялся OpenAPI или описание поля в нём → клиенты **всех** потребителей перегенерированы (`contract-change` п. 4), после
     генерации `git status --porcelain` чист; `cabinet` падал, потому что тронут был только `crm.yaml` (#389);
   - новое поле или значение в контракте → моки MSW и фикстуры тестов обновлены; vitest типов не проверяет, `tsc -b`
     (`make -C apps/platform typecheck`) — да (#382, #389);
   - новое действие аудита или ключ настроек CRM → подпись в замороженном фронтенде CRM (`apps/crm/frontend/src/i18n/labels.ru.ts`,
     `i18n/ru/settings.ts`; сторожа `domain/auditLabels.test.ts`, `i18n/settingsLabels.test.ts`) и в Платформе
     (`entities/audit/labels.ts`, `shared/i18n/{ru,uz,en}/audit.json`) (#378, #385, #388);
   - линт и формат: `make -C apps/<приложение> lint`; в EDS строка ≤ 120 знаков (#376, #388);
   - после **каждого** `git merge origin/main`: одна голова миграций (`db-migration`), версия контракта (`contract-change` п. 2),
     `generated/` без диффа, повтор затронутых тестов (#382, #389);
   - сменил текст или структуру экрана → `grep -rn "<старый текст>" apps/platform/web/e2e apps/platform/web/src`, поправь спеки
     соседей (#386); сменил моки MSW — прогони e2e всех спеков с этой сущностью (#389);
   - тестовые данные вымышленные: домены только `*.example` (B-MAIL-1);
4. **UI** менялся → скилл `ui-evidence` (1440 и 390 px, axe → `docs/screens/<задача>/`). **Экран или поведение для
   сотрудника** → скилл `help-article` и строка «Для пользователей (кому): …».
5. **Контракт** → скилл `contract-change` пройден, обе стороны в этом PR. **Миграция** → `db-migration`. **Событие** → `bus-event`.
6. **Тесты конкурентности** → раздел «Мутационная проверка» (краснеет без защиты, зеленеет с ней).
7. **Коммиты**: Conventional Commits на русском с `(ID)` в конце, трейлеры `Co-Authored-By` и `Claude-Session` (если среда
   выдала); хук `commit-msg` проверит, `--no-verify` запрещён. После push история не переписывается (`amend`, `rebase`, `reset`,
   force-push — хук блокирует и в auto-режиме): лишний файл в ветке — `git rm` обычным коммитом.
8. **PR**: `git push -u origin <ветка>`, затем
   `gh pr create --title "<ID>: …" --body-file <файл>` — разделы шаблона: Задача · Что (+ «Для пользователей») · Почему
   (для продуктовой задачи — benchmark, §3 п. 12) · Как проверить глазами · Проверки · Документация · Открытые вопросы.
   Контракт — отдельной строкой: файл, версия, добавляющее или ломающее. Статус и хвосты — в описании; `docs/PROGRESS.md` не
   правишь. В облаке без `gh` — GitHub MCP.
9. **Стоп**: одна ссылка на PR и один отчёт лиду (формат — агент `executor`). PR не сливаешь.
