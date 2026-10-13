# ТЗ — ADR-0005 Phase E U3: деприкация WorkspaceRole как enforcement-слоя

**База:** main после CRM-слоя (Фазы A–D). Статус: **инвентаризация выполнена** (этот документ) +
**Шаг 0 исполнен** (удалён мёртвый legacy-FSM — см. ниже). Остальные шаги — отдельными PR, **высокий
риск** (ядро прав на КП), обязателен eyes-on полной цепочки заявка→КП→контракт.

## Архитектурный контекст (главное)

В коде **две параллельные системы согласования КП**:

- **LEGACY WorkspaceRole 3-шаговый FSM** в `crm/services/quotes.py`: `submit_for_review` →
  `confirm_trade_review` → `director_approve` (+ `send_back`). Гейтился `has_workspace_role`.
- **LIVE унифицированная step-цепочка** в `crm/services/approvals.py`: `build_approval_chain` →
  `act_on_step` → `recall_quote`. **Уже полностью на `member_has_permission`** (`quote.review`,
  `quote.approve_final`).

`submit_for_review` — мост: WorkspaceRole-гейтит вход, затем строит цепочку и прыгает в
`PENDING_APPROVAL`. **`confirm_trade_review` / `director_approve` / `send_back` были МЁРТВЫМ КОДОМ**
(ноль вызовов, view, URL, тестов).

**Вывод:** реально исполняемая WorkspaceRole-enforcement-поверхность МАЛА — большинство гейтов КП
уже permission-based. U3 сводится к точечной замене нескольких сайтов + одной data-миграции покрытия.

## Шаг 0 — удаление мёртвого legacy-FSM ✅ ИСПОЛНЕНО

Удалены (верифицировано: ноль внешних вызовов): `QuoteLifecycleService.confirm_trade_review`,
`.director_approve`, `.send_back`, и `_ROLE_QUEUE_STATUSES` (`quotes.py`). Approval-chain тесты
(`test_quote_approval_chain.py`, 19) зелёные — подтверждает, что живая цепочка идёт через
`approvals.py`, а не через удалённое. Убирает путаницу «две системы».

## Существующий permission-движок (основа замены)

- `member_has_permission(user, company_id, perm)` — `accounts/services/permissions.py:48`
  (с legacy-fallback: OWNER→все, иначе can_sell/can_buy).
- `has_explicit_company_role_perm(user, company_id, perm)` — `crm/services/_params.py:12`
  (БЕЗ fallback — только явно выданная CompanyRole). Уже используется как defense-in-depth в
  send/accept/payment/contract.
- Permission-коды КП **все уже существуют** (`accounts/constants.py:27-55`, seed в миграциях
  0023/0030): `quote.build`, `quote.send`, `quote.review`, `quote.approve_final`, `quote.approve`,
  `quote.edit_pricing`, `team.manage`, `settings.edit`, `charge_templates.manage`, … — **новых
  кодов для цепочки НЕ нужно.**

## Таблица замен (по возрастанию риска)

### Тривиальные (view-гейты, чистое расширение) — Шаг 1 ✅ ИСПОЛНЕНО
| Сайт | Что гейтит | Замена | Статус |
|---|---|---|---|
| `accounts/views/company.py` `_assert_owner_or_admin` | правка профиля компании | `member_has_permission(settings.edit)` | ✅ |
| `accounts/views/company.py` `set_member_role` | смена роли члена | `member_has_permission(team.manage)` | ✅ |
| `crm/views/quotes.py` `ChargeTemplateViewSet._assert_company_admin` | CRUD ChargeTemplate | `member_has_permission(charge_templates.manage)` | ✅ |

Все три — **чистое расширение**: legacy-fallback `member_has_permission` пускает company_role-less OWNER,
а делегированный админ с нужным permission теперь тоже проходит (смысл движка прав). Никто не теряет
доступ. Прецедент: `company.py:635/738` (`update_member_capabilities`/`invite`, `team.manage`). Тесты:
`accounts/tests/test_workspace_role_deprecation_step1.py` (allow/deny/legacy-fallback × 3 гейта, 8 тестов).
`is_platform_admin`-байпас и `NO_SELLER_COMPANY`-precheck сохранены; неиспользуемые `WorkspaceRoleCode`-импорты убраны.

**`can_send_quote_to_client` ОТЛОЖЕН из Шага 1 в Шаг 4** — это единственное *сужение* (не расширение):
`has_explicit_company_role_perm(quote.send)` не имеет legacy-fallback, и продавец с `company_role=NULL`,
слащий КП по WorkspaceRole SALES_MANAGER/OWNER, потерял бы доступ. Data-check на dev-стеке: 0 таких
активных продавцов — но прод авторитетно не проверить, поэтому убираем этот WorkspaceRole-терм только
ВМЕСТЕ с data-миграцией покрытия Шага 4 (которая гарантирует `quote.send` каждому продавцу до сужения).

### Средний риск — Шаг 2 (живой гейт согласования)
| Сайт | Что гейтит | Замена | Риск |
|---|---|---|---|
| `quotes.py` `submit_for_review` (~:944) | DRAFT → цепочка (вход) | `member_has_permission(quote.build)` | ломает `test_submit_gate_requires_sales_role`; дефолт-шаблон «Менеджер по продажам» несёт `quote.build` → безопасная цель. Обновить тест. Сохранить OWNER-семантику (is_system покрывает) |

### Средне-высокий — Шаг 3 (инвариант «не осиротить», сквозной) ✅ ИСПОЛНЕНО
`accounts/services/members.py` — «последний OWNER» был завязан на WorkspaceRole OWNER, тогда как в
CompanyRole-мире уже есть параллельный инвариант на `is_system` (`roles.py:_is_sole_active_system_admin`).
Унифицировано на **единый предикат `_admin_floor_q()`**:

```python
Q(company_role__is_system=True) | Q(company_role__isnull=True, role__code=OWNER)
```

**Ключевой нюанс (найден при чтении тестов):** чистый переход на `company_role__is_system` был бы НЕ-безопасен
в ОБРАТНУЮ сторону — легаси-член `company_role=NULL + WorkspaceRole=OWNER` (админ через fallback в
`member_has_permission`) выпал бы из счётчика админов → удаление/деактивация единственного такого OWNER
**осиротила бы компанию**. Поэтому floor — это **объединение**: is_system ИЛИ легаси-NULL-OWNER. Это:
- защищает и мигрированных (is_system), и немигрированных (NULL+OWNER) → нет окна осиротения ни в одну сторону;
- держит все существующие тесты `test_member_invariants.py` зелёными (их фикстуры создают NULL-company_role
  OWNER — совпадают со второй ветвью объединения);
- унифицирует определение «последнего админа» с `roles.py` (который остаётся is_system-only — безопасно, т.к. он
  гейтит только переназначение ИЗ is_system).

Применено в `company_active_admins`, `remove_company_member`, `set_member_workspace_role`
(`would_stay_admin = is_system ∨ новая-роль-OWNER`), `toggle_user_active`.

### Высший риск — Шаг 4 (частично ИСПОЛНЕНО + одно ОСОЗНАННОЕ отложение)

**Что сделано:**
- `_fallback_head` (`approvals.py`) переведён c `role__code=OWNER` на `company_role__is_system=True` —
  is_system-админ всегда несёт `quote.approve_final`, поэтому `head_candidates` (permission-based) его и так
  находит, а fallback становится «поясом безопасности». Добавлен `logger.warning`, если голова = None
  (компания без единого админа — состояние, которое never-orphan предотвращает).
- `can_send_quote_to_client` (`quotes.py`, единственный сайт-*сужение*) — **fail-closed** гейт:
  `has_explicit_company_role_perm(quote.send)` (без can_sell-fallback) ∨ `_has_legacy_send_role` (мост для
  немигрированных: `company_role IS NULL` И WorkspaceRole ∈ {OWNER, SALES_MANAGER} — ТОЧНО старый гейт,
  но только для un-migrated). **Adversarial-verify (Opus, 4 линзы) нашёл дефект в первой версии** (я
  сначала поставил `member_has_permission(quote.send)`, чей can_sell-fallback авто-выдаёт отправку любому
  `company_role=NULL`-члену с can_sell=True по умолчанию — напр. LOGIST, добавленному оператором). Исправлено:
  fail-closed + мост НЕ читает can_sell. Отправка клиенту дополнительно тройно гейтится (роль →
  `assert_seller_can_operate` подписка/KYC → `quote.send` entitlement в `send_to_client`).
- **Корень (тоже исправлен):** `add_company_member` (оператор-путь) единственный НЕ сидил `company_role`
  (в отличие от `invite_workspace_member` / `submit_company_profile`) → плодил permission-less
  `company_role=NULL` членов. Теперь сидит `default_company_role_for(...)` при отсутствии (не затирая
  кастомную роль при ре-адде). Регресс-тесты: exploit denied, OWNER-мост passes, seeding works, re-add preserves.

**Осознанно ОТЛОЖЕНО (не регресс данного PR):**
- **Восстановление `quote.review` для ВЭД-деривированных членов.** Потеря ВЭД trade-review — это
  **пред-существующее состояние с миграции 0030** (ВЭД → «Менеджер по продажам» без quote.review), НЕ
  вводимое этим PR. `quote.approve_final` для DIRECTOR — **уже есть** (DIRECTOR → is_system «Администратор
  компании» с ALL-perms; 0031 исключает OWNER/DIRECTOR из демоушена). Явное восстановление ВЭД-reviewer
  требует ПРОДУКТОВОГО решения (новая сид-роль «Менеджер ВЭД» = «Менеджер по продажам» + quote.review, с
  переносом ВЭД-членов) и аддитивно (никто не теряет доступ) → отдельная задача, вне безопасного ядра U3.
  Критерий приёмки «existing-тенанты не теряют доступ» соблюдён: **данный PR не трогает права ВЭД.**

### Derivation-сайты — Шаг 5 (частично ИСПОЛНЕНО)
- `permissions.py` routed-company tie-break — переведён с WorkspaceRole `{OWNER, SALES_MANAGER}` на
  `member_has_permission(quote.build)`. ✅
- `has_workspace_role()` — стал МЁРТВЫМ (ноль вызовов после Шагов 1–4) → **удалён целиком**. ✅
- `approvals.py:39` fallback head — см. Шаг 4. ✅
- **`permissions.py:67` (legacy OWNER-fallback внутри `member_has_permission`) — ОСТАВЛЕН НАМЕРЕННО.**
  Это и есть та самая сеть безопасности, на которую опираются все остальные замены (can_send, never-orphan
  union, tie-break) для немигрированных `company_role=NULL` членов. Убирать её можно ТОЛЬКО после
  гарантии «ноль NULL-company_role активных членов на проде» (отдельная проверка + возможная финальная
  data-миграция). Ретайр самого `CompanyMember.role` (WorkspaceRole FK) — после этого.

## Follow-up (вне этого PR, зафиксировано adversarial-verify)
- **Внутренняя цепочка согласования** (`quote.review` / `quote.approve_final` в `approvals.py`) для
  `company_role=NULL` членов всё ещё падает в catch-all ветку `member_has_permission`
  (`return can_sell or can_buy`, `permissions.py:75`). Это ВНУТРЕННЕ (не клиент-facing), пред-существующее,
  НЕ трогается этим PR. После того как `add_company_member`-фикс + возможная финальная backfill-миграция
  гарантируют ноль NULL-company_role членов, эта ветка станет мёртвой и `permissions.py:67/75` fallback
  можно будет удалить целиком. До тех пор — оставить (сеть безопасности).
- **Восстановление ВЭД-reviewer** (новая сид-роль «Менеджер ВЭД» = «Менеджер по продажам» + `quote.review`)
  — продуктовое решение, аддитивно, отдельная задача.

## Порядок исполнения
1. **Шаг 0** (мёртвый код) — ✅ исполнено в этом PR.
2. **Шаг 1** (тривиальные view-гейты + `can_send_quote_to_client`) — отдельный PR, низкий риск,
   прецедент есть. Тесты на каждый гейт (allowed/denied по permission, не по WorkspaceRole).
3. **Шаг 2** (`submit_for_review` → `quote.build`) — с обновлением `test_submit_gate_requires_sales_role`
   + eyes-on полного submit→review→approve→send.
4. **Шаги 3+4 вместе** (never-orphan унификация на is_system + data-миграция покрытия ВЭД/DIRECTOR +
   `_fallback_head` off-OWNER) — **самый опасный PR**, максимум тестов + прогон цепочки на реальных
   тенантах, сверка с миграцией 0031.
5. **Derivation-сайты** — финальная зачистка, после чего `CompanyMember.role` (WorkspaceRole) —
   только лейбл/деривация, ни одно бизнес-ветвление на него не смотрит.

## Критерии приёмки (весь U3)
- [x] Ни один `has_workspace_role` не участвует в авторизации — функция **удалена** (ноль вызовов).
      `WorkspaceRoleCode` остаётся ТОЛЬКО в: `member_has_permission` legacy-fallback (`permissions.py:67`,
      осознанная сеть безопасности), `_admin_floor_q` легаси-ветвь, и derivation/labels
      (`_WORKSPACE_TO_ROLE`, applications, users-view). Ни одного жёсткого бизнес-гейта.
- [x] Existing-тенанты не теряют доступ: never-orphan union защищает и is_system, и легаси-NULL-OWNER;
      `can_send` через `member_has_permission` с fallback — никто не теряет отправку. (ВЭД-reviewer —
      пред-существующее 0030-состояние, вне этого PR; см. Шаг 4.)
- [x] Полный approval-chain сьют зелёный: `test_quote_approval_chain.py` + `test_permission_guards.py` +
      `test_member_invariants.py` + `test_roles_api.py` + `test_workspace_role_deprecation_step1.py` = 58 pass;
      весь accounts+crm = **537 pass**. Adversarial-verify (4 линзы) — чисто.
- [ ] eyes-on заявка→КП→контракт на мигрированном тенанте — рекомендуется прогнать в браузере после мержа.
- [x] `_fallback_head` не зависит от WorkspaceRole OWNER — теперь `company_role__is_system=True`.

## Тестовое покрытие (текущее — safety net для рефактора)
`test_quote_approval_chain.py` — плотно покрывает LIVE-цепочку (submit/review/approve/reject/recall/
endpoints), фикстуры создают И WorkspaceRole И CompanyRole. `test_permission_guards.py`,
`test_company_roles.py` — движок прав. Это защитная сетка для Шагов 1–4.
