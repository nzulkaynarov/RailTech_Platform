# Runbook: волна 2 — портал и Cabinet против настоящего ERP (FIX-21…24 ∥ FIX-11b)

Когда применять: контракт портала 0.2.0 (FIX-20) влит в `main`. Источник задач — `docs/audits/2026-10-18-main-e0f089e.md`
(«Волна 2»), статусы — `docs/PROGRESS.md`, правила — `ORCHESTRATOR.md` §3, §4.1, §7 и `CLAUDE.md` корня («Среда
разработки, тесты и CI»). Волну ведёт **одна сессия лида** (Claude Opus), исполнители — субагенты (Claude Sonnet),
по одному на задачу, каждый в своём worktree. Архитектор (Fable) принимает итог волны.

Цель волны (аудит): клиент проходит путь BUSINESS §4, шаги 4–10, в Cabinet на стенде `make up`, и каждый ответ портала
автоматически проверяется по `erp-portal.yaml`.

## 0. Промпт лида — вставить одним сообщением в `claude --model opus` в корне репозитория

```
Ты — лид разработки RailTech Platform (ORCHESTRATOR §4.1), ведёшь волну 2 исправлений по аудиту: FIX-21, FIX-22,
FIX-23, FIX-24 и параллельно FIX-11b. Работаешь в корне репозитория на ветке main; код сам не пишешь — ставишь задачи
субагентам-исполнителям, ревьюишь их PR и сливаешь.

Прочитай по порядку: CLAUDE.md корня (раздел «Среда разработки, тесты и CI»), ORCHESTRATOR.md (§3, §4, §4.1, §7),
docs/HANDOFF.md, docs/runbooks/wave2-agents.md (этот runbook — целиком), docs/PROGRESS.md (раздел «Исправления по
аудиту»), docs/DECISIONS.md (строки 2026-10-19), docs/CONTRACTS.md §4, packages/contracts/openapi/erp-portal.yaml.

Порядок работы:
1. Убедись, что worktree из §2 существуют (`git worktree list`) и зависимости в них установлены; чего нет — создай и
   поставь сам по §2. Запиши в docs/PROGRESS.md (журнал) строку «волна 2 запущена» — отдельным docs-PR не нужно,
   положишь её в PR закрытия волны.
2. Запусти субагентами (Agent tool, subagent_type general-purpose, model sonnet, run_in_background true) сразу три
   исполнителя: S1 (FIX-21), S4 (FIX-24), S5 (FIX-11b). Промпт каждого = §5.0 преамбула с подставленными
   значениями + его раздел §5.x. Каждому укажи его worktree и ERP_TEST_NS из §3.
3. Когда S1 доложит PR: ревью свежим субагентом (не исполнителем) строго по «готово, когда» §5.1 и чек-листу §6;
   блокеры — вернуть исполнителю одной строкой; без блокеров — `gh pr merge --auto --merge <n>`. CI не опрашивай и не
   жди: GitHub вольёт сам при зелёном «CI ok»; красный виден в PR — исполнитель воспроизводит локально и чинит.
4. После слияния FIX-21 запусти S2 (FIX-22) и S3 (FIX-23) — их worktree создаются от свежего main. Далее по §4.
5. S4 (FIX-24) работает с мока сразу, а финальную проверку против стенда делает после слияния FIX-21…23: скажи ему
   «ERP готов, проверяй на стенде» и дай адрес стенда из docs/HANDOFF.md §6.
6. Закрытие волны: все строки FIX-2x и FIX-11b в PROGRESS «готово» с PR; HANDOFF §3 «волна 2 закрыта, следующая —
   волна 3 ∥ волна 4»; хвосты ревью — в «Что осталось»; один docs-PR на автослиянии. Доложи архитектору: что влито,
   что осталось, что проверить глазами владельцу (скриншоты из PR FIX-24).

Правила, которые не обсуждаются: исполнитель PR не сливает; ревьюер ≠ исполнитель; стенд make up в основном каталоге
трогает только S4 на финальной проверке и только чтением (без make down/up); контракт erp-portal.yaml в этой волне
правит только архитектор — расхождение контракта и кода исполнитель записывает в docs/QUESTIONS.md и делает по
контракту; платных вызовов моделей нет. Если два исполнителя упёрлись в один файл (portal/views.py) — не
рефакторить файл целиком, слить по порядку §4 с `git merge origin/main` в ветке второго.
```

## 1. Исходное состояние (проверено 2026-10-19)

- `main` содержит волну 1 (PR #54–#64) и контракт портала 0.2.0 (FIX-20, PR #65). CI зелёный, автослияние включено.
- Факты кода, важные для волны (исследование архитектора, `apps/erp/backend/portal`):
  - Сериализаторы портала (`portal/serializers.py`) написаны не по контракту: `Invoice.paid_amount` вместо `paid`,
    статусы договора `draft|pending_signature|signed|active|…` вместо контрактных, у акта `signed`/`return_reason`,
    `DeliveryLine` — одна запись на `Fulfillment` с выдуманными «1 компл.», `Quote` без `public_url` (есть
    `crm/services/documents/public_page.py:public_quote_url`), строки КП всегда `kind="item"`.
  - `GET /quotes/{id}` → 500: `prefetch_related("items__product__unit_of_measure")`, поле называется `uom`
    (`catalog/models/products.py`). КП в согласовании видны клиенту: фильтр исключает только `DRAFT`.
  - Подпись договора и приёмка акта — прямая запись статусов в обход сервисов; возврат акта пишет статус NULL.
    Сервисы есть: `crm/services/contracts.py:sign_contract_by_client`, `crm/services/billing.py:sign_act`
    (скан — `Act.signed_file`), `reject_act`; все принимают `CustomUser`, субъект портала — `Contact`.
  - Код акцепта КП выпускает только публичная страница (`portal/public_views.py:PublicQuoteRequestCodeView` →
    `crm/services/public_page.py:issue_acceptance_code`, 6 цифр, 15 мин, 5 попыток); портальный accept без кода → 409.
  - Модели строки поставки нет: `Fulfillment` один на сделку (`sales/models/fulfillment.py`); приёмка по строкам — волна 2
    (DECISIONS 2026-10-18), статусы со склада — M4.
  - `GET /documents` не фильтрует ни по `kind`, ни по `deal_id`, отдаёт черновики; `POST /requests` падает на
    `Decimal(line.quantity or "1")` и выдумывает «1 шт»; сигнал события ставит `source="erp"`, потому что портал пишет
    `contact`, а не `client_id` (`integration/signals.py`).
  - Контрактного теста ответов портала нет; `jsonschema` уже в `requirements.txt`.
  - Cabinet (`apps/cabinet/src`): `pages/deliveries.tsx` — «Принять строку»/«Есть замечания» только тост;
    `pages/billing.tsx` — скан акта грузится в `/uploads` и никуда не привязывается; `ActionRequiredWidget` теряет КП
    `viewed` и показывает все неоплаченные счета; мок `MOCK_ACCEPT_CODE='2468'`; `public_url` не используется;
    запрос шлёт `size_bytes` во вложениях (контракт запрещает), подсказка «до 20 МБ» (контракт 10).
- Стенд владельца: `make up` на порту 8088, `PLATFORM_SSO_ENABLED=true`, коннектор ERP в CRM настроен (HANDOFF §6).

## 2. Рабочее место

Worktree — только `.claude/worktrees/<задача>` (ORCHESTRATOR §4.1). Архитектор создаёт S1, S4, S5 заранее; S2 и S3 лид
создаёт после слияния FIX-21 (от свежего `main`):

```bash
cd "$(git rev-parse --show-toplevel)" && git fetch origin && git worktree prune
git worktree add .claude/worktrees/fix-21  -b fix/erp-21-portal-serializers   origin/main
git worktree add .claude/worktrees/fix-24  -b fix/cabinet-24-real-portal     origin/main
git worktree add .claude/worktrees/fix-11b -b fix/all-11b-erp-sync-tails     origin/main
# после слияния FIX-21:
git worktree add .claude/worktrees/fix-22  -b fix/erp-22-portal-lifecycle     origin/main
git worktree add .claude/worktrees/fix-23  -b fix/erp-23-documents-requests   origin/main
# зависимости в каждом: make -C apps/erp install | make -C apps/cabinet install | make -C apps/crm install;
# cd packages/contracts && pnpm install --frozen-lockfile
```

Тесты ERP: `ERP_TEST_NS=<имя worktree> make -C apps/erp test-backend args="portal/tests/<файл>.py -x -q"` — свой набор
контейнеров на задачу. Docker Desktop 12 ГБ: стенд + два набора тестов ERP одновременно помещаются; третий — после
`make down` стенда (им управляет архитектор, лиду — спросить). Cabinet против стенда: `make -C apps/cabinet dev-stand`.

## 3. Раскладка

| Сессия | Задача | Ветка / worktree | `ERP_TEST_NS` | Зависит от | Размер | Зоны кода |
|---|---|---|---|---|---|---|
| S0 | лид: задачи, ревью, слияние, PROGRESS | `main` | — | — | — | только `docs/` |
| S1 | **FIX-21** сериализаторы по контракту + сторож + `POST /auth/magic` | `fix/erp-21-portal-serializers`, `.claude/worktrees/fix-21` | `fix21` | — | L | `portal/serializers.py`, `portal/views.py` (только форма ответов и auth), `portal/tests/test_contract_guard.py`, `portal/services/magic_link.py` |
| S2 | **FIX-22** жизненный цикл через сервисы, `request-code`, приёмка строк | `fix/erp-22-portal-lifecycle`, `.claude/worktrees/fix-22` | `fix22` | FIX-21 влит | L | `portal/views.py` (quotes, contracts, acts, deliveries), `portal/services/*`, `crm/services/{contracts,billing,public_page}.py`, `sales/models` (строка поставки), миграция |
| S3 | **FIX-23** документы и заявки | `fix/erp-23-documents-requests`, `.claude/worktrees/fix-23` | `fix23` | FIX-21 влит | M | `portal/views.py` (documents, requests, team), `portal/services/invitation.py`, `integration/signals.py`, шаблоны писем |
| S4 | **FIX-24** Cabinet против настоящего ERP | `fix/cabinet-24-real-portal`, `.claude/worktrees/fix-24` | — | контракт 0.2.0; финал — после FIX-21…23 | M | `apps/cabinet/src/**` |
| S5 | **FIX-11b** хвосты волны 1 | `fix/all-11b-erp-sync-tails`, `.claude/worktrees/fix-11b` | `fix11b` | — | S | CRM `app/services/erp_access.py`, `app/domain/external_erp_sync.py`, `packages/contracts/sso-token.md` (одна фраза), ERP `portal/throttles.py`, `portal/services/magic_link.py`, `core/logging.py` |

## 4. Порядок слияния и конфликтные зоны

1. **FIX-21** — первым: форма ответов — основа для всех. После слияния S2 и S3 стартуют от нового `main`.
2. **FIX-22** и **FIX-23** — параллельно, оба правят `portal/views.py` разными классами; кто сливается вторым, делает
   `git merge origin/main` и перегоняет `portal/tests`. Файл целиком не рефакторить и не разбивать в этой волне.
3. **FIX-24** — после FIX-21…23: финальная проверка против стенда, скриншоты в PR.
4. **FIX-11b** — в любой момент; зоны ни с кем не пересекаются (CRM + `portal/throttles.py`, `core/logging.py`).

`erp-portal.yaml` в волне не правит никто, кроме архитектора. Расхождение контракта и возможностей кода → строка в
`docs/QUESTIONS.md` (контекст → варианты → рекомендация) и реализация по контракту. Сгенерированные файлы
(`packages/contracts/generated/*`, `apps/cabinet/src/api/portal.d.ts`) не меняются, пока не меняется контракт.

## 5. Промпты для исполнителей

### 5.0. Общая преамбула (перед каждым промптом задачи)

```
Ты — исполнитель {РОЛЬ} RailTech Platform (ORCHESTRATOR §4.1). Работаешь ТОЛЬКО в worktree {ПУТЬ} (все команды из
него; корень репозитория и другие worktree не трогать), ветка {ВЕТКА}, одна задача: {ID}.
Прочитай по порядку: CLAUDE.md корня (раздел «Среда разработки, тесты и CI» — обязателен), ORCHESTRATOR.md (§3, §7),
docs/runbooks/wave2-agents.md (§1 — факты кода, §4), docs/audits/2026-10-18-main-e0f089e.md (волна 2 и находки
{НАХОДКИ}), CLAUDE.md приложения, которое правишь, docs/CONTRACTS.md §4 и packages/contracts/openapi/erp-portal.yaml
(контракт 0.2.0 — источник правды о форме ответов и кодах ошибок).

Правила, которые не обсуждаются:
- main защищена; PR только из этой ветки; PR не сливаешь — после открытия PR остановись и доложи лиду ссылкой.
- Локальная проверка — основная: итерации затронутыми тестами, перед коммитом make check-<приложение>, перед push —
  make ci-local по затронутым заданиям. CI не запускай вручную, не опрашивай (gh run, gh pr checks) и не жди.
- Контракт не правишь. Расхождение контракта и кода — строка в docs/QUESTIONS.md, делай по контракту.
- Один PR — одна задача; попутных рефакторингов нет. Тест-first: падающий тест на находку → правка; негативные тесты
  (чужая компания → 404, can_act=false → 403) обязательны на каждый новый или изменённый эндпоинт.
- Секретов нет; тестовые значения явно фейковые. Платных вызовов моделей нет. Стенд make up не трогать.
- Тесты ERP: ERP_TEST_NS={NS} make -C apps/erp test-backend args="<путь> -x -q". Зависимости уже установлены.
- Параллельно работают другие исполнители: {ПАРАЛЛЕЛЬНО}. Их файлы не трогай. В docs/PROGRESS.md правь только
  строку своей задачи и добавь одну строку в журнал — конфликт при слиянии разрешит лид.
- Коммиты: Conventional Commits на русском, суффикс ({ID}), трейлер Co-Authored-By: Claude <noreply@anthropic.com>.
- Финал: gh pr create (заголовок «{ID}: …»; тело — что, почему, как проверить, что обновлено в docs, открытые
  вопросы; для UI — скриншоты 1440/390 в docs/screens/{id}/), ссылка на PR в ответе — и стоп.
```

### 5.1. S1 — FIX-21 (ERP), `fix/erp-21-portal-serializers`, `ERP_TEST_NS=fix21`

```
Задача FIX-21 (P0, находки P-8, C-1): ответы портала строго по erp-portal.yaml 0.2.0 и сторож, который это
проверяет автоматически.

Готово, когда:
1. portal/serializers.py отдаёт ровно поля контракта (ни больше, ни меньше; nullable — как в контракте):
   ClientRequest (+ deal: DealRef|null, lines, attachments; source по факту, не константа), QuoteListItem/Quote
   (deal, public_url через crm.services.documents.public_page.public_quote_url, pdf_document_id, rejected_reason,
   lines с kind item|section|note|stage из структуры КП — заголовки разделов не терять; без vat_rate, items,
   payment_terms и прочих внутренних полей; sent_at — дата отправки, не updated_at), Contract (статусы ERP →
   sent|signed_by_client|signed_by_company|signed|cancelled; signed_by_client_at, signed_by_company_at; document_id —
   настоящий документ или null), Invoice (paid, не paid_amount; document_id), Act (issued|accepted|returned;
   returned_reason; document_id; scan_document_id), DeliveryLine (id, deal, line_no, title, quantity, unit, status,
   eta, tracking, shipped_at, accepted_at, remark — из строк подтверждённого заказа; пока модели строки поставки нет
   (её делает FIX-22) — строки из DealItem со статусом по Fulfillment, без выдуманных количеств: нет данных — null),
   Document (deal, kind с specification), остальные схемы — сверить. Каждому сериализатору — тест на форму.
2. Сторож portal/tests/test_contract_guard.py: загружает erp-portal.yaml (путь — как в
   catalog/tests/test_published_layer.py), резолвит $ref, и для КАЖДОГО GET-эндпоинта портала с фикстурами сущностей
   во всех статусах проверяет ответ jsonschema'ой по схеме ответа из контракта; сверх схемы — что множество ключей
   объекта ⊆ properties схемы (контракт без additionalProperties не значит «можно лишнее»); тела ошибок —
   detail ∈ ErrorCode. Падение сторожа — падение теста, не skip; без смонтированного контракта — fail с понятным
   сообщением (не skip).
3. POST /auth/magic {token} по контракту (та же логика, что GET /auth/magic/{token}; GET остаётся до FIX-24, оба
   покрыты тестами); ссылка в письме входа и приглашения ведёт на {CABINET_URL}/auth/magic#token=<токен> — токен во
   фрагменте, в пути нет; 403 FORBIDDEN архивной компании на обоих.
4. Лимиты контракта в коде: summary ≤ 5000, Reason ≤ 2000, uploads ≤ 10 МБ (настройка) — тесты на границы.
5. Все detail, которые отдаёт портал, есть в ErrorCode (тест перебирает коды в portal/).
6. make -C apps/erp check зелёный; make contracts без diff (контракт не менялся).
Не трогать: правила жизненного цикла (какие КП видны, подпись, приёмка — FIX-22), фильтрацию документов и POST
/requests (FIX-23). Если форма требует данных, которых в модели нет — поле null + строка в QUESTIONS, не выдумывать.
PR: «FIX-21: ответы портала по контракту 0.2.0, сторож по JSON Schema, POST /auth/magic».
```

### 5.2. S2 — FIX-22 (ERP), `fix/erp-22-portal-lifecycle`, `ERP_TEST_NS=fix22`, после слияния FIX-21

```
Задача FIX-22 (P0, находки P-3, P-5, P-6, P-7 + контракт 0.2.0: request-code, приёмка строк поставки, скан акта):
жизненный цикл в портале только через существующие сервисы ERP.

Готово, когда:
1. КП: клиенту видны только SENT, VIEWED, ACCEPTED, REJECTED, EXPIRED (списком, карточкой, акцептом — остальное 404);
   prefetch items__product__uom (не unit_of_measure) — GET /quotes/{id} с позицией из каталога 200; accept/reject
   возвращают сериализатор FIX-21 без 500.
2. POST /quotes/{id}/request-code → crm.services.public_page.issue_acceptance_code для контакта сессии: канал —
   telegram, если у контакта есть telegram_user_id и у ERP настроена отправка через бота, иначе e-mail через EmailLog;
   ни того ни другого → 422 CONTACT_CHANNEL_REQUIRED; ответ 202 AcceptanceCodeSent с маскированным адресом; лимит
   portal_accept. Accept: verify_code_and_accept; неверный/не запрошенный код → 409 QUOTE_CODE_INVALID; КП не в
   ожидании → 409 QUOTE_FINALIZED / QUOTE_EXPIRED. Reject: perform_quote_rejection, ValueError → 409.
3. Договор: POST /contracts/{id}/sign → crm.services.contracts.sign_contract_by_client; сервис принимает субъекта
   портала (Contact с can_act) — расширить сигнатуру минимально, без переписывания; статус в ответе по карте FIX-21;
   из неподходящего статуса → 409 CONTRACT_FINALIZED; черновик/отменённый клиенту не виден.
4. Акт: accept → crm.services.billing.sign_act (только из ISSUED; при upload_id — файл из PortalUpload в
   Act.signed_file, в ответе scan_document_id), return → reject_act(reason); 409 ACT_FINALIZED; приёмка не закрывает
   сделку мимо сервиса; возврат не пишет NULL.
5. Строки поставки: минимальная модель строки поставки на строке подтверждённого заказа (sales, одна миграция):
   status по DeliveryStatus контракта, eta, tracking, shipped_at, accepted_at, remark; GET /deliveries — из неё;
   POST /deliveries/{id}/accept (только delivered → accepted), /dispute {reason} (→ disputed, remark, задача
   менеджеру сделки через ActivityLog/уведомление ERP); 409 DELIVERY_LINE_NOT_ACCEPTABLE. События для CRM
   (delivery.line_accepted|disputed) — волна 3, здесь не слать и не менять events.schema.json.
6. Негативные тесты на каждый эндпоинт: чужая компания 404, can_act=false 403, повтор действия 409; сторож FIX-21
   зелёный на новых ответах. make -C apps/erp check зелёный.
Не трогать: документы, заявки, приглашения (FIX-23), форму сериализаторов сверх новых полей (FIX-21 уже влит).
PR: «FIX-22: жизненный цикл портала через сервисы — КП только отправленные, request-code, договор и акт через
sign_*, строки поставки с приёмкой».
```

### 5.3. S3 — FIX-23 (ERP), `fix/erp-23-documents-requests`, `ERP_TEST_NS=fix23`, после слияния FIX-21

```
Задача FIX-23 (P1, находки P-12, P-15, P-17): документы, заявки и приглашения в портале — честно.

Готово, когда:
1. GET /documents: только выпущенные документы клиентских видов (КП со статуса sent, договор, счёт, акт, спецификация,
   накладная); черновики и внутренние — никогда; фильтры kind и deal_id работают; deal: DealRef|null.
2. GET /documents/{id}/file: PDF КП, договора, счёта и акта — существующим рендером; не готов → 202 + Retry-After и
   постановка рендера в очередь (не пустое 202); готов → поток; каждая выдача — запись аудита (кто, что, когда).
3. POST /requests: quantity — десятичная строка или null, без выдуманных «1»; некорректный ввод → 422
   VALIDATION_ERROR (Decimal/InvalidOperation ловится); summary ≤ 5000; attachments только по upload_id из
   PortalUpload (неизвестный → 422 UPLOAD_NOT_FOUND); строки и вложения сохраняются и возвращаются в GET
   /requests/{id}; событие request.created с source=cabinet (поправить integration/signals.py: сделка от контакта
   портала — cabinet); ClientRequest.source — по факту.
4. POST /team/invite: канал telegram либо реально отправляет (если в ERP есть путь к боту CRM — через него), либо
   честно отвечает 422 INVALID_CHANNEL с пояснением, а не «отправлено»; письма приглашения и входа — в трёх локалях
   ru/uz/en с тестами на каждую (uz добавить).
5. Негативные тесты (чужая компания 404, can_act 403), сторож FIX-21 зелёный, make -C apps/erp check зелёный.
Не трогать: КП/договоры/акты/поставки (FIX-22), форму сериализаторов (FIX-21).
PR: «FIX-23: документы только выпущенные с PDF и аудитом, POST /requests без выдумок и с событием cabinet,
приглашение без ложного «отправлено»».
```

### 5.4. S4 — FIX-24 (Cabinet), `fix/cabinet-24-real-portal`

```
Задача FIX-24 (P0, находки C-1, C-2, C-3, C-4, C-8, C-10): Cabinet работает с настоящим порталом по контракту 0.2.0.

Готово, когда:
1. Сделка везде — deal {id, number, title} («Сделка № …» по number, заголовок — title); чтение deal_id снято во всём
   src (grep -rn "deal_id" src — только в d.ts и в фильтре GET /documents?deal_id=).
2. Акцепт КП: кнопка «Получить код» → POST /quotes/{id}/request-code → показ канала и маскированного адреса из
   AcceptanceCodeSent, затем ввод кода → accept; ошибки по ErrorCode (QUOTE_CODE_INVALID, QUOTE_FINALIZED,
   QUOTE_EXPIRED, CONTACT_CHANNEL_REQUIRED, TOO_MANY_REQUESTS — тексты ru/uz/en); MOCK_ACCEPT_CODE в моке остаётся
   только как значение, которое выдаёт мок request-code.
3. Поставки: «Принять» → POST /deliveries/{id}/accept, «Есть замечания» → /dispute {reason} (диалог с обязательной
   причиной); кнопки активны только при status=delivered; статусы accepted/disputed с remark и accepted_at в списке.
   Никаких тостов без запроса.
4. Акт: скан → POST /uploads → POST /acts/{id}/accept {upload_id}; после — ссылка на scan_document_id; без скана
   приёмка тоже возможна.
5. Вход по ссылке: маршрут /auth/magic читает token из фрагмента (#token=) и шлёт POST /auth/magic {token};
   маршрут с токеном в пути остаётся только редиректом на фрагмент (на переходный период); 429 на входе — понятный
   текст («Слишком много запросов, попробуйте через час»); 403 FORBIDDEN — «Доступ закрыт, обратитесь к менеджеру».
6. Виджет «Требует вашего решения»: КП sent И viewed; счета — только просроченные (status=overdue или due_date <
   сегодня при неоплате); ошибка загрузки — видимое состояние ошибки с повтором, не null.
7. errorElement на корневом маршруте; подсказки: суть до 5000, файл до 10 МБ; вложения без size_bytes; тексты уз/en.
8. Мок MSW приведён к 0.2.0 (request-code, deliveries accept/dispute, POST /auth/magic, статусы), фикстуры с deal.
   make -C apps/cabinet check зелёный (lint, tsc, i18n, tokens, api-types-check, vitest + axe).
9. Финал после слияния FIX-21…23 (лид скажет): make -C apps/cabinet dev-stand против стенда владельца
   (HANDOFF §6: cabinet.localhost:8088; вход по magic-link контакта тестовой компании — попроси лида выдать ссылку
   через ERP), пройти путь BUSINESS §4 шаги 4–10, скриншоты 1440 и 390 шести экранов (главная, запросы, КП с кодом,
   договор, акт со сканом, поставки) в docs/screens/fix-24/ и в теле PR; axe 0.
Не трогать: контракт и d.ts; бэкенды. Снятие deprecated полей из контракта и ERP — отдельная задача после волны.
PR: «FIX-24: Cabinet против настоящего портала — deal, код акцепта по запросу, приёмка строк, скан акта, вход по
фрагменту, виджет решений».
```

### 5.5. S5 — FIX-11b (CRM + ERP), `fix/all-11b-erp-sync-tails`, `ERP_TEST_NS=fix11b`

```
Задача FIX-11b (хвосты ревью и стенда волны 1; строка FIX-11b в docs/PROGRESS.md — полный список).

Готово, когда:
1. P1: задача erp_provision_user/erp_revoke_sessions в воркере CRM не отклоняет выдачу доступа из-за устаревшего
   TTL-кэша настроек коннектора (app/services/settings.py, 30 с): в задаче настройки коннектора читаются мимо кэша
   (или кэш сбрасывается при сохранении коннектора и в задаче), ERP_NOT_CONFIGURED считается временной ошибкой с
   повтором по расписанию попыток, и в users.erp_sync_error пишется понятный текст; тест: «коннектор сохранён →
   доступ выдан в ту же секунду → сопоставление создано»; тест: «коннектор не настроен → erp_sync_error заполнен,
   задача повторится».
2. Подсказка в app/domain/external_erp_sync.py соответствует поведению (повтор есть).
3. packages/contracts/sso-token.md: убрать обещание провижининга при смене почты (AccessState следит за ролями и
   именем) — одна фраза; make contracts без diff.
4. ERP: docs/DECISIONS.md — строка о токенах без claim tv (= версия 0, без массового разлогина) — по рекомендации.
5. ERP portal/throttles.py — мёртвая ветка ip: удалена или задокументирована тестом, что 401 раньше throttle;
   portal/services/magic_link.py — голый except Exception заменён на конкретные исключения брокера.
6. ERP core/logging.py: access-лог пишет строку и для ответов через исключение (410 по magic-link) — тест в
   TestAccessLog; токен по-прежнему [REDACTED].
7. make -C apps/crm check и make -C apps/erp check зелёные.
PR: «FIX-11b: выдача доступа к ERP не теряется из-за кэша настроек, хвосты ревью волны 1».
```

## 6. Цикл лида (S0)

1. Старт: §0 промпт → S1, S4, S5 параллельно; S2, S3 — после слияния FIX-21.
2. Ревью PR свежим субагентом (model opus или sonnet, read-only) по «готово, когда» задачи и чек-листу: контракт не
   менялся (`git diff origin/main -- packages/contracts` пуст, кроме FIX-11b п.3); негативные тесты есть; нет
   попутных правок вне зон §3; `make ci-local` упомянут в PR; строка в PROGRESS; для UI — скриншоты. Вердикт: блокеры →
   исполнителю одной строкой; иначе — `gh pr merge --auto --merge <n>`.
3. CI не опрашивать. Красный CI в PR → исполнитель воспроизводит `make ci-local <задание>` и чинит.
4. После каждого слияния — зависимым исполнителям: «влит FIX-NN, сделай git merge origin/main, перегони portal/tests».
5. Стопка: если два готовых PR конфликтуют по `PROGRESS.md`/`DECISIONS.md`, влить второй в первый и ставить `--auto` по
   порядку (ORCHESTRATOR §4.1).
6. Закрытие волны — §0 п.6. Хвосты ревью записать в PROGRESS «Что осталось» и, если набралось на задачу, — строкой
   FIX-2xb.

## 7. Если что-то идёт не так

- Исполнитель говорит «контракт не позволяет» → строка в QUESTIONS и реализация по контракту; контракт правит архитектор.
- Тесты ERP падают по памяти (код 137) → не больше двух `ERP_TEST_NS` одновременно; третьему — ждать.
- Исполнитель «заодно» рефакторит `portal/views.py` → отклонить: отдельная задача после волны.
- Два PR на один файл → слить по порядку §4, второй делает `git merge origin/main`; дубли строк в `PROGRESS.md`
  склеить вручную (грабли: `reference-merge-pitfalls`).
- GitHub не стартует CI («recent account payments have failed…») → владельцу, ветки не трогать.
