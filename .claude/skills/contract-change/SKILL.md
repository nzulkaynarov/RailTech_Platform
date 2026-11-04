---
name: contract-change
description: Изменить контракт в packages/contracts (OpenAPI, события, RBAC Платформы, MCP, документы) — контракт раньше кода, правила версий, make contracts с oasdiff и проверкой событий, перегенерация клиентов и правка обеих сторон в одном PR. Только когда задача прямо меняет контракт.
---

# Изменение контракта

Правила — ORCHESTRATOR §3 п. 3 и 15, §4.1 «Параллельные PR» (версия контракта); `docs/architecture/CONTRACTS.md` §7
(версии и проверки машиной), §9.6 (события). Задача контракт не меняет, а расхождение есть — строка в `docs/QUESTIONS.md`
и в описании PR, не правка.

## Шаги

1. **Сначала контракт**: файл в `packages/contracts/` — `openapi/*.yaml`, `events/**` (скилл `bus-event`),
   `platform-rbac.yaml`, `mcp-tools.json`, `documents/**`. Описание для людей — соответствующий раздел `CONTRACTS.md`.
2. **Версия** (`info.version`):
   - добавляющее изменение — версию не поднимать, строку журнала в `info.description` не писать; что изменилось — в
     описании PR;
   - ломающее до 1.0 (oasdiff ERR; новое значение enum в ответе — тоже ERR, #386) — ровно на минор выше минора `main`. `main`
     уходит вперёд, пока идёт работа: после каждого `git merge origin/main` сверь `grep -m1 '^  version:'
     packages/contracts/openapi/<файл>.yaml` с `git show origin/main:packages/contracts/openapi/<файл>.yaml | grep -m1
     '^  version:'`; минор не выше минора `main` — поднимай до ровно на один выше `main`, иначе oasdiff красный (#377, #382, #389);
   - событие — в пределах `vN` только новые необязательные поля; ломающее (в том числе новое значение enum) — новым файлом
     `v(N+1)` с двойной публикацией.
3. `make contracts` из корня worktree: линт, генерация в `generated/`, `oasdiff` и сравнение событий с точкой ответвления от
   `origin/main`. Красное не обходится флагом — изменение делается совместимым или версия поднимается (CONTRACTS §7.1).
   Локальная база — точка ответвления, а CI на PR сравнивает с **вершиной** `origin/main`: перед PR с ломающим изменением —
   `git merge origin/main` и `CONTRACTS_BASE_REF=origin/main scripts/ci_local.sh contracts`.
4. **Перегенерация потребителей** — в этом же PR, у **каждого** потребителя файла, не только у системы автора (#389: `crm.yaml`
   менял CRM, типы Cabinet остались старыми). Правка `description` тоже меняет сгенерированное (#381, #382). Карта —
   `docs/systems/infra/ci.md` «Правка → какие задания»:

   | Файл | Команды |
   |---|---|
   | `openapi/crm.yaml` (выгружается из кода CRM) | `make -C apps/crm openapi`; Платформа — `make -C apps/platform crm-models`; Cabinet — `make -C apps/cabinet gen-api-types` |
   | `openapi/platform-bff.yaml` | `make -C apps/platform gen-api` |
   | `openapi/eds.yaml`, `erp-integration.yaml` | `make contracts` (пишет `packages/contracts/generated/*.d.ts`, коммитится) |
   | `openapi/erp-portal.yaml` | `make -C apps/cabinet gen-api-types` |
   | `openapi/erp-internal.yaml` (выгрузка ERP) | `make -C apps/erp openapi` |
   | `platform-rbac.yaml` | `make -C apps/platform rbac`, `make -C apps/crm platform-roles` |
   | `events/**`, `bus/**` | генерация `rt-contracts` входит в `make contracts` |

   Проверка: после коммита повторная генерация не даёт диффа (`git status --porcelain` пуст); затем
   `scripts/ci_local.sh contracts <потребители>` (скилл `pre-pr` п. 2) — `check-cabinet` и `check-platform` сверяют свежесть типов.
5. **Обе стороны** — код издателя и потребителя в этом же PR (одна задача `fix/all-…`, назначенная лидом; §4 «Одна сессия —
   одна система»); новое поле — и в моках MSW и фикстурах тестов (#382, #389).
6. Перед PR — скилл `pre-pr`: задания `contracts` и всех потребителей; `generated/` без диффа после генерации.
