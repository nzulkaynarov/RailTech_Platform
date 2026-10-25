# Волна 12 — этап C1 «Сервис EDS» (версия 0.11)
Статус: действует · Владелец: архитектор · 2026-10-26

Основание: ADR-0015 (EDS — отдельный сервис, границы доменов), ADR-0013 (стек), ADR-0014 (шина), ADR-0012 (роли как данные),
стратегия §3.3, §4 «Этап C», §7; SPEC-v3 §2.1–§2.4, §3.2, §7.3, §10.4; карта интеграции §7 (EDS-01, EDS-02, EDS-03).
Экраны EDS в Платформе — этап D (путь заявки); в этой волне — сервис, контракт, события, связка с CRM и ERP через шину.
Параллельно может идти волна 11b ([`wave11b-tails.md`](wave11b-tails.md)) — её зоны не трогать; общие файлы (compose, Caddy,
`ci.yml`, `ci_local.sh`, `subscriptions.yaml`) — merge `origin/main` перед слиянием.

## 0. Промпт лида — одним сообщением

```
Ты — лид разработки RailTech Platform (docs/ORCHESTRATOR.md §4.1), ведёшь волну 12 «Сервис EDS» по docs/runbooks/wave12-eds-c1.md.
Код сам не пишешь. Прочитай: CLAUDE.md корня, docs/ORCHESTRATOR.md (§3, §4.1, §4.2, §7), docs/HANDOFF.md, этот runbook целиком,
ADR-0012…0016, docs/strategy/2026-10-23-platform-architecture-strategy.md (§3.3, §3.4, §4 «Этап C»), docs/product/SPEC-v3.md
(§2.1–§2.4, §3.2, §7.3, §10.4), docs/architecture/CONTRACTS.md, docs/architecture/rt-bus.md, docs/architecture/integration-map.md §7,
docs/architecture/sso-token.md, docs/systems/eds/README.md, docs/systems/platform/CONVENTIONS.md (как образец правил кода FastAPI).
Исполнители — субагенты (Agent tool): E1 — model "opus" (контракт на все стороны), остальные — "sonnet"; не больше трёх
одновременно и не больше одного набора тестов ERP за раз (ERP_TEST_NS=<задача>); worktree .claude/worktrees/<задача> от свежего
origin/main, зависимости ставишь ты; каждая git-команда исполнителя — git -C <абсолютный путь своего worktree>; задачу не строят на
неслитых ветках соседей. Преамбула исполнителя — ORCHESTRATOR §4.2. Ревью — свежий субагент ≠ исполнитель, по «готово, когда».
Перед автослиянием — merge origin/main, повтор проверок (make contracts, одна голова Alembic CRM и EDS, --migration-check ERP,
make docs-links, make deploy-check для infra); затем gh pr merge --auto --merge <n>. CI не опрашиваешь; перед раундом — одна
проверка своих PR (gh pr view <n> --json state,mergeable,mergeStateStatus,statusCheckRollup), логи не читаешь. Правка ci.yml,
ci_local.sh и deploy.yml для сервиса EDS разрешена владельцем (как для Платформы 2026-10-22). Прод не деплоишь.
Отчёты исполнителей приходят архитектору — он перешлёт; промежуточный отчёт не отдавай, финальный — при закрытой волне.
Решения вне §2 — архитектору. Закрытие: docs-PR (PROGRESS — «Этап C1: EDS»), блок для HANDOFF — архитектору в отчёте.
```

## 1. Задачи и порядок

| Задача | Что | Зоны | Модель | Ветка |
|---|---|---|---|---|
| **E1 Контракт EDS** | `packages/contracts/openapi/eds.yaml` 0.1.0 (по §2.3); схемы событий `uz.railtech.eds.*` (§2.4) с примерами и AsyncAPI; подписки EDS в `bus/subscriptions.yaml`; в `platform-rbac.yaml` — отображение разделов `eds.inbox`, `eds.memo.create`, `eds.memo.approve`, `eds.drafts` (одобрение) на права EDS (`backend.eds`, §2.2); аддитивное поле `permissions.eds` в `identity` `User` (v1, необязательное); `ERP quote.ready_for_approval.v1`; генерация моделей; `docs/architecture/CONTRACTS.md` — раздел EDS | `packages/contracts`, `docs/architecture` | opus | `c1/e1-eds-contract` |
| **E2 Каркас сервиса** | `apps/eds`: FastAPI + SQLAlchemy 2 + Alembic + Procrastinate, `rt_bus` (outbox, inbox, приёмник `/bus/v1/events`, ретранслятор), `/health`, проверка токена сотрудника (§2.2), проекция сотрудников из `identity.user.*`; Dockerfile (Debian, проходит `cpu-baseline-check`), compose dev/prod (`eds-api`, `eds-worker`, `eds-migrate`), база `eds` (`db-init`, `infra/db` прод: роль `eds_app`, `10-prod-init.sh`, `reset-prod.sh` — список баз), бакет `eds-private` и ключ S3 сервиса (как S0-9), Caddy — **без** внешнего маршрута (только внутренняя сеть: BFF, шина); `make check-eds`, задание `eds` в `ci.yml` и `ci_local.sh`; `docs/systems/eds/README.md` + `CONVENTIONS.md`, указатели `apps/eds/CLAUDE.md`, `README.md` | `apps/eds`, `infra/*`, `.github/workflows/ci.yml`, `scripts/ci_local.sh`, `Makefile`, `docs/systems/eds` | sonnet | `c1/e2-eds-skeleton` |
| **E3 Домен EDS** | Реестр и нумерация (§2.1), входящие письма и резолюции (SPEC §2.4, §7.3), служебные записки, заявления, отчёты (SPEC §3.2), общий движок маршрутов согласования (§2.5), журнал «кто, что, когда, файл», файлы в S3 с версиями; API по `eds.yaml`; публикация событий в транзакции (outbox); права по §2.2 | `apps/eds` | sonnet | `c1/e3-eds-domain` |
| **E4 CRM → EDS** | CRM вычисляет `permissions.eds` сотрудника из каталога (как права ERP, ADR-0012 п. 5) и публикует в `identity.user.*`; пересчёт при изменении ролей; токен сотрудника для EDS (`aud` EDS, тот же механизм, что для ERP) | `apps/crm` | sonnet | `c1/e4-crm-eds-identity` |
| **E5 ERP ↔ EDS** | ERP подписан на `eds.letter.resolved` → задание расчёта по сделке (исполнители, срок, мин. маржа; стадия `CALCULATION`); на `eds.letter.rejected` → сделка в `LOST` с причиной. **EDS-03:** ERP публикует `quote.ready_for_approval` вместо своей цепочки одобрения директором, применяет `eds.approval.decided` (одобрено — ИСХ-номер из события на КП, отправка разблокирована; возвращено — КП «На доработке» с комментарием); прежняя цепочка `quote.approve_final` для директора удаляется (карт-бланш, без переходного периода) | `apps/erp` | sonnet | `c1/e5-erp-eds` |
| **E6 Гейт C1 (QA)** | На одном стенде compose (`-p rt-c1`): §3 «Гейт этапа C1». Отчёт — `docs/runbooks/c1_eds_gate_report.md` | стенд, `docs/` | sonnet | `qa/c1-eds-gate` |

Раунды: 1 — E1 ∥ E2 (E2 строит каркас без доменных моделей; контракт E1 сливается первым); 2 — E3 ∥ E4; 3 — E5; 4 — E6.

## 2. Нормативное

### 2.1. Реестр и нумерация
EDS — единственный владелец номеров документов-реестра: `ВХ-NNN/ГГ` (входящее), `ИСХ-NNN/ГГ` (исходящий, присваивается при
одобрении КП и при отправке письма), `СЗ-ГГГГ/NNN` (служебная), `ЗЯ-ГГГГ/NNN` (заявление), `ОТ-ГГГГ/NNN` (отчёт). Счётчик — на тип и год,
без пропусков: строка счётчика под `SELECT … FOR UPDATE` в транзакции создания; отменённый документ номер не возвращает. Номера
ЗВ/ПР/КП/ДОГ/СЧ/АКТ остаются у ERP (коммерческие объекты); EDS хранит их как ссылки. Год — по часовому поясу компании (`Asia/Tashkent`).

### 2.2. Доступ
- Сотрудник приходит в EDS только через BFF с токеном сотрудника, выпущенным CRM (`docs/architecture/sso-token.md`, своя `aud` для EDS).
  Своей формы входа у EDS нет; машинный доступ — только приёмник шины с подписью.
- Права — данные: CRM вычисляет `permissions.eds` из ролей по каталогу и публикует в `identity.user.created/updated`; EDS держит
  проекцию сотрудников (inbox, идемпотентно) и проверяет право на каждый запрос. Коды прав v1: `letters.read`, `letters.register`,
  `letters.resolve`, `memos.create`, `memos.approve`, `approvals.decide`, `registry.read`, `registry.export`.
- Отображение каталога (E1): `eds.inbox` read → `letters.read, registry.read`, full → `+ letters.register, letters.resolve`;
  `eds.memo.create` → `memos.create`; `eds.memo.approve` → `memos.approve`; `eds.drafts` full → `approvals.decide`;
  `eds.projects`/`eds.payments` read → `registry.read`, `data.export` → `registry.export`. Системный «Директор» получает всё по
  каталогу; «Администратор» бизнес-документов не видит (решение R3-D-2).

### 2.3. API v0.1 (`eds.yaml`, префикс `/api/v1`)
`GET/POST /letters`, `GET /letters/{no}`, `POST /letters/{no}/resolution {text, assignees[{crm_user_id, zone}], due, min_margin_pct}`,
`POST /letters/{no}/return {comment}`, `POST /letters/{no}/reject {reason}`; `GET/POST /documents` (типы `memo`, `application`, `report`,
`letter_out`; поля SPEC §10.4 `ServiceMemo`), `GET /documents/{no}`, `POST /documents/{no}/submit`; `GET /approvals?mine=1`,
`GET /approvals/{id}`, `POST /approvals/{id}/decision {decision: approve|return|reject, comment}` (comment обязателен для `return` и
`reject`); `GET /registry` (все документы с фильтрами SPEC §7.3 «Все документы»), `GET /registry/export`; `POST /files`, `GET /files/{id}`
(поток, версии). Ошибки — единый формат, как у BFF; пагинация — курсором.

### 2.4. События (`uz.railtech.eds.<сущность>.<действие>.v1`)
Публикует EDS: `letter.registered`, `letter.resolved` (исполнители, срок, мин. маржа, ссылка на заявку ERP), `letter.returned`,
`letter.rejected` (причина), `document.registered`, `document.archived`, `approval.requested` (маршрут открыт), `approval.decided`
(решение, комментарий, ИСХ-номер для КП). Публикует ERP: `uz.railtech.erp.quote.ready_for_approval.v1` (КП, сумма, маржа, виза
снабженца и гл. инженера, порог маржи из резолюции). Подписки EDS: `identity.user.*`, `erp.request.created` (связать письмо с
заявкой), `erp.quote.ready_for_approval`. Подписки ERP: `eds.letter.resolved`, `eds.letter.rejected`, `eds.approval.decided`.
Подписка `platform-bff`: `eds.*` (колокольчик и счётчики — экраны на этапе D).

### 2.5. Движок маршрутов согласования
Маршрут — упорядоченные шаги «кто решает» (конкретный сотрудник или «любой с правом X»); шаблоны v1: «Служебная записка» —
директор, затем бухгалтер, если указана сумма; «КП» — директор с чек-листом (визы, маржа ≥ порога резолюции; кнопка одобрения
недоступна, пока чек-лист не зелёный — проверка на сервере); «Заявление», «Отчёт» — директор. Решения: `approve`, `return`
(на доработку, автор правит и отправляет снова — новая версия), `reject`. Каждое решение — строка журнала и событие. Маршрут не
знает про коммерческое содержание: данные КП приходят снимком в `quote.ready_for_approval` и хранятся в маршруте только для показа.

## 3. «Готово, когда» и гейт этапа C1

- **E1**: `make contracts` зелёный (схемы, примеры, AsyncAPI, совместимость, генерация моделей); `eds.yaml` проходит линт; каталог
  проходит тест «ровно один каталог» и тест отображения.
- **E2**: `make check-eds` (ruff, mypy, pytest) и задание CI; `make deploy-check` (compose prod, `cpu-baseline` нового образа);
  на стенде `eds-api` healthy, снаружи маршрута нет (404 через Caddy), приёмник шины принимает подписанное событие.
- **E3**: тесты на каждое правило §2.1, §2.2, §2.5 (нумерация без пропусков при параллельных запросах, право на каждый эндпоинт,
  обязательный комментарий, повторная отправка после возврата, маршрут с суммой уходит бухгалтеру); откат транзакции — события нет.
- **E4**: тест «изменение роли → `identity.user.updated` с новым `permissions.eds`»; `make check-crm`.
- **E5**: тесты подписок и EDS-03; старой цепочки одобрения КП директором в ERP нет; `make check-erp`, `--migration-check`.
- **Гейт C1 (E6, стенд compose):** заявка из CRM → `erp.request.created` → письмо зарегистрировано в EDS (ВХ-номер) → резолюция
  директора через API EDS → ERP создал задание расчёта с исполнителями и маржой; служебная записка с суммой проходит директор →
  бухгалтер; КП: ERP `quote.ready_for_approval` → EDS маршрут → `approval.decided` → КП одобрено с ИСХ-номером; роль «Менеджер и
  бухгалтер» видит в EDS ровно свои права; EDS остановлен на 10 минут — CRM и ERP работают, события доходят после включения;
  нумерация не даёт пропусков на 50 параллельных созданиях.

## 4. Решения архитектора к этой волне (записаны в `DECISIONS.md` 2026-10-26)
1. Нумерация реестра — в EDS; коммерческие номера — в ERP (§2.1).
2. Права EDS — проекция из `identity.user.*` с вычисленными CRM `permissions.eds`; своей модели ролей у EDS нет (§2.2).
3. Одобрение КП директором — только маршрут EDS (EDS-03), прежняя цепочка ERP удаляется без переходного периода (карт-бланш).
4. EDS не имеет внешнего маршрута в Caddy: сотрудники — через BFF Платформы (этап D), системы — через шину.
