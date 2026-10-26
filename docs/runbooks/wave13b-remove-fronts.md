# Волна 13b — этап C2b «Удаление старых фронтов CRM и ERP» (версия 0.12)
Статус: действует · Владелец: архитектор · 2026-10-26

Основание: стратегия §7 (C2: паритет Admin + удаление старых фронтов, без сосуществования), решение владельца 2026-10-26 («сейчас
платформой и другими сервисами никто не пользуется, поэтому удаляй когда решишь сам») и решение архитектора — **удалять сразу после
гейта C2a** ([`wave13-c2-admin.md`](wave13-c2-admin.md) A7). Инвентарь — [`wave13-c2-admin.md`](wave13-c2-admin.md) §4.4.
**Старт — только после закрытия волны 13** (гейт C2a «паритет Admin достигнут»): обе волны правят compose, Caddy, CI и деплой.
Рабочие разделы CRM, ERP и EDS в Платформе до этапа D — заглушки; бизнес-работа до D идёт через API, бот и Cabinet (пользователей нет).

## 0. Промпт лида — одним сообщением

```
Ты — лид разработки RailTech Platform (docs/ORCHESTRATOR.md §4.1), ведёшь волну 13b «Удаление старых фронтов» по
docs/runbooks/wave13b-remove-fronts.md. Код сам не пишешь. Прочитай: CLAUDE.md корня, docs/ORCHESTRATOR.md (§3, §4.1, §4.2, §7),
docs/HANDOFF.md, этот runbook, docs/runbooks/wave13-c2-admin.md §4.4, docs/runbooks/c2a_admin_gate_report.md, docs/runbooks/deploy.md,
docs/systems/infra/ci.md. Исполнители — субагенты (Agent tool) model "sonnet", не больше двух одновременно; worktree
.claude/worktrees/<задача> от свежего origin/main; каждая git-команда — git -C <абсолютный путь worktree>; тело PR — во временный файл с
уникальным именем. Преамбула — ORCHESTRATOR §4.2. Ревью — свежий субагент; итог — комментарием в PR до --auto. Перед автослиянием —
merge origin/main, make ci-local по затронутым заданиям (infra, crm, erp, platform, cabinet, contracts, gitleaks), make deploy-check,
make docs-links; затем gh pr merge --auto --merge <n>. Правка ci.yml, ci_local.sh, deploy.yml разрешена владельцем. CI не опрашиваешь;
перед раундом — одна проверка своих PR. Прод не трогаешь (деплой — архитектор). Общие очистки Docker запрещены; стенд владельца (8088)
не трогать — свой стенд -p rt-c2b. Отчёты исполнителей приходят архитектору — он перешлёт; промежуточный отчёт не отдавай.
Закрытие: docs-PR (PROGRESS — «Волна 13b»), блок для HANDOFF — архитектору (что удалено, что перенастроено, шаги деплоя).
```

## 1. Задачи

| Задача | Что | Зоны |
|---|---|---|
| **R1 Ссылки бэкендов** | Все ссылки из писем, уведомлений Telegram, мониторинга и SSO на старые фронты — на Платформу (`PLATFORM_URL` + маршруты Платформы; где экрана ещё нет — на раздел-заглушку с понятным текстом): CRM `crm_base_url` (приглашения, уведомления о лидах, мониторинг, карточка канала, внешние сервисы, состояние системы), `erp_frontend_url` и SSO-редирект на ERP; ERP `FRONTEND_URL` (письма сделок, сброс пароля, приглашения, мастер, уведомления), `CRM_FRONTEND_URL`. Удалить мёртвые после удаления фронтов направления SSO (ERP `auth/sso/token/`, CRM `/auth/sso/exchange`) и пароли/2FA/сброс ERP для сотрудников (вход — только через CRM, ADR-0011, ADR-0012); портал Cabinet не трогать. Контракты — по правилу 0.x | `apps/crm/backend`, `apps/erp/backend`, `packages/contracts`, env-примеры |
| **R2 Удаление и инфраструктура** | После R1: удалить `apps/crm/frontend`, `apps/erp/frontend`; compose (`crm-web`, `erp-web`, `caddy.depends_on`), Caddy (`handle → *-web`; домены CRM и ERP остаются для API, `/telegram/webhook`, `/ws`, `/media`, публичных ссылок; корень доменов CRM и ERP — редирект 302 на Платформу), деплой (`deploy.sh`, `rollback.sh`, `lib.sh`, `cpu-baseline-rules.sh`, тесты `infra/deploy/tests/*`), CI (`deploy.yml`, `ci.yml`, `ci-ok.needs`, `scripts/ci_local.sh`, `apps/crm/scripts/ci_local.sh`, `scripts/qemu_cpu_check.sh`), Makefile CRM и ERP (frontend-цели; генерация типов фронта — убрать), `packages/ui-tokens` (копии в фронты), синхронизация `docs/kb` — в Платформу (если не сделано в A5), env (`*_FRONTEND_URL`, CSRF/CORS ERP), образы `rt-crm-frontend`, `rt-erp-frontend` из GHCR не удалять (откат) | `apps/*`, `infra/*`, `.github/workflows/*`, `scripts/*`, `packages/ui-tokens`, `Makefile` |
| **R3 Документы** | `docs/systems/{crm,erp,infra,platform,ui-tokens,contracts,cabinet}`, `stand.md`, `servers.md`, `request-id.md`, `deploy.md` (раздел «Удаление фронтов» с шагами деплоя: удалить контейнеры `crm-web`, `erp-web` — `--remove-orphans`), указатели `apps/crm/CLAUDE.md`, `apps/erp/CLAUDE.md`, корневой `CLAUDE.md`; старые правила фронтов в `CONVENTIONS.md` — в `docs/history/` | `docs/`, указатели |

Раунды: 1 — R1; 2 — R2 ∥ R3.

## 2. «Готово, когда»

- **R1:** `git grep` по бэкендам не находит путей старых фронтов (`/#request-detail`, `/leads/`, `crm_base_url` без Платформы); тесты писем и уведомлений
  проверяют ссылки на Платформу; `make check-crm`, `make check-erp`, `make contracts`.
- **R2:** в репозитории нет `apps/crm/frontend`, `apps/erp/frontend`; `make ci-local` (все задания) и `make deploy-check` зелёные; стенд `-p rt-c2b`:
  `make smoke` (корень доменов CRM и ERP — 302 на Платформу, API и вебхук бота работают), Cabinet открывается и логинится, Платформа работает.
- **R3:** `make docs-links`; ни один действующий документ не описывает старые фронты как живые.
