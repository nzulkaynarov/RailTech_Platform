# Документация RailTech B2B — карта

Организовано по аудитории. Актуальное — в `dev/`, `business/`, `user/`. Историческое (снапшоты, закрытые аудиты, вытесненные планы) — в `old/`.

> Структура наведена 2026-07-07. Корневые `CLAUDE.md` (инструкции для Claude Code) и `README.md` (обзор проекта для GitHub) остаются в корне репозитория по требованию инструментов.

## `dev/` — для разработки

| Папка | Что внутри |
|---|---|
| `dev/adr/` | Архитектурные решения (ADR 0001–0006) — **действующий канон**: разделение админок, ролевая модель, три админ-плоскости, единая навигация, wedge-loop + entitlements |
| `dev/architecture/` | Карта системы (`master-system-document.md` — v7 living-doc, сверять с ADR), техспека, диаграммы (`architecture-diagrams.md` + `diagrams/*.drawio`), WebSocket-словарь, `schema.json` (OpenAPI) |
| `dev/ops/` | Эксплуатация: `RUNBOOK-b2b-vps.md`, деплой-уроки, observability (Sentry), email-setup, staging, smoke-checklist, stability-program, VPS-ограничения, post-deploy-todos, e2e, api-types, docker-* , **последний** session-handoff |
| `dev/specs/` | Актуальные ТЗ и дизайны: `spec-remaining-2026-07-07.md` (оставшаяся работа), `client-base-design`, `rbac-roles-design` |

## `business/` — для бизнеса

| Файл/папка | Что |
|---|---|
| `business/ROADMAP.md` | Верхнеуровневый роадмап: хроника + открытые треки |
| `business/business-logic.md` | Бизнес-процессы (FSM сделок, KYC, landed cost) |
| `business/ux-ui-brief.md` | Дизайн-концепция и требования к UI/UX |
| `business/presentations/` | Презентации + смета проекта |
| `business/mockups/` | Мокапы экранов (PNG) |

## `user/` — для пользователя

Руководства для конечных пользователей платформы. Сейчас — заготовка (в приложении справка живёт в коде, `HelpPage.tsx`); наполняется по мере появления.

## `old/` — архив (неактуальное, хранится для истории)

| Папка | Что |
|---|---|
| `old/handoffs/` | Все прежние session-handoff'ы (кроме последнего — он в `dev/ops/`) |
| `old/audits/` | Закрытые аудиты (security/arch/UX, e2e, catalog, platform, checklist) |
| `old/roadmaps/` | Вытесненные планы: `master-scope`, `ai-features-roadmap`, прежние `roadmap-*` |
| `old/checkups/` | Ранние чек-апы из корня репозитория |
| `old/misc/` | Прочее историческое: status/tech-debt снапшоты, вытесненные референсы (`role-model`, `interface-architecture`) |

> Ссылки внутри `old/` — это фиксированные снапшоты и могут указывать на прежнюю раскладку файлов; они сохранены как есть для точности истории.
