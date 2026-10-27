# docs/ — вся документация RailTech Platform, одна правда
Статус: действует · Владелец: архитектор · Обновлено: 2026-10-27

**Правило (владелец 2026-10-23, `docs/ORCHESTRATOR.md` §3 п. 17).** Вся правда о продукте, архитектуре, процессе и
правилах кода живёт здесь, в `docs/`, и нигде больше. В `apps/*`, `packages/*`, `infra/` и корне — только указатели:
`CLAUDE.md` (что за каталог, где правила, главные команды) и `README.md` (одна фраза и ссылки сюда). У каждой темы —
**один** действующий документ (таблица ниже); если появилась вторая версия, одна уходит в `history/` с баннером
«История. Заменено: …». Ссылки проверяет `scripts/check-doc-links.sh` (входит в `make check` и CI).

Порядок чтения для новой сессии: [`ORCHESTRATOR.md`](ORCHESTRATOR.md) → [`HANDOFF.md`](HANDOFF.md) →
[`strategy/`](strategy/2026-10-23-platform-architecture-strategy.md) → `systems/<система>/CONVENTIONS.md` своей зоны.

## Тема → единственный документ

| Тема | Документ | Статус | Владелец |
|---|---|---|---|
| Процесс, роли агентов, инварианты, гейты | [`ORCHESTRATOR.md`](ORCHESTRATOR.md) | действует | архитектор |
| Среда разработки, тесты и CI (правило владельца) | [`../CLAUDE.md`](../CLAUDE.md), раздел «Среда разработки, тесты и CI» | действует | владелец |
| Где мы сейчас и что дальше | [`HANDOFF.md`](HANDOFF.md) | действует | архитектор |
| Журнал задач и PR | [`PROGRESS.md`](PROGRESS.md) | действует | лид |
| Хвосты: незакрытые дефекты, долги, открытые вопросы (единый реестр, ID `B-0xx`) | [`BACKLOG.md`](BACKLOG.md) | действует | архитектор |
| Решения владельца | [`DECISIONS.md`](DECISIONS.md) | действует | владелец |
| Открытые вопросы | [`QUESTIONS.md`](QUESTIONS.md) | действует | архитектор |
| Действия владельца вне кода | [`OWNER-CHECKLIST.md`](OWNER-CHECKLIST.md) | действует | владелец |
| Стратегия, целевая архитектура, план этапов 0, B–H | [`strategy/2026-10-23-platform-architecture-strategy.md`](strategy/2026-10-23-platform-architecture-strategy.md) | действует | архитектор |
| Архитектурные решения ансамбля | [`adr/`](adr/) (0001…0019) | действует | архитектор |
| Продукт: спецификация единого интерфейса (словарь, процессы, роли, экраны) | [`product/SPEC-v3.md`](product/SPEC-v3.md) (§4 — вместе с ADR-0012) | действует | владелец |
| Продукт: ценность систем и путь клиента | [`product/BUSINESS.md`](product/BUSINESS.md) | основание; при расхождении права SPEC-v3 | владелец |
| Шов CRM ↔ ERP: API, события, MCP, портал | [`architecture/CONTRACTS.md`](architecture/CONTRACTS.md) (машиночитаемо — `packages/contracts/`) | действует | архитектор |
| SSO-токен сотрудника | [`architecture/sso-token.md`](architecture/sso-token.md) | действует | архитектор |
| Платформа: BFF, вход, события, развёртывание | [`architecture/platform-bff.md`](architecture/platform-bff.md) | действует | архитектор |
| Платформа: фронтенд, каркас, размеры, тема | [`architecture/platform-frontend.md`](architecture/platform-frontend.md) | действует | архитектор |
| Карта интеграции: экран → BFF → домены, разрывы | [`architecture/integration-map.md`](architecture/integration-map.md) | действует | архитектор |
| Система: назначение, запуск, команды | `systems/<crm\|erp\|cabinet\|platform\|eds\|infra\|contracts\|ui-tokens>/README.md` | действует | лид |
| Система: правила кода | `systems/<crm\|erp\|cabinet\|platform\|eds>/CONVENTIONS.md` | действует | лид |
| CRM: техническое задание, бизнес-требования, разметка evals | [`systems/crm/SPEC.md`](systems/crm/SPEC.md), [`systems/crm/BUSINESS.md`](systems/crm/BUSINESS.md), [`systems/crm/evals-labeling.md`](systems/crm/evals-labeling.md) | действует для бэкенда CRM; при расхождении права `product/` | лид |
| Архитектурные решения CRM | [`adr/crm/`](adr/crm/) (обозначение «ADR CRM-00NN») | действует | архитектор |
| Эксплуатация | [`runbooks/`](runbooks/) (ансамбль), [`runbooks/crm/`](runbooks/crm/), [`runbooks/erp/`](runbooks/erp/); волны агентов — `runbooks/wave*.md` | действует | лид |
| Аудиты | [`audits/`](audits/), [`audits/crm/`](audits/crm/) | снимок на дату | архитектор |
| Исследования | [`research/`](research/) | снимок на дату | архитектор |
| База знаний CRM: формат и промпт подготовки | [`kb/`](kb/) (копию в Платформу делает `pnpm kb:sync` в `apps/platform/web`, `make -C apps/platform kb-sync`) | действует | лид |
| Скриншоты DoD | [`screens/<задача>/`](screens/) | артефакт PR | исполнитель |
| Всё недействующее | [`history/`](history/README.md) | история | — |

## Что не документация (живёт рядом с кодом)

Промпты агентов (`apps/*/backend/prompts/*.md`), шаблоны писем, фикстуры evals, навыки Claude Code
(`apps/crm/.claude/skills/`), шаблоны PR (`.github/`), машиночитаемые контракты (`packages/contracts/**`) и
сгенерированные контракты в `packages/contracts/` (включая OpenAPI CRM `openapi/crm.yaml`). Их читают код, тесты и генераторы.

## Статусы документов

- Вторая строка действующего документа: `Статус: действует · Владелец: … · Обновлено: …`.
- Первая строка исторического: `> **История.** Заменено: <путь>. Не используется для решений.`
- ADR — свой статус в шапке (proposed → accepted → superseded). Runbook волны действует, пока волна идёт; закрытая
  волна уходит в `history/runbooks/`.
