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

### Средне-высокий — Шаг 3 (инвариант «не осиротить», сквозной)
`accounts/services/members.py:145/158/190-191/216` — «последний OWNER» завязан на WorkspaceRole
OWNER, тогда как в CompanyRole-мире уже есть параллельный инвариант на `is_system`
(`roles.py:_is_sole_active_system_admin`). **Риск:** два конкурирующих определения «последнего
админа» могут разойтись во время раскатки → окно осиротения. **Унифицировать на `is_system` и
мигрировать вместе, не по кускам.**

### Высший риск — Шаг 4 (data-миграция покрытия, НЕ код)
**Дефолт-шаблон «Менеджер по продажам» НЕ несёт `quote.review` / `quote.approve_final`** →
- legacy **FOREIGN_TRADE_SPECIALIST (ВЭД)** → «Менеджер по продажам» → **теряет право trade-review**;
- никто не получает `quote.review`, пока не выдать явно → `build_approval_chain` не находит
  reviewer'а, а `_fallback_head` (`approvals.py:39`, всё ещё OWNER-based) становится единственным
  апрувером → стадия trade-review для мигрированных тенантов исчезает.

**Data-миграция U3 ОБЯЗАНА:** явно выдать `quote.review` членам, деривированным из ВЭД, и
`quote.approve_final` — из DIRECTOR; перевести `_fallback_head` c `role__code=OWNER` на
is_system/`quote.approve_final`-держателя. **Сверить с миграцией
`accounts/migrations/0031_demote_overgranted_company_admins.py` перед финализацией.**

### Derivation-сайты (последними, низкий приоритет)
`permissions.py:67` (fallback), `permissions.py:398-403` (routed-company tie-break),
`approvals.py:39` (fallback head) — не жёсткие гейты, деградируют мягко; обновить, чтобы OWNER
WorkspaceRole можно было в итоге ретайрить.

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
- [ ] Ни один `has_workspace_role` / `WorkspaceRoleCode` не участвует в авторизации бизнес-действий
      (grep только в derivation/labels).
- [ ] Existing-тенанты не теряют доступ (data-миграция покрытия + тест «до/после прав», особенно ВЭД).
- [ ] Полный approval-FSM сьют зелёный + eyes-on заявка→КП→контракт на мигрированном тенанте.
- [ ] `_fallback_head` не зависит от WorkspaceRole OWNER.

## Тестовое покрытие (текущее — safety net для рефактора)
`test_quote_approval_chain.py` — плотно покрывает LIVE-цепочку (submit/review/approve/reject/recall/
endpoints), фикстуры создают И WorkspaceRole И CompanyRole. `test_permission_guards.py`,
`test_company_roles.py` — движок прав. Это защитная сетка для Шагов 1–4.
