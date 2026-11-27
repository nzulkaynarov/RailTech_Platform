# docs/ — вся документация RailTech Platform, одна правда
Статус: действует · Владелец: архитектор · Обновлено: 2026-11-27

**Курс — [`COURSE.md`](COURSE.md). Список — [`LIST.md`](LIST.md).** Курс: куда идём и что не делаем; список «Что мешает работать» —
единственная очередь работ; отложенное — [`LATER.md`](LATER.md). Остальные управляющие документы — справочники и журнал решений.

**Правило (владелец 2026-10-23, `docs/ORCHESTRATOR.md` §3 п. 17).** Вся правда о продукте, архитектуре, процессе и
правилах кода живёт здесь, в `docs/`, и нигде больше. В `apps/*`, `packages/*`, `infra/` и корне — только указатели:
`CLAUDE.md` (что за каталог, где правила, главные команды) и `README.md` (одна фраза и ссылки сюда). У каждой темы —
**один** действующий документ (таблица ниже); если появилась вторая версия, одна уходит в `history/` с баннером
«История. Заменено: …». Ссылки проверяет `scripts/check-doc-links.sh` (входит в `make check` и CI).

## С чего начать

**Владелец продукта — 15 минут.**
- [`COURSE.md`](COURSE.md) — куда идём, что значит «готово», что не делаем сейчас (5 минут). Меняется только вашим решением.
- [`LIST.md`](LIST.md) — что мешает работать сейчас, по шагам пути сделки, с состоянием (5 минут); [`LATER.md`](LATER.md) — что отложено и когда вернёмся.
- [`QUESTIONS.md`](QUESTIONS.md) — что ждёт вашего решения (не больше трёх); [`DECISIONS.md`](DECISIONS.md) — что уже решено;
  [`OWNER-CHECKLIST.md`](OWNER-CHECKLIST.md) — что сделать руками вне кода.
- Нужно глубже — продукт: [`product/SPEC-v3.md`](product/SPEC-v3.md), экраны по ролям — [`product/NAVIGATION.md`](product/NAVIGATION.md);
  как это видит сотрудник — статьи помощи [`kb/help/`](kb/help/); что уже вышло — «Что нового», [`kb/help/changelog/`](kb/help/changelog/).

**Разработчик** (человек или агент-исполнитель).
- Среда, тесты и CI — [`../CLAUDE.md`](../CLAUDE.md); какие задания CI идут на какую правку — [`systems/infra/ci.md`](systems/infra/ci.md).
- Своя система: устройство и команды — `systems/<система>/README.md`, правила кода — `systems/<система>/CONVENTIONS.md`.
- Контракты между доменами — [`architecture/CONTRACTS.md`](architecture/CONTRACTS.md) и `packages/contracts/`; шина —
  [`architecture/rt-bus.md`](architecture/rt-bus.md); Платформа — `architecture/platform-*.md` и
  [`architecture/integration-map.md`](architecture/integration-map.md).
- Повторяющиеся процедуры агентов (worktree, PR, миграция, контракт, событие, снимки) — скиллы `.claude/skills/`.

**Лид и архитектор** — [`COURSE.md`](COURSE.md), [`LIST.md`](LIST.md), [`ORCHESTRATOR.md`](ORCHESTRATOR.md) (процесс, инварианты,
уровни агентов, протокол сессии), [`DECISIONS.md`](DECISIONS.md), [`QUESTIONS.md`](QUESTIONS.md). Журнал PROGRESS, HANDOFF и реестр BACKLOG ведутся
в [`history/`](history/) и не обновляются (решение 2026-11-27).

**Эксплуатация** — [`runbooks/README.md`](runbooks/README.md): серверы, деплой, бэкапы, шина, бот.

## Тема → единственный документ

| Тема | Документ | Статус | Владелец |
|---|---|---|---|
| Процесс, роли агентов, инварианты, гейты | [`ORCHESTRATOR.md`](ORCHESTRATOR.md) | действует | архитектор |
| Среда разработки, тесты и CI (правило владельца) | [`../CLAUDE.md`](../CLAUDE.md), раздел «Среда разработки, тесты и CI»; задания CI по путям — [`systems/infra/ci.md`](systems/infra/ci.md) | действует | владелец |
| Рабочее место агентов Claude Code: права, хуки, проверка коммита | [`systems/infra/claude-code.md`](systems/infra/claude-code.md) | действует | архитектор |
| **Курс**: цель, этап, критерий «готово», приоритеты, что не делаем (≤ 45 строк) | [`COURSE.md`](COURSE.md) | действует с 2026-11-27 | владелец |
| **Что мешает работать** — единственная очередь работ и правило разбора (класс 0–5) | [`LIST.md`](LIST.md) | действует | архитектор |
| **Не сейчас** — отложенное с условием возврата | [`LATER.md`](LATER.md) | действует | архитектор |
| Прежние «где мы», журнал задач, реестр хвостов, runbook'и волн и план до запуска | [`history/`](history/) (`HANDOFF.md`, `PROGRESS.md`, `BACKLOG.md`, `runbooks/`) | история с 2026-11-27 | — |
| Решения владельца и архитектора (журнал; новое перекрывает старое) | [`DECISIONS.md`](DECISIONS.md) | действует | владелец |
| Открытые вопросы (вверху — «Ждут владельца») | [`QUESTIONS.md`](QUESTIONS.md) | действует | архитектор |
| Действия владельца вне кода | [`OWNER-CHECKLIST.md`](OWNER-CHECKLIST.md) | действует | владелец |
| **Стратегия: что действует** — какой документ главный в каком вопросе, снятые противоречия | [`strategy/README.md`](strategy/README.md) | утверждено 2026-11-17 | архитектор |
| Стратегия выхода на рынок: цели на 3 года и 12 месяцев, роль компании, порядок интеграций и работы | [`strategy/2026-11-09-market-strategy.md`](strategy/2026-11-09-market-strategy.md) | действует | владелец |
| Дорожная карта владельца: главный порядок работ до запуска и после | [`strategy/2026-11-10-owner-roadmap.md`](strategy/2026-11-10-owner-roadmap.md) | принято 2026-11-10, правка 2026-11-17 | владелец |
| Готовые решения: правило выбора (библиотека, лицензия, один интерфейс, память) и перечни «берём», «по условию», «не берём» | [`strategy/2026-11-12-ready-solutions.md`](strategy/2026-11-12-ready-solutions.md) | действует с 2026-11-12 | архитектор |
| Стратегия экосистемы и профиль международной сертификации (кибербезопасность и качество) | [`strategy/2026-11-07-ecosystem-and-certification-strategy.md`](strategy/2026-11-07-ecosystem-and-certification-strategy.md) | действует (§3–§4) | владелец |
| Целевая архитектура (§3); план этапов 0, B–H — история | [`strategy/2026-10-23-platform-architecture-strategy.md`](strategy/2026-10-23-platform-architecture-strategy.md) | действует в части архитектуры | архитектор |
| Сквозной процесс и пути ролей (§2–§4); порядок работ перед пилотом — история | [`strategy/2026-11-01-plan-refresh.md`](strategy/2026-11-01-plan-refresh.md) | действует в части процесса | архитектор |
| Архитектурные решения ансамбля | [`adr/README.md`](adr/README.md) — индекс со статусами и поправками (0001…0021) | действует | архитектор |
| Продукт: спецификация единого интерфейса (словарь, процессы, роли, экраны) | [`product/SPEC-v3.md`](product/SPEC-v3.md) (§4 — вместе с ADR-0012) | действует | владелец |
| Продукт: ценность систем и путь клиента | [`product/BUSINESS.md`](product/BUSINESS.md) | основание; при расхождении права SPEC-v3 | владелец |
| Модули как коробочные решения: границы, функции, статус | [`product/MODULES.md`](product/MODULES.md) | принято владельцем 2026-11-09, пересмотр утверждён 2026-11-10 | владелец |
| Бизнес-процесс компании: процессы, шаги, модули | [`product/BUSINESS-PROCESS.md`](product/BUSINESS-PROCESS.md) | уточнён владельцем 2026-11-09 | владелец |
| Навигация Платформы: меню, роли, процесс → экран, сверка со стандартами | [`product/NAVIGATION.md`](product/NAVIGATION.md), правила рабочего места — [`research/2026-11-10-workspace-ux.md`](research/2026-11-10-workspace-ux.md) | принята владельцем 2026-11-10; заменяет SPEC-v3 §6.2 | владелец |
| Продукт: кабинет контрагента — отношения, шаблоны ролей, подключаемые модули (концепция) | [`product/COUNTERPARTY-CABINET.md`](product/COUNTERPARTY-CABINET.md), бенчмарк [`research/2026-11-01-counterparty-cabinet`](research/2026-11-01-counterparty-cabinet/README.md), карта пути [`research/2026-11-04-counterparty-journey`](research/2026-11-04-counterparty-journey/README.md) | утверждено 2026-11-01; ADR и волны K0–K5 — по §9 | владелец |
| Контракты доменов: API, события шины, MCP, портал | [`architecture/CONTRACTS.md`](architecture/CONTRACTS.md) (машиночитаемо — `packages/contracts/`) | действует | архитектор |
| Шина `rt_bus`: публикация, подписки, доставка, приёмник (пакет `rt-bus`) | [`architecture/rt-bus.md`](architecture/rt-bus.md), решение — [ADR-0014](adr/0014-integration-bus-rt-bus.md) | действует | архитектор |
| Статусы объектов: одно слово на состояние, ru · uz · en, для всех поверхностей | [`architecture/status-dictionary.md`](architecture/status-dictionary.md), проверка текстов — `scripts/copy_guard/` | действует (Кабинет приведён, остальное — по PR ТЕКСТ) | архитектор |
| SSO-токен сотрудника | [`architecture/sso-token.md`](architecture/sso-token.md) | действует | архитектор |
| Платформа: BFF, вход, события, развёртывание | [`architecture/platform-bff.md`](architecture/platform-bff.md) | действует | архитектор |
| Платформа: фронтенд, каркас, размеры, тема | [`architecture/platform-frontend.md`](architecture/platform-frontend.md) | действует | архитектор |
| Стандарт интерфейса Платформы и Cabinet: цвет, шрифт, окна, таблицы, формы, чек-лист экрана | [`architecture/ui-standard.md`](architecture/ui-standard.md), разбор — [`research/2026-11-15-ui-standard-assessment.md`](research/2026-11-15-ui-standard-assessment.md) | действует | архитектор |
| Стандарт документов и писем: шрифт, палитра печати, бланк, письмо, КП и счёт, договор, почта, подпись сотрудника | [`architecture/documents-standard.md`](architecture/documents-standard.md), разбор — [`research/2026-11-15-documents-standard-assessment.md`](research/2026-11-15-documents-standard-assessment.md) | действует | архитектор |
| Документы: формат тела, бланк, рендер PDF и DOCX, «Подогнать» (пакет `rt-docs`, контракт `documents/`) | [`architecture/rt-docs.md`](architecture/rt-docs.md), решение — [ADR-0020](adr/0020-documents-letterhead-body-rendering.md) | действует | архитектор |
| Карта интеграции: экран → BFF → домены, разрывы | [`architecture/integration-map.md`](architecture/integration-map.md) | действует | архитектор |
| Система: назначение, запуск, команды | `systems/<crm\|erp\|cabinet\|platform\|eds\|infra\|contracts\|ui-tokens>/README.md`; пакеты `rt-bus` и `rt-docs` — их документы в `architecture/` | действует | лид |
| Система: правила кода | `systems/<crm\|erp\|cabinet\|platform\|eds>/CONVENTIONS.md` | действует | лид |
| Уведомления контрагента: колокольчик кабинета, канал по контакту, событие → бот / ERP / письмо | [`systems/erp/notifications.md`](systems/erp/notifications.md) | действует (NOTIFY-2, ADR-0023 п. 2) | лид ERP |
| Оферта и политика Кабинета: редакции, акцепт при входе, гейт кабинета | [`systems/erp/cabinet-legal.md`](systems/erp/cabinet-legal.md) | действует (ДВ-5) | лид ERP |
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
