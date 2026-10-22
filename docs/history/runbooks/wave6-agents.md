# Runbook: волна 6 — остаток M3, шов 0.3.0, задачи M5 до пилота

Старт — **после гейтов M1 и M2** (волна 5 закрыта, владелец отметил гейты): до этого код под прогоном не меняется.
Решения — `docs/DECISIONS.md` 2026-10-21. Контракт шва 0.3.0 (архитектор) уже закоммичен в ветку `fix/all-60-seam-030`
(коммит `2d7a9001`, worktree `.claude/worktrees/fix-60`): `erp-integration.yaml` 0.3.0, `events.schema.json`, `docs/architecture/CONTRACTS.md` §3,
пример события `quote.acceptance_code_requested`. Контракт в волне правит только архитектор.

Цель волны — гейт **M3** (ORCHESTRATOR §6): лид из Telegram передаётся одной кнопкой, клиент получает приглашение, события ERP
в ленте лида, бот отвечает «где мой счёт / когда поставка» по данным ERP, сотрудник переключается CRM ↔ ERP без входа; и всё, что
нужно M5 до пилота, кроме данных владельца.

## 0. Промпт лида — одним сообщением

```
Ты — лид разработки RailTech Platform (ORCHESTRATOR §4.1), ведёшь волну 6 по docs/history/runbooks/wave6-agents.md. Код сам не пишешь.
Прочитай: CLAUDE.md корня, docs/ORCHESTRATOR.md (§3, §4.1, §6 «M3», «M5», §7), docs/HANDOFF.md, этот runbook целиком,
docs/architecture/CONTRACTS.md, docs/PROGRESS.md, CLAUDE.md приложений, docs/history/runbooks/wave5-agents.md §5.0 (преамбула — общая) и §6–§7.
Работай по раундам §3: worktree от свежего origin/main (FIX-60a/b — от fix/all-60-seam-030), зависимости, исполнители
субагентами (model sonnet, run_in_background=false — ждёшь результата в своём ходе) с промптом «преамбула wave5 §5.0 с
подставленными значениями + раздел §4.x этого runbook'а». Ревью — свежим субагентом ≠ исполнителю, по «готово, когда»;
перед автослиянием — merge origin/main в ветку и `--migration-check` ERP / голова Alembic CRM на итоговой ветке (две
миграции с одним номером уже дважды ломали CI). Затем gh pr merge --auto --merge <n>. Перед раундом — одна проверка своих PR
(gh pr view --json state,mergeable,mergeStateStatus,statusCheckRollup, без логов). PROGRESS ведёшь ты — docs-PR после раунда.
Платные прогоны моделей (eval) — только с «да» владельца на конкретный прогон: спроси через отчёт, не запускай сам.
Закрытие: строки задач «готово» с PR, строка M3 «готово к гейту — M3-QA-01 пройден, ждёт владельца», HANDOFF §3, хвосты,
один docs-PR; доложи архитектору — что владелец проверяет сам на гейте M3.
```

## 1. Исходное состояние (архитектор, `main @ 206aaee7`, 2026-10-21)

- Волны 0–4 закрыты, волна 5 (прогоны M1/M2) идёт. M3 разморожена: из задач M3 открыты M3-ERP-05, M3-ERP-06, M3-CRM-07,
  M3-CRM-10, M3-CRM-11, M3-QA-01 (остальные — «готово» в PROGRESS).
- Шов 0.3.0 (коммит `2d7a9001`): 429 `TOO_MANY_REQUESTS` с `Retry-After` на всех 12 операциях integration (лимит токена уже
  есть в ERP — `INTEGRATION_RATE`, Q-FIX35-1); `ContactFields` + закрытые `ContactIn`/`Contact` через `unevaluatedProperties`
  (сторож FIX-35 держит обход `allof_safe` — снять, Q-FIX35-3); `CompanySummary.receivables_by_currency` (Q-FIX30-2);
  описание `erp_document_id` = id портала (FIX-38); подпись вебхука v2 `HMAC(secret, "{X-Event-Id}.{X-Timestamp}.{body}")` с
  окном 300 с и переходом `ERP_WEBHOOK_SIGN_LEGACY` (Q-FIX35-2); «постоянный отказ — 200 и `rejected`» (Q-FIX33-1) и терпимый
  читатель (Q-FIX35-4) — записаны; событие `quote.acceptance_code_requested` (код акцепта контакту в Telegram через бот CRM,
  Q-FIX22-1); `QuoteOutcome.erp_contact_id`/`crm_contact_id` — кто принял (Q-FIX22-6).
- Код акцепта в Telegram сейчас — прямой Bot API из ERP за флагом `PORTAL_ACCEPT_CODE_TELEGRAM` (`portal/services/acceptance.py`,
  `core/settings/base.py`) — снять после события.
- `act.returned` не выпускается: `reject_act` ставит `DRAFT` (Q-FIX35-5); тест `test_act_returned_has_no_trigger_in_the_real_flow`
  фиксирует разрыв. Решение: событие на возврате акта клиентом/сотрудником, статус возврата — без нового кода статуса, по
  факту перехода с `returned_reason`.
- Приёмка всех строк поставки не двигает исполнение (Q-FIX22-5 ч. 2): `update_fulfillment_status` требует исполнителя-человека.
- В проде схема событий не смонтирована в ERP (Q-FIX35-5 п. 2): проверка тела события пропускается.
- Статус бэкапа в «Центре внешних сервисов» на прод-схеме пуст (Q-M5-2 → M5-CRM-01).
- Q-FIX31-5 (связь по ИНН без доступа в Cabinet) — решено по рекомендации (DECISIONS 2026-10-21), задач нет.

## 2. Раскладка

| Задача | Системы | Размер | Зависит | Зоны кода | Конфликтует |
|---|---|---|---|---|---|
| **FIX-60a** шов 0.3.0 — ERP | ERP | M | контракт `2d7a9001` | `integration/*` (429 уже есть — сторож), `portal/services/acceptance.py`, `parties` (код акцепта ↔ контакт), сторож `test_contract_integration.py` | 61, 62 |
| **FIX-60b** шов 0.3.0 — CRM | CRM | M | контракт | `integrations/erp.py` (429, `Retry-After`), `schemas/erp_events.py`, `services/erp_events.py` (код акцепта — бот, без журнала кода), карточка клиента (долг по валютам) | 61, M5-CRM-01 |
| **FIX-61** подпись вебхука v2 | ERP + CRM | S–M | FIX-60 | ERP `integration/services/webhooks.py`; CRM `api/v1/integrations.py`; настройка перехода | 60 |
| **FIX-62** `act.returned` и приёмка всех строк | ERP | S | — | `crm/services/billing.py` (`reject_act`), `integration/signals.py`, `sales` (все строки приняты → исполнение через сервис, актор «клиент») | 60a |
| **M3-ERP-05 + M3-CRM-10** сопряжение в один клик | ERP + CRM | M–L | — | ERP: приём кода сопряжения, токены и секрет шифрованно в БД; CRM: «Подключить ERP» в «Подключениях» | 11 |
| **M3-ERP-06** внешние сервисы ERP в `/health` | ERP + CRM | M | — | ERP `GET /health` `externals[]`; CRM центр внешних сервисов (M3-CRM-12 — CRM-часть есть) | M5-CRM-01 |
| **M3-CRM-11** единая консоль настроек | CRM + ERP | M | M3-ERP-05 | общие настройки из CRM в ERP с кэшем и статусом | 10 |
| **M3-CRM-07** сервисный режим бота через `erp-mcp` | CRM | L | FIX-60 | промпт `dialog_customer.md`, golden-кейсы, разбор 401/400/429 клиента MCP (Q-FIX36-1), профиль `mcp` в прод | — |
| **M5-CRM-01** статус бэкапов из RustFS | CRM | S | — | центр внешних сервисов CRM | M3-ERP-06 |
| **M5-INF-01c** схема событий в проде | infra | S | — | `infra/compose/prod.yml` (монтирование `events.schema.json` в `erp-backend`, `erp-worker*`, `erp-beat`), `deploy.yml` (в релиз) | — |
| **M5-ERP-01** перенос данных старого прода | ERP | L | волна 4 | скрипт переноса из схемы тега `b2b-final`, сверка, идемпотентность | — |
| **M3-QA-01** сквозной прогон M3 | QA | M | всё выше | стенд | — |

## 3. Раунды

Docker: не больше трёх наборов `ERP_TEST_NS` при остановленном стенде, двух — при запущенном.

1. **FIX-60a ∥ FIX-60b** (обе половины от `fix/all-60-seam-030`, сливаются в неё, PR один — с контрактом) **∥ M3-ERP-05 +
   M3-CRM-10** (одна ветка, один PR) **∥ M5-CRM-01 ∥ M5-INF-01c**.
2. **FIX-61** (от свежего `main` после FIX-60) **∥ FIX-62 ∥ M3-ERP-06 ∥ M3-CRM-11**.
3. **M3-CRM-07 ∥ M5-ERP-01**.
4. **M3-QA-01** на стенде от свежего `main` → гейт M3 владельцем.

## 4. Задачи («готово, когда»)

### 4.60. FIX-60 — шов 0.3.0 (a — ERP, b — CRM; один PR с контрактом)
a) ERP: сторож integration без `allof_safe`, на каждую операцию — вызов 429 (`INTEGRATION_RATE=1/minute`); `receivables_by_currency`
по счетам без пересчёта курса; событие `quote.acceptance_code_requested` при `POST /quotes/{id}/request-code` для контакта с
Telegram и сопоставлением в CRM (иначе — письмо, как сейчас); прямой вызов Bot API и флаг `PORTAL_ACCEPT_CODE_TELEGRAM`
сняты; код акцепта привязан к контакту (`QuoteAcceptanceCode` → контакт, ввод чужим контактом — `QUOTE_CODE_INVALID`);
`quote.accepted|rejected` несут `erp_contact_id`/`crm_contact_id`. Тесты на каждую ветку.
b) CRM: клиент ERP на 429 ждёт `Retry-After` и повторяет в задачах очереди (проверка связи — понятный статус); событие кода —
бот присылает код контакту (тексты ×3 в `settings.texts`), `payload.code` не попадает в журнал `erp_incoming_events`, ленту
и логи (тест по содержимому журнала и `caplog`); карточка клиента — долг по валютам; контакты в ленте акцепта.
Готово, когда: `make contracts`, `make check-erp`, `make check-crm`, `scripts/ci_local.sh crm-integration` зелёные на итоговой
ветке; PR «FIX-60: шов 0.3.0 — ERP и CRM».

### 4.61. FIX-61 — подпись вебхука v2
CRM принимает обе схемы (`ERP_WEBHOOK_SIGN_LEGACY=true` по умолчанию в этом PR), окно `X-Timestamp` 300 с → 200 `rejected`;
ERP подписывает v2 и заново при каждом ретрае; после выкладки — настройка `false` (строка в `docs/runbooks/webhooks.md`).
Хеш тела (FIX-35) остаётся. Готово: тесты «перехват тела под новым `X-Event-Id` — отказ», «старый `X-Timestamp` — `rejected`»,
«обе схемы в переходе»; `check-erp`, `check-crm`, `crm-integration` зелёные.

### 4.62. FIX-62 — `act.returned` и приёмка всех строк
Возврат акта (портал `POST /acts/{id}/return`, сотрудник) выпускает `act.returned` с причиной; тест
`test_act_returned_has_no_trigger_in_the_real_flow` заменён на положительный. Все строки поставки сделки приняты клиентом →
исполнение `ACCEPTED` через сервис с актором «клиент» (без обхода FIX-13), событие `delivery.status_changed`. Готово: тесты,
`check-erp`.

### 4.05. M3-ERP-05 + M3-CRM-10 — сопряжение в один клик
По ORCHESTRATOR §6 M3 (DoD там же) и §3.13: в CRM «Подключить ERP» генерирует оба сервисных токена и секрет вебхуков и
передаёт ERP по одноразовому коду сопряжения (срок, один раз); ERP хранит их шифрованно в БД, `.env` — запасной путь;
статус в «Подключениях». Готово: тест сопряжения (успех, повтор кода, просрочка), скриншоты 1440/390 CRM, `check-erp`,
`check-crm`.

### 4.06. M3-ERP-06 — внешние сервисы ERP
По ORCHESTRATOR §6 M3: `externals[]` в `GET /health` integration (курсы ЦБ, ТН ВЭД, почта ERP, LiteLLM, S3, Sentry — статус,
последняя успешная операция, последняя ошибка, без секретов); CRM показывает их в центре внешних сервисов. Контракт `Health`
— при расхождении вопрос архитектору до кода.

### 4.11. M3-CRM-11 — единая консоль настроек
По ORCHESTRATOR §6 M3: ERP получает из CRM общие настройки (SMTP-релей, LiteLLM, имя бота, `PLATFORM_NAME`, e-mail поддержки)
по integration с сервисным токеном, кэш со статусом «получено / устарело / ошибка»; в ERP — только чтение (как FIX-42).

### 4.07. M3-CRM-07 — сервисный режим бота
По ORCHESTRATOR §6 M3: промпт `dialog_customer.md`, golden-кейсы («где счёт», «когда поставка», «пришлите договор», «сколько
стоит X» — цена только клиенту), разбор 401/400/429 клиента MCP (Q-FIX36-1: 401 — новый контекст, 429 — `Retry-After`,
400 — без повтора), профиль `mcp` включается в `prod.yml`/runbook деплоя. `eval-quick` — только с «да» владельца.

### 4.M5c. M5-CRM-01, M5-INF-01c
M5-CRM-01 — по ORCHESTRATOR §6 M5 (Q-M5-2). M5-INF-01c — `events.schema.json` read-only в `/packages/contracts/` сервисов ERP в
`prod.yml` и в `release.tgz`; `make deploy-check` на чистом клоне.

### 4.M5e. M5-ERP-01 — перенос данных старого прода
По ORCHESTRATOR §6 M5: скрипт `manage.py import_b2b` из дампа схемы тега `b2b-final` (компании, контакты, сделки, КП,
договоры, счета, документы) в новую схему; идемпотентен (внешний ключ старого id), отчёт сверки количеств и сумм. Внутренние
пометки из примечаний договоров (`Отменён …: причина`, e-mail сотрудников — дефект, закрытый FIX-4xb) в клиентские поля не
переносить. Реальный дамп — у владельца (OWNER-CHECKLIST «До M5»); тесты — на синтетическом дампе, созданном миграциями тега.

### 4.QA. M3-QA-01 — сквозной прогон
Telegram → лид → передача → заявка в ERP → КП → ссылка в боте → код акцепта в боте → акцепт в Cabinet → счёт → вопрос боту
«где счёт» → переключение CRM ↔ ERP; скриншоты/GIF, axe, отчёт `docs/runbooks/m3_qa_01_report.md`. Mini App — владелец на
телефоне через туннель (как в волне 5).
