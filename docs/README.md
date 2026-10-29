# docs/ — вся документация RailTech Platform, одна правда
Статус: действует · Владелец: архитектор · Обновлено: 2026-10-29

**Правило (владелец 2026-10-23, `docs/ORCHESTRATOR.md` §3 п. 17).** Вся правда о продукте, архитектуре, процессе и
правилах кода живёт здесь, в `docs/`, и нигде больше. В `apps/*`, `packages/*`, `infra/` и корне — только указатели:
`CLAUDE.md` (что за каталог, где правила, главные команды) и `README.md` (одна фраза и ссылки сюда). У каждой темы —
**один** действующий документ (таблица ниже); если появилась вторая версия, одна уходит в `history/` с баннером
«История. Заменено: …». Ссылки проверяет `scripts/check-doc-links.sh` (входит в `make check` и CI).

## С чего начать

**Владелец продукта.**
- Что делает продукт и для кого — [`product/SPEC-v3.md`](product/SPEC-v3.md): словарь §2, процесс §3, роли §4, экраны §6.
  Как это видит сотрудник, человеческим языком по экранам, — статьи помощи [`kb/help/`](kb/help/).
- Что уже вышло — «Что нового», [`kb/help/changelog/`](kb/help/changelog/); что будет — [`kb/help/roadmap.md`](kb/help/roadmap.md).
- Где мы и что дальше — [`HANDOFF.md`](HANDOFF.md) §1 и §3; исходный план этапов — стратегия §4 и §7, поправки к нему — в
  [`DECISIONS.md`](DECISIONS.md).
- Что ждёт вашего решения — [`QUESTIONS.md`](QUESTIONS.md), раздел «Ждут владельца»; что сделать руками вне кода —
  [`OWNER-CHECKLIST.md`](OWNER-CHECKLIST.md); что уже решено — [`DECISIONS.md`](DECISIONS.md).

**Разработчик** (человек или агент-исполнитель).
- Среда, тесты и CI — [`../CLAUDE.md`](../CLAUDE.md); какие задания CI идут на какую правку — [`systems/infra/ci.md`](systems/infra/ci.md).
- Своя система: устройство и команды — `systems/<система>/README.md`, правила кода — `systems/<система>/CONVENTIONS.md`.
- Контракты между доменами — [`architecture/CONTRACTS.md`](architecture/CONTRACTS.md) и `packages/contracts/`; шина —
  [`architecture/rt-bus.md`](architecture/rt-bus.md); Платформа — `architecture/platform-*.md` и
  [`architecture/integration-map.md`](architecture/integration-map.md).
- Повторяющиеся процедуры агентов (worktree, PR, миграция, контракт, событие, снимки) — скиллы `.claude/skills/`.

**Лид и архитектор** — [`ORCHESTRATOR.md`](ORCHESTRATOR.md) (процесс, инварианты, уровни агентов, протокол сессии),
[`HANDOFF.md`](HANDOFF.md), действующие волны — [`runbooks/README.md`](runbooks/README.md), [`PROGRESS.md`](PROGRESS.md),
[`BACKLOG.md`](BACKLOG.md).

**Эксплуатация** — [`runbooks/README.md`](runbooks/README.md): серверы, деплой, бэкапы, шина, бот.

## Тема → единственный документ

| Тема | Документ | Статус | Владелец |
|---|---|---|---|
| Процесс, роли агентов, инварианты, гейты | [`ORCHESTRATOR.md`](ORCHESTRATOR.md) | действует | архитектор |
| Среда разработки, тесты и CI (правило владельца) | [`../CLAUDE.md`](../CLAUDE.md), раздел «Среда разработки, тесты и CI»; задания CI по путям — [`systems/infra/ci.md`](systems/infra/ci.md) | действует | владелец |
| Где мы сейчас и что дальше | [`HANDOFF.md`](HANDOFF.md) | действует | архитектор |
| Журнал задач и PR | [`PROGRESS.md`](PROGRESS.md) | действует | лид |
| Хвосты: незакрытые дефекты и долги (единый реестр, ID `B-<задача>-<n>`, старые — `B-0xx`) | [`BACKLOG.md`](BACKLOG.md) | действует | архитектор |
| Решения владельца и архитектора (журнал; новое перекрывает старое) | [`DECISIONS.md`](DECISIONS.md) | действует | владелец |
| Открытые вопросы (вверху — «Ждут владельца») | [`QUESTIONS.md`](QUESTIONS.md) | действует | архитектор |
| Действия владельца вне кода | [`OWNER-CHECKLIST.md`](OWNER-CHECKLIST.md) | действует | владелец |
| Стратегия, целевая архитектура, план этапов 0, B–H | [`strategy/2026-10-23-platform-architecture-strategy.md`](strategy/2026-10-23-platform-architecture-strategy.md) | действует | архитектор |
| Архитектурные решения ансамбля | [`adr/README.md`](adr/README.md) — индекс со статусами и поправками (0001…0020) | действует | архитектор |
| Продукт: спецификация единого интерфейса (словарь, процессы, роли, экраны) | [`product/SPEC-v3.md`](product/SPEC-v3.md) (§4 — вместе с ADR-0012) | действует | владелец |
| Продукт: ценность систем и путь клиента | [`product/BUSINESS.md`](product/BUSINESS.md) | основание; при расхождении права SPEC-v3 | владелец |
| Контракты доменов: API, события шины, MCP, портал | [`architecture/CONTRACTS.md`](architecture/CONTRACTS.md) (машиночитаемо — `packages/contracts/`) | действует | архитектор |
| Шина `rt_bus`: публикация, подписки, доставка, приёмник (пакет `rt-bus`) | [`architecture/rt-bus.md`](architecture/rt-bus.md), решение — [ADR-0014](adr/0014-integration-bus-rt-bus.md) | действует | архитектор |
| SSO-токен сотрудника | [`architecture/sso-token.md`](architecture/sso-token.md) | действует | архитектор |
| Платформа: BFF, вход, события, развёртывание | [`architecture/platform-bff.md`](architecture/platform-bff.md) | действует | архитектор |
| Платформа: фронтенд, каркас, размеры, тема | [`architecture/platform-frontend.md`](architecture/platform-frontend.md) | действует | архитектор |
| Документы: формат тела, бланк, рендер PDF и DOCX, «Подогнать» (пакет `rt-docs`, контракт `documents/`) | [`architecture/rt-docs.md`](architecture/rt-docs.md), решение — [ADR-0020](adr/0020-documents-letterhead-body-rendering.md) | действует | архитектор |
| Карта интеграции: экран → BFF → домены, разрывы | [`architecture/integration-map.md`](architecture/integration-map.md) | действует | архитектор |
| Система: назначение, запуск, команды | `systems/<crm\|erp\|cabinet\|platform\|eds\|infra\|contracts\|ui-tokens>/README.md`; пакеты `rt-bus` и `rt-docs` — их документы в `architecture/` | действует | лид |
| Система: правила кода | `systems/<crm\|erp\|cabinet\|platform\|eds>/CONVENTIONS.md` | действует | лид |
| CRM: техническое задание, бизнес-требования, разметка evals | [`systems/crm/SPEC.md`](systems/crm/SPEC.md), [`systems/crm/BUSINESS.md`](systems/crm/BUSINESS.md), [`systems/crm/evals-labeling.md`](systems/crm/evals-labeling.md) | действует для бэкенда CRM; при расхождении права `product/` | лид |
| Архитектурные решения CRM | [`adr/crm/`](adr/crm/) (обозначение «ADR CRM-00NN») | действует | архитектор |
| Эксплуатация: симптом → диагностика → действие | [`runbooks/README.md`](runbooks/README.md) (ансамбль), [`runbooks/crm/`](runbooks/crm/README.md), [`runbooks/erp/`](runbooks/erp/README.md) | действует | лид |
| Волны агентов: действующие runbook'и | [`runbooks/README.md`](runbooks/README.md), раздел «Действующие волны»; закрытые — [`history/runbooks/`](history/runbooks/) | действует, пока волна идёт | архитектор |
| Аудиты и отчёты гейтов (оценка нашего состояния) | [`audits/README.md`](audits/README.md) | снимок на дату | архитектор |
| Исследования (аналоги, эталоны, рынок и законы) | [`research/README.md`](research/README.md) | снимок на дату | архитектор |
| База знаний CRM: формат и промпт подготовки | [`kb/`](kb/) (копию в Платформу делает `pnpm kb:sync` в `apps/platform/web`, `make -C apps/platform kb-sync`) | действует | лид |
| Статьи помощи сотрудникам Платформы (окно «?» и раздел «Помощь») | [`kb/help/`](kb/help/) (не база знаний бота; копию в сборку делает тот же `pnpm kb:sync`; правка — PR; статьи компании «как у нас принято» пишет админ в Настройках, хранит CRM — [platform-bff §3.4](architecture/platform-bff.md), [SPEC-v3](product/SPEC-v3.md), W18A-P5) | действует | лид |
| «Что нового» для сотрудников (собирается после выкладки из строк «Для пользователей» PR) | [`kb/help/changelog/`](kb/help/changelog/), сборщик — `scripts/release_notes.py` | действует | архитектор |
| Скриншоты DoD | [`screens/<задача>/`](screens/) | артефакт PR | исполнитель |
| Всё недействующее | [`history/`](history/README.md) | история | — |

## Что не документация (живёт рядом с кодом)

Промпты агентов (`apps/*/backend/prompts/*.md`), шаблоны писем, фикстуры evals, настройки, хуки и навыки Claude Code
(`.claude/`, `apps/crm/.claude/skills/`), шаблоны PR (`.github/`), машиночитаемые контракты (`packages/contracts/**`) и
сгенерированные контракты в `packages/contracts/` (включая OpenAPI CRM `openapi/crm.yaml`). Их читают код, тесты и генераторы.

## Статусы документов

- Вторая строка действующего документа: `Статус: действует · Владелец: … · Обновлено: …`.
- Первая строка исторического: `> **История.** Заменено: <путь>. Не используется для решений.`
- `Обновлено:` меняется в том же PR, что меняет документ по существу (не опечатка), — иначе дата вводит в заблуждение.
- ADR — свой статус в шапке (proposed → accepted → superseded); поправки, внесённые позже, видны в индексе
  [`adr/README.md`](adr/README.md).
- Аудиты, отчёты гейтов и исследования — снимки на дату: строки статуса нет, дата и предмет — в имени и заголовке.
- Runbook волны действует, пока волна идёт; закрытая волна уходит в `history/runbooks/` с баннером, строка — из
  [`runbooks/README.md`](runbooks/README.md).
